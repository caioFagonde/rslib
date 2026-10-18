"""Freeze public STAC inventories before preparing small, preselected reference cases."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rslib.progress import Progress
from rslib.stac import client_for
from rslib.validation import verified_run_metadata
from rslib.workflows import StackRequest, discover_observations, prepare_optical


class ReferenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    name: str = Field(min_length=1, max_length=200)
    site_group: str = Field(min_length=1, max_length=100)
    partition: Literal["development", "holdout"]
    regimes: list[str] = Field(min_length=1)
    request: StackRequest

    @model_validator(mode="after")
    def actual_data(self):
        if self.request.demo:
            raise ValueError("Reference acquisitions require actual satellite inputs")
        if self.request.refresh:
            raise ValueError("A frozen reference must not refresh source preparation silently")
        return self


class ReferencePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["rslib-reference-plan/1"]
    created_utc: str
    purpose: str
    cases: list[ReferenceSelection] = Field(min_length=1)

    @model_validator(mode="after")
    def splits(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("Reference case IDs must be unique")
        for i, left in enumerate(self.cases):
            for right in self.cases[i + 1 :]:
                if left.partition == right.partition:
                    continue
                a, b = left.request.bbox, right.request.bbox
                overlap = max(a.west, b.west) < min(a.east, b.east) and max(a.south, b.south) < min(
                    a.north, b.north
                )
                if left.site_group == right.site_group or overlap:
                    raise ValueError("Development and holdout cases must use disjoint sites/AOIs")
        return self


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def public_document(value) -> None:
    """Reject credential-bearing URLs rather than publishing a redacted replay input."""
    if isinstance(value, dict):
        for child in value.values():
            public_document(child)
    elif isinstance(value, list):
        for child in value:
            public_document(child)
    elif isinstance(value, str) and value.startswith(("https://", "http://", "s3://")):
        parsed = urlsplit(value)
        keys = {key.lower() for key, _ in parse_qsl(parsed.query)}
        sensitive = {"sig", "token", "access_token", "api_key", "apikey", "key", "signature"}
        if (
            parsed.username
            or parsed.password
            or keys & sensitive
            or any(key.startswith(("x-amz-", "x-goog-")) for key in keys)
        ):
            raise ValueError("Reference documents must contain public unsigned URLs")


def _write(path: Path, value: dict) -> None:
    public_document(value)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    os.replace(temporary, path)


def _read_pinned(directory: Path) -> dict:
    pin = json.loads((directory / "capture.json").read_text())
    if pin.get("schema_version") != "rslib-reference-capture/1":
        raise ValueError("Unsupported reference capture")
    if set(pin["documents"]) != {"selection.json", "inventory.json", "collections.json"}:
        raise ValueError("Reference capture must pin selection, inventory and collection documents")
    for name, digest in pin["documents"].items():
        if name not in {"selection.json", "inventory.json", "collections.json"}:
            raise ValueError("Unexpected reference document path")
        if sha256(directory / name) != digest:
            raise ValueError(f"Pinned reference document changed: {name}")
    if not re.fullmatch(r"[0-9a-f]{32}", pin["run_id"]):
        raise ValueError("Invalid reference run identifier")
    return pin


def license_records(collections: list[dict]) -> list[dict]:
    return [
        {
            "provider": record["provider"],
            "collection": record["document"]["id"],
            "declared_license": record["document"].get("license"),
            "license_links": [
                link for link in record["document"].get("links", []) if link.get("rel") == "license"
            ],
            "providers": record["document"].get("providers", []),
            "interpretation": "Source metadata captured; no automatic legal clearance inferred.",
        }
        for record in collections
    ]


def _snapshot(directory: Path, data: Path, pin: dict, case: ReferenceSelection) -> dict:
    report, checksums = verified_run_metadata(data / "runs" / pin["run_id"])
    if report["synthetic"] or report["request"] != case.request.model_dump(mode="json"):
        raise ValueError("Prepared reference does not match the pinned satellite recipe")
    inventory = json.loads((directory / "inventory.json").read_text())
    selected = {
        (o["provider"], o["item"]["collection"], o["item"]["id"]) for o in inventory["observations"]
    }
    sources = [
        {key: o[key] for key in ["id", "collection", "provider", "datetime", "platform"]}
        for o in report["observations"]
    ]
    if not sources or any(
        (o["provider"], o["collection"], o["id"]) not in selected for o in sources
    ):
        raise ValueError("Prepared reference contains unpinned observations")
    collections = json.loads((directory / "collections.json").read_text())["collections"]
    return {
        "id": case.id,
        "name": case.name,
        "site_group": case.site_group,
        "status": "local_snapshot",
        "partition": case.partition,
        "regimes": case.regimes,
        "run_id": pin["run_id"],
        "input_checksums": checksums,
        **{key: report[key] for key in ["request", "grid", "bands", "synthetic"]},
        "observations": sources,
        "source_documents": {
            "directory": case.id,
            "checksums": {**pin["documents"], "capture.json": sha256(directory / "capture.json")},
        },
        "license_records": license_records(collections),
        "independent_labels": [],
        "purpose": "Input regression and support diagnostics. No independent accuracy labels.",
        "redistribution": "Prepared rasters remain local. Public source metadata and declared collection licenses are retained with this snapshot.",
        "selection_sha256": pin["plan_sha256"],
    }


async def acquire_reference(
    plan_path: Path,
    identifier: str,
    data: Path,
    snapshots: Path,
    *,
    progress: Progress | None = None,
) -> dict:
    """Resume one pinned acquisition. Published snapshots are verified, never replaced.

    The full selection plan and STAC documents are pinned before any raster read.
    Collection licenses are metadata evidence, not an inferred SPDX grant. Reuse
    verifies the prepared inputs; upstream assets may still change on reacquisition.
    """
    plan_bytes = plan_path.read_bytes()
    plan = ReferencePlan.model_validate_json(plan_bytes)
    case = next((case for case in plan.cases if case.id == identifier), None)
    if case is None:
        raise ValueError("Reference case not found in selection plan")
    directory = snapshots / identifier
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".capture.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("This reference case is already being acquired") from error
        if (directory / "capture.json").exists():
            pin = _read_pinned(directory)
            if pin["case"] != identifier:
                raise ValueError("Reference capture identifies a different case")
            if pin["plan_sha256"] != hashlib.sha256(plan_bytes).hexdigest():
                raise ValueError("Selection plan changed; choose a new snapshot directory")
            saved = directory / "snapshot.json"
            if saved.exists():
                frozen = json.loads(saved.read_text())
                actual = _snapshot(directory, data, pin, case)
                if actual != frozen:
                    raise ValueError("Published reference snapshot changed")
                return frozen
        else:
            observations, discovery = await discover_observations(case.request)
            pairs = sorted({(o.provider, o.item["collection"]) for o in observations})
            documents = await asyncio.gather(
                *(client_for(provider).collection(collection) for provider, collection in pairs)
            )
            collections = {
                "collections": [
                    {"provider": provider, "document": doc}
                    for (provider, _), doc in zip(pairs, documents, strict=True)
                ]
            }
            inventory = {
                "observations": [{"provider": o.provider, "item": o.item} for o in observations],
                "discovery": discovery,
            }
            _write(directory / "selection.json", json.loads(plan_bytes))
            _write(directory / "inventory.json", inventory)
            _write(directory / "collections.json", collections)
            pin = {
                "schema_version": "rslib-reference-capture/1",
                "case": identifier,
                "run_id": uuid.uuid4().hex,
                "captured_utc": datetime.now(UTC).isoformat(),
                "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
                "documents": {
                    name: sha256(directory / name)
                    for name in ["selection.json", "inventory.json", "collections.json"]
                },
            }
            _write(directory / "capture.json", pin)
        if not (data / "runs" / pin["run_id"]).exists():
            inventory = json.loads((directory / "inventory.json").read_text())
            await prepare_optical(
                case.request,
                data,
                inventory=inventory,
                run_id=pin["run_id"],
                resume=True,
                progress=progress,
            )
        result = _snapshot(directory, data, pin, case)
        _write(directory / "snapshot.json", result)
        return result
