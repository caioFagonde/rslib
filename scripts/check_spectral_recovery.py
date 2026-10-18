"""Opt-in real SIGKILL recovery at a spectral export checkpoint, using local satellite inputs.

The harness only delays a production checkpoint. It does not supply analysis
values or alter the solver. A private data directory isolates this queue/server.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "1315d34695e8484093cf6a0ec3cdacad"
DATA = ROOT / "data" / "acceptance" / ("spectral-recovery-" + uuid.uuid4().hex)
(DATA / "runs").mkdir(parents=True)
(DATA / "runs" / SOURCE).symlink_to(ROOT / "data" / "runs" / SOURCE, target_is_directory=True)
marker = DATA / "checkpoint-reached"
with socket.socket() as reservation:
    reservation.bind(("127.0.0.1", 0))
    port = reservation.getsockname()[1]
base = f"http://127.0.0.1:{port}"
HARNESS = """import sys,time
from pathlib import Path
import uvicorn
from rslib.api import create_app
from rslib.jobs import Jobs
original=Jobs.checkpoint
def checkpoint(self,identifier,event):
    original(self,identifier,event)
    if event['phase']=='exporting':
        Path(sys.argv[2]).write_text(identifier)
        while True: time.sleep(.1)
Jobs.checkpoint=checkpoint
uvicorn.run(create_app(Path(sys.argv[1])),host='127.0.0.1',port=int(sys.argv[3]),log_level='warning')
"""
NORMAL = """import sys
from pathlib import Path
import uvicorn
from rslib.api import create_app
uvicorn.run(create_app(Path(sys.argv[1])),host='127.0.0.1',port=int(sys.argv[2]),log_level='warning')
"""


def until(check, seconds=25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (httpx.HTTPError, FileNotFoundError):
            pass
        time.sleep(0.05)
    raise RuntimeError("Timed out waiting for the owned recovery harness")


process = None
with (DATA / "server.log").open("w") as log, httpx.Client(base_url=base, timeout=3) as client:
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", HARNESS, str(DATA), str(marker), str(port)],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        until(lambda: client.get("/api/health").status_code == 200)
        submitted = client.post(
            "/api/jobs",
            json={"kind": "spectral", "spectral": {"run_id": SOURCE, "source_index": 2}},
        )
        submitted.raise_for_status()
        job = submitted.json()
        until(marker.exists)
        assert marker.read_text() == job["id"]
        before = client.get("/api/jobs/" + job["id"]).json()
        assert before["status"] == "running" and before["attempt"] == 1
        assert client.get(f"/api/analyses/{job['run_id']}/report.json").status_code == 404
        staging = DATA / "analyses" / f".{job['run_id']}.staging"
        assert staging.is_dir()
        os.kill(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
        process = subprocess.Popen(
            [sys.executable, "-c", NORMAL, str(DATA), str(port)],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        until(lambda: client.get("/api/health").status_code == 200)

        def completed():
            current = client.get("/api/jobs/" + job["id"]).json()
            if current["status"] == "failed":
                raise RuntimeError(current["error"])
            return current if current["status"] == "succeeded" else None

        done = until(completed)
        assert done["id"] == job["id"] and done["run_id"] == job["run_id"] and done["attempt"] == 2
        report = client.get(done["manifest_url"]).json()
        expected = json.loads((ROOT / "docs/showcase/35-live-spectral-report.json").read_text())
        assert report["input_checksums"] == expected["input_checksums"]
        assert report["fcls"] == expected["fcls"]
        events = client.get(f"/api/jobs/{job['id']}/events").json()["events"]
        assert sum(e["phase"] == "pca" for e in events) == 2
        assert any(e["phase"] == "recovered" for e in events)
        assert not staging.exists()
        evidence = {
            "synthetic": False,
            "source_run_id": SOURCE,
            "job_id": done["id"],
            "analysis_id": done["run_id"],
            "input_checksums": report["input_checksums"],
            "attempts": done["attempt"],
            "scratch_data_directory": str(DATA),
            "harness": "Delay only at exporting checkpoint; real SIGKILL before COG export/publication; restart without the delay",
            "assertions": {
                "incomplete_result_not_public": True,
                "same_job_and_result_identity_after_process_death": True,
                "same_pinned_input_checksums": True,
                "restarted_fit_matches_original_satellite_result": True,
                "staging_removed_after_publication": True,
                "recovery_and_both_fit_attempts_journaled": True,
            },
            "limitations": [
                "Only this deterministic checkpoint is a real process-death experiment. It does not establish storage-failure/load safety or every interruption window.",
                "Spectral recovery restarts the fit on the pinned prepared run; it does not resume the eigendecomposition or simplex solver internally.",
            ],
        }
        (ROOT / "docs/showcase/41-spectral-process-recovery.json").write_text(
            json.dumps(evidence, indent=2) + "\n"
        )
        print(json.dumps(evidence["assertions"], indent=2))
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
