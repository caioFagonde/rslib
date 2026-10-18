"""Exercise the built image offline, including queue persistence after restart."""

import argparse
import hashlib
import json
import subprocess
import uuid
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--image", default="rslib:jobs")
args = parser.parse_args()
name = "rslib-jobs-accept-" + uuid.uuid4().hex[:10]
helper = """
import json, time, sys
from urllib.request import Request, urlopen
from urllib.error import URLError
def api(path, body=None):
    req=Request('http://127.0.0.1:8000'+path, data=json.dumps(body).encode() if body is not None else None, headers={'Content-Type':'application/json'})
    with urlopen(req, timeout=10) as response: return json.load(response)
for _ in range(200):
    try:
        api('/api/health')
        break
    except URLError: time.sleep(.05)
else: raise RuntimeError('Container API did not start')
"""


def remote(code, *values):
    result = subprocess.run(
        ["docker", "exec", name, "python", "-c", helper + code, *values],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


try:
    subprocess.run(
        ["docker", "run", "--detach", "--name", name, "--network", "none", args.image],
        check=True,
        capture_output=True,
    )
    first = remote("""
job=api('/api/jobs', {'recipe':{'demo':True}})
for _ in range(500):
    job=api('/api/jobs/'+job['id'])
    if job['status'] in {'succeeded','failed'}: break
    time.sleep(.02)
assert job['status']=='succeeded', job
report=api(job['manifest_url'])
validation=api('/api/runs/'+job['run_id']+'/validation')
assert validation['synthetic'] and validation['summary']['scored_cells']>0
print(json.dumps({'job':job,'summary':report['summary'],'validation_summary':validation['summary']}))
""")
    subprocess.run(["docker", "restart", name], check=True, capture_output=True)
    second = remote(
        """
job=api('/api/jobs/'+sys.argv[1])
assert job['status']=='succeeded' and job['attempt']==1
with urlopen('http://127.0.0.1:8000/showcase/27-live-reconstruction-check.png') as response:
    import hashlib
    capture=hashlib.sha256(response.read()).hexdigest()
print(json.dumps({'job_id':job['id'],'run_id':job['run_id'],'status':job['status'],'capture_sha256':capture}))
""",
        first["job"]["id"],
    )
    assert second["job_id"] == first["job"]["id"]
    assert (
        second["capture_sha256"]
        == hashlib.sha256(
            Path("docs/showcase/27-live-reconstruction-check.png").read_bytes()
        ).hexdigest()
    )
    image = subprocess.run(
        ["docker", "image", "inspect", args.image, "--format", "{{.Id}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    evidence = {
        "image": args.image,
        "image_id": image,
        "network": "none",
        "first_execution": first,
        "after_restart": second,
        "assertions": {
            "completed_job_persisted": True,
            "same_run_id": second["run_id"] == first["job"]["run_id"],
            "offline_native_preparation": True,
            "evaluation_available": True,
            "gallery_matches_source": True,
        },
    }
    Path("docs/RUNTIME_ACCEPTANCE.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence["assertions"], indent=2))
finally:
    subprocess.run(["docker", "rm", "--force", name], check=False, capture_output=True)
