import json
import threading
import time
from io import BytesIO
from zipfile import ZipFile

import numpy as np
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from rslib.api import create_app
from rslib.cli import app
from rslib.jobs import Jobs, JobSpec, WorkerStopping
from rslib.spectral_request import SpectralRequest
from rslib.spectral_workflow import analyze_spectra
from rslib.workflows import StackRequest, run_stack_workflow


def wait(client, identifier, states=frozenset({"succeeded", "failed", "cancelled"})):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{identifier}").json()
        if job["status"] in states:
            return job
        time.sleep(0.02)
    raise AssertionError(job)


@pytest.fixture
def optical(tmp_path):
    return run_stack_workflow(StackRequest(), None, tmp_path)


def test_shared_recipe_api_cli_python_artifacts_and_input_identity(tmp_path, optical):
    direct = analyze_spectra(
        tmp_path / "runs" / optical["id"],
        tmp_path / "direct",
        source_index=1,
        components=2,
        endmembers=2,
        projection="affine",
        seed=19,
    )
    request = {"kind": "spectral", "spectral": direct["recipe"], "request_key": "a" * 32}
    with TestClient(create_app(tmp_path)) as client:
        response = client.post("/api/jobs", json=request)
        assert response.status_code == 202, response.text
        job = response.json()
        assert (
            job["kind"] == "spectral"
            and job["recipe"]["input_checksums"] == direct["input_checksums"]
        )
        assert client.post("/api/jobs", json=request).json()["id"] == job["id"]
        assert (
            client.post(
                "/api/jobs", json={**request, "spectral": {**request["spectral"], "seed": 20}}
            ).status_code
            == 409
        )
        done = wait(client, job["id"])
        assert done["status"] == "succeeded", done
        report = client.get(done["manifest_url"]).json()
        assert (
            report["pca"] == direct["pca"]
            and report["vca"] == direct["vca"]
            and report["fcls"] == direct["fcls"]
        )
        assert report["parent"]["request"] == optical["request"]
        base = f"/api/analyses/{done['run_id']}"
        cell = report["vca"]["cells"][0]
        pixel = client.get(base + f"/pixel?row={cell['row']}&col={cell['column']}").json()
        np.testing.assert_allclose(
            pixel["observed"], report["vca"]["observed_spectra"][0], atol=1e-7
        )
        assert pixel["valid"] and sum(pixel["abundance"]) == pytest.approx(1, abs=1e-7)
        assert client.get(base + "/pixel?row=1000000&col=0").status_code == 422
        bundle = ZipFile(BytesIO(client.get(base + "/bundle.zip").content))
        assert json.loads(bundle.read("report.json")) == report
        assert {"pca.tif", "abundance.tif", "report.html", "request.json"} <= set(bundle.namelist())
        html = client.get(base + "/report.html")
        assert html.status_code == 200 and "Parent monitoring project" in html.text
        assert client.get(base + "/stack.npz").status_code == 404
        # A copied request can be submitted by CLI without an implicit new source.
        spec = tmp_path / "saved-request.json"
        spec.write_bytes(bundle.read("request.json"))
        result = CliRunner().invoke(
            app, ["jobs", "submit", "--spec", str(spec), "--data", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
        spectral_jobs = [
            j for j in client.get("/api/jobs").json()["jobs"] if j["kind"] == "spectral"
        ]
        assert len(spectral_jobs) == 2
        other = next(j for j in spectral_jobs if j["id"] != job["id"])
        assert wait(client, other["id"])["status"] == "succeeded"
        assert (
            len(client.get("/api/jobs", params={"source_run_id": optical["id"]}).json()["jobs"])
            == 2
        )
        assert client.get("/api/jobs", params={"source_run_id": "f" * 32}).json()["jobs"] == []
        artifact = tmp_path / "analyses" / done["run_id"] / "pca.tif"
        original = artifact.read_bytes()
        artifact.write_bytes(original + b"corrupt")
        assert client.get(done["manifest_url"]).status_code == 422
        artifact.write_bytes(original)
        # Modified source cannot silently change a saved job's meaning.
        manifest = tmp_path / "runs" / optical["id"] / "manifest.json"
        manifest.write_text(manifest.read_text() + "\n")
        assert (
            client.post(
                "/api/jobs", json={"kind": "spectral", "spectral": report["recipe"]}
            ).status_code
            == 422
        )
        assert (
            client.get(base + f"/pixel?row={cell['row']}&col={cell['column']}").status_code == 422
        )


def test_spectral_cancel_before_publish_retry_and_corrupt_input(tmp_path, optical, monkeypatch):
    original = Jobs.checkpoint
    cancel = True

    def checkpoint(store, identifier, event):
        nonlocal cancel
        if event["phase"] == "publishing" and cancel:
            cancel = False
            store.cancel(identifier)
        return original(store, identifier, event)

    monkeypatch.setattr(Jobs, "checkpoint", checkpoint)
    with TestClient(create_app(tmp_path)) as client:
        job = client.post(
            "/api/jobs", json={"kind": "spectral", "spectral": {"run_id": optical["id"]}}
        ).json()
        assert wait(client, job["id"])["status"] == "cancelled"
        assert not (tmp_path / "analyses" / job["run_id"]).exists()
        assert client.get(f"/api/analyses/{job['run_id']}/report.json").status_code == 404
        assert not (tmp_path / "analyses" / f".{job['run_id']}.staging").exists()
        client.post(f"/api/jobs/{job['id']}/retry").raise_for_status()
        assert wait(client, job["id"])["status"] == "succeeded"
        phases = [e["phase"] for e in client.get(f"/api/jobs/{job['id']}/events").json()["events"]]
        assert {"verifying", "pca", "vca", "unmixing", "publishing"} <= set(phases)
        # Pin on submission, pause the running job before verification, mutate
        # the parent manifest, then ensure execution rejects even a valid stack.
        import rslib.spectral_workflow as module

        analyze = module.analyze_spectra
        started, release = threading.Event(), threading.Event()

        def paused(*args, **kwargs):
            started.set()
            assert release.wait(5)
            return analyze(*args, **kwargs)

        monkeypatch.setattr(module, "analyze_spectra", paused)
        second = client.post(
            "/api/jobs", json={"kind": "spectral", "spectral": {"run_id": optical["id"]}}
        ).json()
        assert started.wait(3)
        manifest = tmp_path / "runs" / optical["id"] / "manifest.json"
        manifest.write_text(manifest.read_text() + "\n")
        release.set()
        failed = wait(client, second["id"])
        assert failed["status"] == "failed" and "checksums" in failed["error"]["message"]
        assert not (tmp_path / "analyses" / second["run_id"]).exists()


def test_spectral_recovery_reconciles_published_result_without_refitting(
    tmp_path, optical, monkeypatch
):
    finish = Jobs.finish
    interrupted = False

    def stop_after_publish(store, identifier, **kwargs):
        nonlocal interrupted
        if kwargs.get("report") and not interrupted:
            interrupted = True
            raise WorkerStopping()
        return finish(store, identifier, **kwargs)

    monkeypatch.setattr(Jobs, "finish", stop_after_publish)
    with TestClient(create_app(tmp_path)) as client:
        job = client.post(
            "/api/jobs", json={"kind": "spectral", "spectral": {"run_id": optical["id"]}}
        ).json()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not interrupted:
            time.sleep(0.02)
        assert interrupted and (tmp_path / "analyses" / job["run_id"] / "report.json").exists()
    import rslib.spectral_workflow as module

    def unexpected(*args, **kwargs):
        raise AssertionError("Published result must not be fitted again")

    monkeypatch.setattr(module, "analyze_spectra", unexpected)
    with TestClient(create_app(tmp_path)) as client:
        done = wait(client, job["id"])
        assert done["status"] == "succeeded" and done["attempt"] == 2
        assert (
            len([j for j in client.get("/api/jobs").json()["jobs"] if j["kind"] == "spectral"]) == 1
        )


def test_spectral_job_schema_and_legacy_queue_migration(tmp_path, optical):
    store = Jobs(tmp_path / "projects.sqlite3")
    job = store.submit(JobSpec(recipe=StackRequest()))
    assert job["kind"] == "optical"
    with pytest.raises(ValueError):
        JobSpec(
            kind="spectral", spectral=SpectralRequest(run_id=optical["id"]), recipe=StackRequest()
        )
    with TestClient(create_app(tmp_path)) as client:
        for spectral in [
            {"run_id": "../invalid"},
            {"run_id": optical["id"], "source_index": 99},
            {"run_id": optical["id"], "components": True},
        ]:
            assert (
                client.post(
                    "/api/jobs", json={"kind": "spectral", "spectral": spectral}
                ).status_code
                == 422
            )


def test_terminal_submits_reopens_same_job_and_inspects_components(tmp_path, optical):
    import asyncio

    from textual.widgets import Button, DataTable, Input, Select, TabbedContent

    from rslib.tui import Workbench

    async def terminal():
        ui = Workbench(tmp_path)
        async with ui.run_test(size=(190, 60)) as pilot:
            ui.last_stack = optical
            ui.action_spectral()
            await ui.workers.wait_for_complete()
            ui.query_one("#sp-source", Select).value = "1"
            ui.query_one("#sp-seed", Input).value = "19"
            ui.run_spectral_job()
            await ui.workers.wait_for_complete()
            await pilot.pause(0.1)
            assert ui.spectral_report is not None
            job = ui.jobs.get_job(ui.selected_job_id)
            assert job["kind"] == "spectral" and job["status"] == "succeeded"
            assert ui.spectral_report["recipe"]["seed"] == 19
            assert ui.query_one("#spectral-values", DataTable).row_count == 6
            assert ui.query_one("#spectral-members", DataTable).row_count == 3
            assert ui.query_one("#tabs", TabbedContent).active == "spectral-tab"
            ui.query_one("#sp-map", Select).value = "pc-03.png"
            await pilot.pause(0.05)
            ui.spectral_report = None
            ui.open_selected_job()
            await ui.workers.wait_for_complete()
            assert ui.spectral_report["id"] == job["run_id"]
            assert ui.jobs.get_job(job["id"])["attempt"] == 1
            ui.query_one("#sp-row", Input).value = "999999"
            ui.inspect_spectral_cell()
            await ui.workers.wait_for_complete()
            assert "outside" in str(ui.query_one("#status").render()).lower()
            assert ui.query_one("#spectral-values", DataTable).row_count == 0
            (tmp_path / "runs" / optical["id"] / "manifest.json").unlink()
            ui.open_selected_job()
            await ui.workers.wait_for_complete()
            assert ui.spectral_report["id"] == job["run_id"]
            assert ui.spectral_input is None and ui.query_one("#sp-run", Button).disabled

    asyncio.run(terminal())


def test_reference_snapshot_requires_exact_inventory_and_never_claims_accuracy(tmp_path, optical):
    from rslib.references import check_reference
    from rslib.validation import verified_run_metadata

    report, checksums = verified_run_metadata(tmp_path / "runs" / optical["id"])
    case = {
        "id": "fixture",
        "status": "local_snapshot",
        "partition": "development",
        "run_id": optical["id"],
        "input_checksums": checksums,
        "independent_labels": [],
        **{k: report[k] for k in ["grid", "request", "bands", "synthetic"]},
        "observations": [
            {k: o[k] for k in ["id", "collection", "provider", "datetime", "platform"]}
            for o in report["observations"]
        ],
    }
    catalog = tmp_path / "references.json"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": "rslib-reference-projects/1",
                "cases": [case, {"id": "pending", "status": "pending_selection"}],
            }
        )
    )
    result = check_reference(catalog, tmp_path, "fixture")
    assert result["status"] == "input_snapshot_verified" and not result["accuracy_validated"]
    with pytest.raises(ValueError, match="selected"):
        check_reference(catalog, tmp_path, "pending")
    manifest = tmp_path / "runs" / optical["id"] / "manifest.json"
    manifest.write_text(manifest.read_text() + "\n")
    with pytest.raises(ValueError, match="checksums"):
        check_reference(catalog, tmp_path, "fixture")


def test_pre_kind_database_migration_preserves_old_idempotency_keys(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE jobs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE, submission TEXT NOT NULL,
                    recipe TEXT NOT NULL, project_id TEXT REFERENCES projects(id),
                    recipe_revision INTEGER, status TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL,
                    updated TEXT NOT NULL, inventory TEXT, progress TEXT NOT NULL,
                    error TEXT, run_id TEXT NOT NULL UNIQUE)""")
    store = Jobs(path)
    spec = JobSpec(recipe=StackRequest(), request_key="b" * 32)
    submitted = store.submit(spec)
    legacy = json.loads(spec.model_dump_json(exclude={"request_key", "kind", "spectral"}))
    with store.connect() as db:
        db.execute("UPDATE jobs SET submission=? WHERE id=?", (json.dumps(legacy), submitted["id"]))
    replay = Jobs(path).submit(spec)
    assert replay["id"] == submitted["id"] and replay["kind"] == "optical"
    assert len(store.list_jobs()) == 1
