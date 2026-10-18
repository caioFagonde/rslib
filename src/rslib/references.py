"""Check local reference snapshots without acquiring data or claiming label accuracy."""

import json
import re
from pathlib import Path

from rslib.validation import verified_run_metadata


def validate_partitions(cases: list[dict]) -> None:
    """Reject shared sites, overlapping AOIs and exact source IDs across partitions."""
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Reference case IDs must be unique")
    selected = [case for case in cases if case.get("partition") in {"development", "holdout"}]
    for i, left in enumerate(selected):
        for right in selected[i + 1 :]:
            if left["partition"] == right["partition"]:
                continue
            if left.get("site_group") and left["site_group"] == right.get("site_group"):
                raise ValueError("Reference partitions share a site group")
            a = left.get("request", {}).get("bbox")
            b = right.get("request", {}).get("bbox")
            if (
                a
                and b
                and (
                    max(a["west"], b["west"]) < min(a["east"], b["east"])
                    and max(a["south"], b["south"]) < min(a["north"], b["north"])
                )
            ):
                raise ValueError("Reference partitions have overlapping AOIs")
            if {o["id"] for o in left.get("observations", [])} & {
                o["id"] for o in right.get("observations", [])
            }:
                raise ValueError("Reference partitions share source observations")


def _check_documents(catalog: Path, case: dict) -> None:
    from rslib.reference_capture import ReferencePlan, _read_pinned, license_records, sha256

    documents = case.get("source_documents")
    if not documents:
        return  # Legacy snapshots report missing source/license evidence explicitly.
    root = catalog.parent.resolve()
    directory = (root / documents["directory"]).resolve()
    if not directory.is_relative_to(root):
        raise ValueError("Reference document directory must be inside the catalog directory")
    if set(documents["checksums"]) != {
        "selection.json",
        "inventory.json",
        "collections.json",
        "capture.json",
    }:
        raise ValueError("Reference source documents must include every pinned document")
    for name, digest in documents["checksums"].items():
        if name not in {"selection.json", "inventory.json", "collections.json", "capture.json"}:
            raise ValueError("Unexpected reference document path")
        if sha256(directory / name) != digest:
            raise ValueError(f"Reference source document checksum differs: {name}")
    pin = _read_pinned(directory)
    if pin["case"] != case["id"] or pin["run_id"] != case["run_id"]:
        raise ValueError("Reference capture identifies a different case/run")
    if pin["plan_sha256"] != case["selection_sha256"]:
        raise ValueError("Reference selection hash differs from the pinned capture")
    plan = ReferencePlan.model_validate_json((directory / "selection.json").read_text())
    selected = next((c for c in plan.cases if c.id == case["id"]), None)
    if (
        selected is None
        or any(
            case[key] != getattr(selected, key)
            for key in ["name", "site_group", "partition", "regimes"]
        )
        or case["request"] != selected.request.model_dump(mode="json")
    ):
        raise ValueError("Reference case differs from its original site/partition selection")
    records = json.loads((directory / "collections.json").read_text())["collections"]
    if license_records(records) != case["license_records"]:
        raise ValueError("Reference license records differ from captured source metadata")


def check_reference(catalog: Path, data: Path, identifier: str) -> dict:
    registry = json.loads(catalog.read_text())
    if registry.get("schema_version") != "rslib-reference-projects/1":
        raise ValueError("Unsupported reference-project catalog")
    validate_partitions(registry["cases"])
    case = next((c for c in registry["cases"] if c["id"] == identifier), None)
    if case is None:
        raise ValueError("Reference project not found")
    if case["status"] != "local_snapshot":
        raise ValueError("This reference case has not been selected and frozen")
    if not re.fullmatch(r"[0-9a-f]{32}", case["run_id"]):
        raise ValueError("Invalid reference run identifier")
    if not case.get("source_documents") and case["partition"] != "development":
        raise ValueError(
            "Legacy references without pinned source selections remain development-only"
        )
    _check_documents(catalog, case)
    report, checksums = verified_run_metadata(data / "runs" / case["run_id"])
    if checksums != case["input_checksums"]:
        raise ValueError("Reference input checksums differ from the frozen snapshot")
    for key in ["grid", "request", "bands", "synthetic"]:
        if report[key] != case[key]:
            raise ValueError(f"Reference {key} differs from the frozen snapshot")
    sources = [
        {key: observation[key] for key in ["id", "collection", "provider", "datetime", "platform"]}
        for observation in report["observations"]
    ]
    if sources != case["observations"]:
        raise ValueError("Reference observation inventory differs from the frozen snapshot")
    return {
        "case": identifier,
        "status": "input_snapshot_verified",
        "partition": case["partition"],
        "input_checksums": checksums,
        "observations": len(sources),
        "independent_labels": case["independent_labels"],
        "accuracy_validated": False,
        "source_metadata_captured": bool(case.get("source_documents")),
        "license_records": case.get("license_records", []),
        "known_findings": case.get("known_findings", []),
    }


