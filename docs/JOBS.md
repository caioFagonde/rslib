# Durable preparation jobs

The optical browser and terminal submit jobs to the same local SQLite queue. A job snapshots its recipe and project revision. After discovery, the exact STAC candidate inventory is pinned before raster preparation. Reloading the browser follows the job ID rather than submitting another acquisition.

Use **Run preparation**, then open **Processing journal** to inspect scene IDs, cache use, clear fractions, measured support and export phases. **Cancel job** requests a cooperative stop. **Retry saved job** executes the same saved recipe and candidate inventory; it does not adopt later project edits. The URL contains the job ID and can be reopened. Recent jobs include failures and cancellations as well as completed runs.

In the terminal, `w` submits the current optical recipe and `j` opens **Jobs**. Select a row to inspect its journal, cancel it, retry it or open its completed result. The TUI uses an existing server worker when one owns the data directory; otherwise it starts a local worker. If that server exits, the terminal attempts to take over the queue. Quitting the terminal stops only its own worker.

## API

```bash
# Standalone recipe; response is HTTP 202 with a durable job ID.
curl -s http://127.0.0.1:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"recipe":{"demo":true},"request_key":"11111111111111111111111111111111"}'

# A saved project requires the revision the operator reviewed.
# POST /api/jobs {"project_id":"...","revision":3,"request_key":"..."}

curl -s http://127.0.0.1:8000/api/jobs/JOB_ID
curl -s 'http://127.0.0.1:8000/api/jobs/JOB_ID/events?after=0'
curl -s -X POST http://127.0.0.1:8000/api/jobs/JOB_ID/cancel
curl -s -X POST http://127.0.0.1:8000/api/jobs/JOB_ID/retry
```

`request_key` is optional. Repeating the same submission with the same key returns the existing job, including after a project changes. Reusing a key for a different submission returns 409. Project revision conflicts also return 409. A job's recipe is immutable. A retry increments its attempt count; it keeps its job ID, output run ID and snapshot. A fresh job is required to change inputs or processing choices.

`GET /api/jobs` lists the latest 50 jobs; `?project_id=...` filters them. The events endpoint returns at most 200 journal entries in ascending sequence order. Pass the last sequence as `after` to continue; sequences are monotonic across the database. Every event includes the attempt and UTC timestamp. No synthetic completion percentage is inferred from elapsed time.

States are `queued`, `running`, `cancelling`, `cancelled`, `failed`, `succeeded`. `manifest_url` is available only for a succeeded job. Output success is separate from coverage: a completed run can still have unsupported dates or an unmet acquisition goal.

The original `POST /api/stack` and `POST /api/projects/{id}/runs` remain blocking interfaces for compatibility. They use the preparation library but do not create durable job records. Use `/api/jobs` for recoverable execution.

## CLI

```bash
uv run rslib serve --data data
# Another terminal, same data directory:
uv run rslib jobs submit --project PROJECT_ID --data data
uv run rslib jobs submit --recipe recipe.json --data data
uv run rslib jobs list --data data
uv run rslib jobs show JOB_ID --data data
uv run rslib jobs cancel JOB_ID --data data
uv run rslib jobs retry JOB_ID --data data
```

Submitting through the CLI persists the job without requiring an HTTP connection. A server or TUI must be running to process it. Existing `rslib stack` and `rslib project run` are direct blocking commands.

## Recovery and limits

- One worker owner per data directory, enforced with an OS file lock. Run one API server process for that directory. The server bounds analysis concurrency at two and the durable queue at 32 active jobs. The TUI can share its queue. This implementation targets Linux/Unix and local storage; distributed workers, network-filesystem locking and Windows are not supported.
- A process exit releases the lock. On the next exclusive startup, interrupted jobs return to the queue, retaining their inventory and journal. Requested cancellations remain cancelled. A completed published result is reconciled with job/project state after a crash in that final transaction window.
- Completed prepared-scene cache files are atomic and reused on retry, including when the original job requested `refresh=true`. Evicted, corrupted or unfinished cache entries must be recomputed. To force fresh reads after an upstream change, submit a new job with refresh. Recovery assumes unchanged source assets and compatible software; it is not a reproducible cross-version migration protocol.
- Cancellation is checked between scene reads, acquisition evaluations and export batches. It cannot interrupt a running GDAL call. Catalog discovery must return before its next checkpoint. Graceful shutdown can therefore wait for bounded source timeouts. A failure's error type and last source checkpoint remain in the job record.
- Exports are written to private `data/.staging/<run-id>`, then atomically renamed into `data/runs/<run-id>` after the complete manifest is written. A retry rebuilds unfinished exports. Publication is the completion commit point: cancellation racing after it can result in successful completion. Scene preparation checkpoints are the recoverable work units; this is not byte-level resume of an interrupted range request.
- SQLite WAL stores jobs and events alongside projects. Preserve that database and the artifacts/cache volumes together. Hardware failure, storage corruption, quotas, automatic retention and multi-user authorization require further work. Old private staging directories are not automatically pruned.
- Report processing times describe the successful attempt. Failed-attempt work and queue time remain in the journal; they are not included in that report's processing timer.

