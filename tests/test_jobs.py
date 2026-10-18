import time

import pytest
from fastapi.testclient import TestClient

from rslib.api import create_app
from rslib.jobs import JobConflict, Jobs, JobSpec
from rslib.workflows import StackRequest


def wait_job(client, identifier, status):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{identifier}").json()
        if job["status"] in status:
            return job
        time.sleep(0.02)
    raise AssertionError(job)


def test_job_failure_retry_keeps_revision_inventory_and_reuses_cache(tmp_path, monkeypatch):
    import rslib.stack as module

    prepare = module.prepare_scene
    calls = []

    def fail_second(*args, **kwargs):
        calls.append(args[0]["id"])
        if len(calls) == 2:
            raise RuntimeError("simulated lost source connection")
        return prepare(*args, **kwargs)

    monkeypatch.setattr(module, "prepare_scene", fail_second)
    with TestClient(create_app(tmp_path)) as client:
        project = client.post(
            "/api/projects", json={"name": "Snapshot", "recipe": {"demo": True, "refresh": True}}
        ).json()
        response = client.post(
            "/api/jobs", json={"project_id": project["id"], "revision": 1, "request_key": "a" * 32}
        )
        assert response.status_code == 202
        identifier = response.json()["id"]
        assert (
            client.post(
                "/api/jobs",
                json={"project_id": project["id"], "revision": 1, "request_key": "a" * 32},
            ).json()["id"]
            == identifier
        )
        assert (
            client.post(
                "/api/jobs", json={"recipe": {"demo": True}, "request_key": "a" * 32}
            ).status_code
            == 409
        )
        failed = wait_job(client, identifier, {"failed"})
        assert failed["inventory_count"] == 8
        assert failed["error"]["code"] == "RuntimeError"
        assert not (tmp_path / "runs" / failed["run_id"]).exists()
        # The user changes the saved project after the failed attempt. A retry
        # must execute revision 1, not silently switch scientific inputs.
        client.post(
            f"/api/projects/{project['id']}",
            json={"name": "Changed", "revision": 1, "recipe": {"demo": True, "index": "nbr"}},
        ).raise_for_status()
        assert client.post(f"/api/jobs/{identifier}/retry").status_code == 202
        complete = wait_job(client, identifier, {"succeeded", "failed"})
        assert complete["status"] == "succeeded", complete
        assert complete["attempt"] == 2
        report = client.get(complete["manifest_url"]).json()
        assert report["request"]["index"] == "ndvi"
        assert report["request"]["refresh"] is True
        assert report["summary"]["cache_hits"] == 1
        assert report["id"] == failed["run_id"]
        assert len(calls) == 9  # 8 successful scene reads plus the one failure.
        history = client.get(f"/api/projects/{project['id']}").json()["runs"]
        assert len(history) == 1 and history[0]["recipe_revision"] == 1
        events = client.get(f"/api/jobs/{identifier}/events").json()["events"]
        assert {e["attempt"] for e in events} == {0, 1, 2}
        cursor = events[2]["sequence"]
        assert all(
            e["sequence"] > cursor
            for e in client.get(f"/api/jobs/{identifier}/events?after={cursor}").json()["events"]
        )
        assert client.post(f"/api/jobs/{identifier}/retry").status_code == 409
        # A terminal attached while the API owns the worker reads the same
        # journal and opens its result without launching a duplicate worker/job.
        import asyncio

        from rslib.tui import Workbench

        async def terminal():
            app = Workbench(tmp_path)
            async with app.run_test(size=(150, 45)) as pilot:
                assert app.job_runner.lock is None
                app.selected_job_id = identifier
                app.action_jobs()
                await pilot.pause(0.05)
                app.open_selected_job()
                assert app.last_stack["id"] == report["id"]
                assert len(app.jobs.list_jobs()) == 1

        asyncio.run(terminal())
        # Simulate a crash in the final commit window: exports are published,
        # but a late cancellation and stale state remain in the job database.
        store = Jobs(tmp_path / "projects.sqlite3")
        with store.connect() as db:
            db.execute(
                "UPDATE jobs SET status='cancelling',cancel_requested=1 WHERE id=?", (identifier,)
            )
    # Completed jobs and their project references survive a new application.
    with TestClient(create_app(tmp_path)) as client:
        reconciled = wait_job(client, identifier, {"succeeded"})
        assert reconciled["attempt"] == 3 and not reconciled["cancel_requested"]
        assert len(calls) == 9  # Reconcile the published result without re-reading scenes.
        assert len(client.get(f"/api/projects/{project['id']}").json()["runs"]) == 1


