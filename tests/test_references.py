"""Reference selection, public provenance and replay invariants; no live sources."""

import asyncio
import hashlib
import json

import pytest
from typer.testing import CliRunner

from rslib.cli import app
from rslib.reference_capture import ReferencePlan, acquire_reference, public_document
from rslib.references import check_reference, register_reference, validate_partitions
from rslib.stack import Observation


def selection(identifier="case", partition="development", west=1):
    return {
        "id": identifier,
        "name": "Offline contract fixture",
        "site_group": identifier,
        "partition": partition,
        "regimes": ["test fixture"],
        "request": {
            "demo": False,
            "bbox": {"west": west, "east": west + 0.01, "south": 1, "north": 1.01},
            "datetime": "2025-01-01/2025-01-31",
        },
    }


def plan(cases):
    return {
        "schema_version": "rslib-reference-plan/1",
        "created_utc": "2026-10-18",
        "purpose": "Offline contract test; no satellite or scientific accuracy assertion",
        "cases": cases,
    }


def test_plan_blocks_site_and_source_leakage():
    a, b = selection(), selection("other", "holdout")
    with pytest.raises(ValueError, match="disjoint"):
        ReferencePlan.model_validate(plan([a, b]))
    b["request"]["bbox"]["west"] = 2
    b["request"]["bbox"]["east"] = 2.01
    b["site_group"] = a["site_group"]
    with pytest.raises(ValueError, match="disjoint"):
        ReferencePlan.model_validate(plan([a, b]))
    b["site_group"] = "other"
    ReferencePlan.model_validate(plan([a, b]))
    a["observations"] = b["observations"] = [{"id": "shared-source"}]
    with pytest.raises(ValueError, match="source observations"):
        validate_partitions([a, b])
    a.pop("observations")
    b.pop("observations")
    with pytest.raises(ValueError, match="unique"):
        ReferencePlan.model_validate(plan([a, a]))
    a["request"]["demo"] = True
    with pytest.raises(ValueError, match="actual satellite"):
        ReferencePlan.model_validate(plan([a]))


@pytest.mark.parametrize("query", ["sig=private", "X-Amz-Signature=private", "token=private"])
def test_signed_inventory_is_never_published(query):
    with pytest.raises(ValueError, match="unsigned"):
        public_document({"assets": {"red": {"href": f"https://example.org/red.tif?{query}"}}})
    public_document({"href": "https://example.org/collection?limit=10"})