## Acceptance evidence

[`accept_job_recovery.py`](https://github.com/caioFagonde/rslib/blob/main/scripts/accept_job_recovery.py) starts an isolated owned server, processes actual GDAL windows on explicitly synthetic multisensor rasters, sends SIGSTOP/SIGKILL after a prepared scene, and restarts it. The [recorded execution](showcase/26-job-recovery-evidence.json) recovered the same job/run as attempt 2, reused the completed scene cache and published one result. There is no injected processing delay or mocked raster read.

The [browser record](showcase/27-browser-job-validation-evidence.json) exercises cancellation, retry, reload during execution, one recipe submission across reloads, mobile layout and the actual held-out evaluation. [Terminal evidence](showcase/29-terminal-job-evidence.json) opens that same browser job's completed satellite result without another submission. These are local acceptance checks, not fault-tolerance or load-testing certification.

## Spectral analysis jobs

The queue now accepts two job kinds. Existing submissions default to `optical`; pre-kind database rows and idempotency submissions migrate compatibly. A spectral submission is:

```json
{
  "kind": "spectral",
  "spectral": {
    "run_id": "1315d34695e8484093cf6a0ec3cdacad",
    "source_index": 2,
    "components": 3,
    "endmembers": 3,
    "projection": "affine",
    "seed": 0
  }
}
```

Submission verifies the optical source and records both `stack.npz` and `manifest.json` SHA256 in the persisted recipe. Exported `request.json` includes these expected hashes and can be resubmitted with `rslib jobs submit --spec request.json --data data`. A changed or missing source fails explicitly. Reopening a job does not submit another fit. `GET /api/jobs?source_run_id=RUN_ID` lists the most recent 50 spectral jobs belonging to that input run; direct job URLs remain available for older records.

Spectral `run_id` in the job record is its result/analysis ID; `job.recipe.run_id` is the parent optical run. Results are published under `data/analyses/ANALYSIS_ID`, with a spectral `report.json` rather than an optical `manifest.json`. The succeeded job's `manifest_url` resolves to `/api/analyses/ANALYSIS_ID/report.json`. Published artifact hashes are verified before that report is served or a recovered published result is reconciled. Spectral jobs do not masquerade as optical runs in project history.

Checkpoints cover verification, PCA, VCA, every 4,096 FCLS cells and export/publication. Cancellation cannot interrupt a running eigendecomposition or GDAL export mid-call. A retry/restart recomputes an unfinished fit on the same pinned prepared input, without acquiring scenes again; partial numerical solver state is not checkpointed. Exports use private `data/analyses/.ANALYSIS_ID.staging`. Cancellation during export cleans that attempt up; a retry replaces an old private export directory before writing fresh exports. A crash or cancellation before that cleanup can leave an unserved staging directory. Atomic rename publishes the complete result and bundle. Publication remains the completion boundary if cancellation races with it.

A report bundle contains COGs, PNG previews, full coefficient/source metadata, a printable parent-project report and a saved request. The parent source cube is referenced by hash, not duplicated. Installed runtime versions and implementation source hashes are recorded; cross-version replay equivalence is not assumed. Preserve parent runs, the database and analysis directories together for source-cell inspection and reproduction. Saved analysis artifacts remain viewable if the parent input is unavailable, with inspection/re-execution errors explicit.

[Working browser](showcase/37-queued-spectral-workbench.png) · [report](showcase/38-spectral-project-report.png) · [same-job terminal/four-interface parity](showcase/40-spectral-interface-parity.json) · [real SIGKILL recovery](showcase/41-spectral-process-recovery.json). The recovery harness delays only an export checkpoint, kills an isolated owned server and restarts it on the same actual satellite input. It measures that interruption window; storage-failure and load coverage remain incomplete.
