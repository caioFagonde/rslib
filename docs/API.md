# Python and HTTP interfaces

The library, CLI, browser and TUI use the same optical preparation and spectral-analysis core. Run `uv run rslib serve` to expose the HTTP API. Its generated interactive contract is available at [localhost:8000/docs](http://127.0.0.1:8000/docs), and its OpenAPI schema at [localhost:8000/openapi.json](http://127.0.0.1:8000/openapi.json).

## Python preparation

```python
import asyncio
from pathlib import Path
from rslib.workflows import StackRequest, prepare_optical

# Synthetic data are explicitly selected. Set demo=False with your actual AOI/dates
# for live discovery; no synthetic fallback is used when a live request fails.
result = asyncio.run(prepare_optical(StackRequest(demo=True), Path("data")))
print(result["id"], result["summary"])
```

`StackRequest` validates the finite interval, bounding box, sensor selection, metric output resolution, scene budget, native QA buffer, clear-support threshold and temporal bracket. The returned manifest identifies input assets, calibration, grid, processing assumptions, support and artifact hashes.

## HTTP jobs

Submit long-running work through the durable job API:

```bash
curl -sS http://127.0.0.1:8000/api/jobs \
  -H 'Content-Type: application/json' \
  --data '{"kind":"optical","recipe":{"demo":true}}'
curl -sS http://127.0.0.1:8000/api/jobs/JOB_ID
curl -sS 'http://127.0.0.1:8000/api/jobs/JOB_ID/events?after=0'
```

The response includes a job ID. Reuse a saved request key for idempotent submission. A successful processing state does not imply adequate coverage. See [job execution](JOBS.md) for the complete request, recovery and result contracts.

## Spectral analysis

```python
from pathlib import Path
from rslib.spectral_workflow import analyze_spectra

report = analyze_spectra(
    Path("data/runs/RUN_ID"),
    Path("data/analyses/my-analysis"),
    source_index=0,
    components=3,
    endmembers=3,
    projection="affine",
    seed=0,
)
```

Fit inputs are complete QA-valid spectra from one observed acquisition. The report records source cells, coefficients, input hashes, implementation versions, abundance constraints and reconstruction residuals. Queue requests pin the parent run checksums. [Algorithm contracts](CLASSICAL_ALGORITHMS.md) explain why reconstruction fit is not material-fraction accuracy.

## Frozen reference inputs

```bash
uv run rslib reference-acquire seasonal-crops
uv run rslib reference-register \
  docs/reference-projects/snapshots/seasonal-crops/snapshot.json
uv run rslib reference-check seasonal-crops
uv run rslib reference-audit --output data/reference-audit.json
```

These commands distinguish pinned input verification, source metadata/licensing evidence and scientific validation. See the [reference guide](reference-projects/README.md) before reacquiring a published case.