def audit_references(catalog: Path, data: Path) -> dict:
    """Measure support and paired diagnostics without treating native QA as truth."""
    import numpy as np

    from rslib.agreement import compare_run
    from rslib.indices import spectral_index
    from rslib.validation import load_verified_run, validate_series

    registry = json.loads(catalog.read_text())
    validate_partitions(registry["cases"])
    cases, pending = [], []
    for case in registry["cases"]:
        if case["status"] != "local_snapshot":
            pending.append(case["id"])
            continue
        check = check_reference(catalog, data, case["id"])
        directory = data / "runs" / case["run_id"]
        stack, manifest, _ = load_verified_run(directory)
        inside = stack.analysis_mask()
        sources = []
        for i, source in enumerate(stack.observations):
            valid = np.isfinite(stack.values[i]).all(axis=0) & inside
            ndvi = spectral_index("ndvi", dict(zip(stack.bands, stack.values[i], strict=True)))
            values = ndvi[valid & np.isfinite(ndvi)]
            sources.append(
                {
                    "id": source["id"],
                    "datetime": source["datetime"],
                    "platform": source["platform"],
                    "clear_cells": int(valid.sum()),
                    "clear_fraction": float(valid.sum() / inside.sum()),
                    "ndvi_p05_p50_p95": np.percentile(values, [5, 50, 95]).tolist()
                    if values.size
                    else None,
                }
            )
        validation = (
            validate_series(
                stack,
                index=manifest["request"]["index"],
                max_gap_days=manifest["request"]["max_gap_days"],
            )
            if len(stack.daily().days) >= 3
            else {"status": "insufficient_acquisition_days", "summary": None}
        )
        agreement = compare_run(directory)
        start, end = manifest["request"]["datetime"].split("/")
        days = np.arange(
            np.datetime64(start[:10]), np.datetime64(end[:10]) + np.timedelta64(1, "D")
        )
        daily_query = stack.regular_series(
            step_days=1,
            start=start[:10],
            end=end[:10],
            index=manifest["request"]["index"],
            max_gap_days=manifest["request"]["max_gap_days"],
        )
        cases.append(
            {
                "id": case["id"],
                "name": case.get("name", case["id"]),
                "run_id": case["run_id"],
                "partition": case["partition"],
                "regimes": case["regimes"],
                "checks": check,
                "grid": manifest["grid"],
                "request": manifest["request"],
                "aoi_cells": int(inside.sum()),
                "sources": sources,
                "query_support": manifest["summary"],
                "daily_query_diagnostic": {
                    "description": "Same interval and gap limit, evaluated every UTC day; saved recipe/output unchanged.",
                    "dates": len(days),
                    "observed_fraction": float((daily_query.support[:, inside] == 1).mean()),
                    "filled_fraction": float((daily_query.support[:, inside] == 2).mean()),
                    "unsupported_fraction": float((daily_query.support[:, inside] == 0).mean()),
                },
                "query_timeline": [
                    {key: t[key] for key in ["day", "observed_fraction", "filled_fraction"]}
                    for t in manifest["timeline"]
                ],
                "coverage_notes": manifest["coverage_notes"],
                "temporal_holdout": validation,
                "sensor_agreement": agreement,
            }
        )
    return {
        "schema_version": "rslib-reference-audit/1",
        "cases": cases,
        "pending_cases": pending,
        "accuracy_validated": False,
        "limitations": [
            "Tiny preselected engineering cases; geographic names/regimes are selection intentions, not verified land-cover labels.",
            "Native QA support is not independently measured cloud-mask accuracy; snow is excluded by the current optical clear classes.",
            "Query-date support depends on the saved date step. Per-source clear support is reported separately.",
            "Temporal held-out clear observations and sensor pairs are diagnostic references, not ground truth. Unscored cells/dates remain in coverage denominators.",
            "Holdout partitions prohibit fitting/tuning on these cases. Inspection does not constitute an independently labeled accuracy evaluation.",
        ],
    }


def register_reference(catalog: Path, data: Path, snapshot: Path) -> dict:
    """Add a verified capture to a catalog; an existing frozen record is immutable."""
    import fcntl

    from rslib.reference_capture import ReferencePlan, _read_pinned, _snapshot, _write

    root = catalog.parent.resolve()
    directory = snapshot.parent.resolve()
    if not directory.is_relative_to(root):
        raise ValueError("Keep reference source documents inside the catalog directory")
    with catalog.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        registry = json.loads(catalog.read_text())
        if registry.get("schema_version") != "rslib-reference-projects/1":
            raise ValueError("Unsupported reference-project catalog")
        frozen = json.loads(snapshot.read_text())
        pin = _read_pinned(directory)
        plan = ReferencePlan.model_validate_json((directory / "selection.json").read_text())
        case = next(c for c in plan.cases if c.id == pin["case"])
        if _snapshot(directory, data, pin, case) != frozen:
            raise ValueError("Reference snapshot differs from pinned inputs")
        frozen["source_documents"]["directory"] = directory.relative_to(root).as_posix()
        old = next((c for c in registry["cases"] if c["id"] == frozen["id"]), None)
        if old and old["status"] == "local_snapshot" and old != frozen:
            raise ValueError("Existing frozen reference cannot be replaced; use a new case ID")
        updated = [c for c in registry["cases"] if c["id"] != frozen["id"]] + [frozen]
        validate_partitions(updated)
        _check_documents(catalog, frozen)
        registry["cases"] = updated
        _write(catalog, registry)
        return frozen
