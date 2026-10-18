# Getting started

Use Python 3.11–3.13, Rust stable, Node.js 22 and [uv](https://docs.astral.sh/uv/). Clone the repository and install the locked dependencies:

```bash
git clone https://github.com/caioFagonde/rslib.git
cd rslib
uv sync --locked --extra dev --extra ml --extra postgis
cargo build --release --locked -p rslib-hydro
npm --prefix web ci
npm --prefix web run build
uv run rslib doctor
uv run rslib serve
```

Open [the local browser](http://127.0.0.1:8000/workflows.html). The documentation hosted on GitHub Pages cannot execute analysis jobs.

## Prepare a first dataset

1. Open **Optical preparation** in the local browser. Choose the explicitly labeled synthetic fixture for an offline first run, or choose satellite data.
2. Set a small bounding box, finite date interval, scene budget, output resolution and maximum interpolation bracket.
3. Submit the job. Inspect the scene journal and observed/estimated/missing support after it finishes.
4. Select a map cell or monitoring area to inspect values, source acquisitions and CSV exports.
5. Save the project or export its recipe. Reopen the run to compare it with later results.

Start with small AOIs. The current execution path materializes bounded arrays and is not a large-area distributed loader. Actual acquisition requires internet access; basemap and terrain services also require internet.

## Terminal and CLI

```bash
uv run rslib tui
uv run rslib stack             # Explicitly synthetic multisensor fixture
uv run rslib stack --live      # Actual satellite data for the documented small default AOI
uv run rslib --help
uv run rslib jobs --help
```

The TUI shares the preparation and job core. Use `w` for the optical workflow, `j` for the job journal and `x` for spectral analysis. Consult the [job guide](JOBS.md) for cancellation, retries and recovery.

## Storage and optional components

Prepared scene caches, project/queue SQLite databases and run outputs live under `data/` by default. They are not included in Git. Preserve a run's `manifest.json` together with its exported arrays when reproducing an analysis.

The Rust binary is separate from a Python wheel. Set `RSLIB_HYDRO_BIN` or put `rslib-hydro` on `PATH` when using it outside this checkout. PostGIS/Compose and optional machine-learning packages are described in the repository configuration and [architecture](ARCHITECTURE.md).

See [operations](OPERATIONS.md) for calibration and QA policies, [monitoring areas](PROJECTS.md) for polygon workflows, and [classical algorithms](CLASSICAL_ALGORITHMS.md) for spectral analysis.