def test_cancellation_checkpoints_and_retry(tmp_path, monkeypatch):
    import rslib.jobs as module

    original = module.prepare_optical
    import asyncio
    import threading

    ready, release = threading.Event(), threading.Event()

    async def paused(*args, **kwargs):
        ready.set()
        await asyncio.to_thread(release.wait, 5)
        return await original(*args, **kwargs)

    monkeypatch.setattr(module, "prepare_optical", paused)
    with TestClient(create_app(tmp_path)) as client:
        job = client.post("/api/jobs", json={"recipe": {"demo": True}}).json()
        assert ready.wait(3)
        assert client.post(f"/api/jobs/{job['id']}/cancel").json()["status"] == "cancelling"
        release.set()
        cancelled = wait_job(client, job["id"], {"cancelled"})
        assert cancelled["manifest_url"] is None
        assert not (tmp_path / "runs" / job["run_id"]).exists()
        client.post(f"/api/jobs/{job['id']}/retry").raise_for_status()
        assert wait_job(client, job["id"], {"succeeded", "failed"})["status"] == "succeeded"


def test_recovery_retains_cancel_and_pinned_inventory(tmp_path):
    store = Jobs(tmp_path / "projects.sqlite3")
    first = store.submit(JobSpec(recipe=StackRequest()))
    store.claim()
    inventory = {"observations": [{"item": {"id": "pinned"}, "provider": "test"}], "discovery": []}
    store.checkpoint(
        first["id"], {"phase": "inventory", "message": "Pinned", "inventory": inventory}
    )
    second = store.submit(JobSpec(recipe=StackRequest()))
    store.claim()
    store.cancel(second["id"])
    store.recover()
    assert store.get_job(first["id"])["status"] == "queued"
    assert store.get_job(second["id"])["status"] == "cancelled"
    assert store.inventory(first["id"]) == inventory
    assert store.claim()["attempt"] == 2
    queued = store.submit(JobSpec(recipe=StackRequest()))
    assert store.cancel(queued["id"])["status"] == "cancelled"
    with pytest.raises(JobConflict):
        store.retry(first["id"])


def test_cancelled_exports_remain_private_until_successful_retry(tmp_path, monkeypatch):
    checkpoint = Jobs.checkpoint
    cancelled = False

    def cancel_before_publish(self, identifier, event):
        nonlocal cancelled
        if event["phase"] == "publishing" and not cancelled:
            cancelled = True
            self.cancel(identifier)
        return checkpoint(self, identifier, event)

    monkeypatch.setattr(Jobs, "checkpoint", cancel_before_publish)
    with TestClient(create_app(tmp_path)) as client:
        job = client.post("/api/jobs", json={"recipe": {"demo": True}}).json()
        wait_job(client, job["id"], {"cancelled"})
        assert (tmp_path / ".staging" / job["run_id"] / "manifest.json").exists()
        assert client.get(f"/api/runs/{job['run_id']}/manifest.json").status_code == 404
        client.post(f"/api/jobs/{job['id']}/retry").raise_for_status()
        finished = wait_job(client, job["id"], {"succeeded", "failed"})
        assert finished["status"] == "succeeded"
        report = client.get(finished["manifest_url"]).json()
        assert report["summary"]["cache_hits"] == 8
        assert not (tmp_path / ".staging" / job["run_id"]).exists()