def test_capture_resume_and_document_pins(tmp_path, monkeypatch):
    import rslib.reference_capture as capture

    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan([selection()])))
    snapshots = tmp_path / "snapshots"
    data = tmp_path / "data"
    item = {
        "id": "offline-scene",
        "collection": "offline-collection",
        "properties": {"datetime": "2025-01-10T10:00:00Z", "platform": "sentinel-2b"},
        "assets": {"red": {"href": "https://example.org/red.tif"}},
    }
    counts = {"discovery": 0, "prepare": 0}

    async def discover(request):
        counts["discovery"] += 1
        return [Observation(item, "earth-search")], []

    class Client:
        async def collection(self, identifier):
            return {"id": identifier, "license": "proprietary", "links": []}

    interrupted = True

    async def prepare(request, data, *, inventory, run_id, resume, progress):
        # Only exercise the reference contract. No arrays or remote imagery are fabricated.
        nonlocal interrupted
        counts["prepare"] += 1
        assert inventory["observations"][0]["item"] == item and resume
        if interrupted:
            interrupted = False
            raise RuntimeError("Simulated interruption before publication")
        directory = data / "runs" / run_id
        directory.mkdir(parents=True)
        payload = b"Offline checksum payload; deliberately not a raster archive"
        (directory / "stack.npz").write_bytes(payload)
        manifest = {
            "schema_version": "rslib-stack-workflow/1",
            "id": run_id,
            "synthetic": False,
            "request": request.model_dump(mode="json"),
            "grid": {},
            "bands": ["red"],
            "observations": [
                {
                    "id": item["id"],
                    "collection": item["collection"],
                    "provider": "earth-search",
                    "datetime": item["properties"]["datetime"],
                    "platform": "sentinel-2b",
                }
            ],
            "outputs": [{"path": "stack.npz", "sha256": hashlib.sha256(payload).hexdigest()}],
        }
        (directory / "manifest.json").write_text(json.dumps(manifest))

    monkeypatch.setattr(capture, "discover_observations", discover)
    monkeypatch.setattr(capture, "client_for", lambda _: Client())
    monkeypatch.setattr(capture, "prepare_optical", prepare)
    with pytest.raises(RuntimeError, match="interruption"):
        asyncio.run(acquire_reference(path, "case", data, snapshots))
    pinned = json.loads((snapshots / "case" / "capture.json").read_text())
    result = asyncio.run(acquire_reference(path, "case", data, snapshots))
    assert result["run_id"] == pinned["run_id"] and counts == {"discovery": 1, "prepare": 2}
    assert result["license_records"][0]["declared_license"] == "proprietary"
    assert result["independent_labels"] == []
    assert asyncio.run(acquire_reference(path, "case", data, snapshots)) == result
    assert counts == {"discovery": 1, "prepare": 2}
    result["source_documents"]["directory"] = "snapshots/case"
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps({"schema_version": "rslib-reference-projects/1", "cases": [result]})
    )
    verified = check_reference(catalog, data, "case")
    assert verified["source_metadata_captured"] and not verified["accuracy_validated"]
    saved = snapshots / "case" / "snapshot.json"
    assert register_reference(catalog, data, saved) == result
    changed = json.loads(catalog.read_text())
    changed["cases"][0]["purpose"] = "A different frozen record"
    catalog.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="cannot be replaced"):
        register_reference(catalog, data, saved)
    changed["cases"][0] = result
    catalog.write_text(json.dumps(changed))
    cli = CliRunner().invoke(
        app,
        [
            "reference-acquire",
            "case",
            "--plan",
            str(path),
            "--data",
            str(data),
            "--snapshots",
            str(snapshots),
        ],
    )
    assert cli.exit_code == 0, cli.output
    assert json.loads(cli.output)["run_id"] == result["run_id"]
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="Selection plan changed"):
        asyncio.run(acquire_reference(path, "case", data, snapshots))
    document = snapshots / "case" / "inventory.json"
    document.write_text(document.read_text() + "\n")
    with pytest.raises(ValueError, match="Pinned reference document changed"):
        asyncio.run(acquire_reference(path, "case", data, snapshots))
    with pytest.raises(ValueError, match="source document checksum"):
        check_reference(catalog, data, "case")


def test_audit_distinguishes_query_sampling_from_observed_support(tmp_path):
    import numpy as np

    from rslib.references import audit_references
    from rslib.validation import load_verified_run
    from rslib.workflows import StackRequest, run_stack_workflow

    manifest = run_stack_workflow(StackRequest(), None, tmp_path)
    manifest_path = tmp_path / "runs" / manifest["id"] / "manifest.json"
    original_manifest = manifest_path.read_bytes()
    stack, _, digests = load_verified_run(tmp_path / "runs" / manifest["id"])
    case = {
        "id": "offline-synthetic",
        "status": "local_snapshot",
        "partition": "development",
        "regimes": ["explicit synthetic test"],
        "run_id": manifest["id"],
        "input_checksums": digests,
        "independent_labels": [],
        **{k: manifest[k] for k in ["grid", "request", "bands", "synthetic"]},
        "observations": [
            {k: o[k] for k in ["id", "collection", "provider", "datetime", "platform"]}
            for o in manifest["observations"]
        ],
    }
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps({"schema_version": "rslib-reference-projects/1", "cases": [case]})
    )
    result = audit_references(catalog, tmp_path)
    audited = result["cases"][0]
    assert not result["accuracy_validated"] and audited["checks"]["independent_labels"] == []
    assert audited["query_support"] == manifest["summary"]
    assert audited["request"]["step_days"] == 5
    daily = audited["daily_query_diagnostic"]
    assert daily["dates"] > manifest["summary"]["regular_dates"]
    inside = stack.analysis_mask()
    observed = np.isfinite(stack.daily().values).all(axis=1)[:, inside].sum()
    assert daily["observed_fraction"] == pytest.approx(observed / (daily["dates"] * inside.sum()))
    assert daily["observed_fraction"] + daily["filled_fraction"] + daily[
        "unsupported_fraction"
    ] == pytest.approx(1)
    assert manifest_path.read_bytes() == original_manifest
