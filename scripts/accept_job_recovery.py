"""Kill an owned API process after a prepared scene; restart the same durable job.

Uses real native processing on explicitly synthetic raster fixtures. No injected
worker delay, fake status, or mocked acquisition is used. Only this script's
isolated server process group is signalled.
"""

import argparse
import json
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8769)
args = parser.parse_args()
root = Path.cwd()
data = root / "data" / f"job-recovery-{uuid.uuid4().hex[:8]}"
data.mkdir(parents=True)
url = f"http://127.0.0.1:{args.port}"
proc = None
log = (data / "server.log").open("w")


def request(path, body=None):
    req = Request(
        url + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=10) as response:
        return json.load(response)


def start():
    global proc
    proc = subprocess.Popen(
        [
            str(root / ".venv/bin/python"),
            "-m",
            "uvicorn",
            "rslib.api:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
        ],
        env={**os.environ, "RSLIB_DATA": str(data)},
        stdout=log,
        stderr=log,
        start_new_session=True,
    )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"Owned server exited; see {data / 'server.log'}")
        try:
            request("/api/health")
            return
        except URLError:
            time.sleep(0.05)
    raise TimeoutError("Owned server did not start")


def stop(sig=signal.SIGTERM):
    global proc
    if proc is not None and proc.poll() is None:
        os.killpg(proc.pid, sig)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
    proc = None


try:
    start()
    job = request(
        "/api/jobs",
        {
            "recipe": {"demo": True, "refresh": True, "step_days": 1},
            "request_key": uuid.uuid4().hex,
        },
    )
    identifier = job["id"]
    deadline = time.monotonic() + 15
    events = []
    while time.monotonic() < deadline:
        events = request(f"/api/jobs/{identifier}/events")["events"]
        if any(e["phase"] == "prepared" for e in events):
            # Freeze the owned process before reading the interruption evidence.
            os.killpg(proc.pid, signal.SIGSTOP)
            break
        time.sleep(0.005)
    else:
        raise AssertionError("No scene checkpoint appeared")
    cached_before = len(list((data / "cache/prepared").glob("*.npz")))
    assert cached_before >= 1
    assert not (data / "runs" / job["run_id"] / "manifest.json").exists(), (
        "Job completed before interruption"
    )
    stop(signal.SIGKILL)
    start()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        recovered = request(f"/api/jobs/{identifier}")
        if recovered["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.04)
    assert recovered["status"] == "succeeded", recovered
    assert recovered["attempt"] == 2
    assert recovered["inventory_count"] == 8
    report = request(recovered["manifest_url"])
    assert report["request"]["refresh"] is True
    assert report["summary"]["cache_hits"] >= cached_before
    events = request(f"/api/jobs/{identifier}/events")["events"]
    assert any(e["phase"] == "recovered" for e in events)
    assert len(list((data / "runs").iterdir())) == 1
    evidence = {
        "input": "Explicitly synthetic multisensor fixture; real Rasterio/GDAL processing",
        "interruption": "SIGSTOP then SIGKILL of this script's owned API process group after a prepared-scene checkpoint",
        "data_directory": str(data.relative_to(root)),
        "job_id": identifier,
        "cached_scenes_before_kill": cached_before,
        "job": recovered,
        "summary": report["summary"],
        "outputs": report["outputs"],
        "events": events,
        "assertions": {
            "same_job_and_run_id": recovered["run_id"] == job["run_id"],
            "second_attempt": recovered["attempt"] == 2,
            "prepared_cache_reused": report["summary"]["cache_hits"] >= cached_before,
            "no_public_partial_result": True,
            "single_published_run": True,
        },
    }
    Path("docs/showcase/26-job-recovery-evidence.json").write_text(
        json.dumps(evidence, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                k: evidence[k]
                for k in ["data_directory", "job_id", "cached_scenes_before_kill", "assertions"]
            },
            indent=2,
        )
    )
finally:
    stop()
    log.close()
