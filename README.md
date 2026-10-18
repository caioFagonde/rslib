# RSLIB

[Documentation](https://caioFagonde.github.io/rslib/) · [GitHub](https://github.com/caioFagonde/rslib) · [Roadmap](docs/ROADMAP.md)

An Earth observation library and local workbench combining GDAL-backed raster processing, STAC discovery, AWS Open Data, deck.gl, Turf.js, optional PostGIS, and a native Rust infiltration and slope-stability engine.

Version 0.1 prepares bounded Sentinel-2/Landsat stacks, applies native QA and partial spectral adjustment, and exports regular index series with observation/estimate provenance. The optical browser supports polygon monitoring areas, a deck.gl map, fractional-cell area statistics, source inspection, CSV/COG exports and saved projects with run history. Acquisition can check measured temporal support and add candidates within a declared budget. Saved projects also run from the CLI and TUI. Python, CLI and TUI share the preparation core.

Use it for exploratory preparation and inspection of small optical datasets. Jobs now persist their recipes, progress and selected scenes, with cancellation, cache-aware retry and process-restart recovery in the browser and TUI. Whole-date reconstruction holdouts compare linear filling with a paired nearest-observation baseline. General cross-sensor/reconstruction accuracy and large-area performance remain unvalidated. The [product audit](docs/PRODUCT_AUDIT.md) identifies these gaps and the evidence required to close them. [Operations guide](docs/OPERATIONS.md) · [monitoring projects guide](docs/PROJECTS.md) · [job execution guide](docs/JOBS.md) · [delivery roadmap](docs/ROADMAP.md) · [reconstruction check](docs/showcase/27-live-reconstruction-check.png).

## Run locally

Python 3.11–3.13, Rust stable and Node 18+ (22 recommended):

```bash
uv sync --extra dev --extra ml --extra postgis
cargo build --release --locked -p rslib-hydro
npm --prefix web ci
npm --prefix web run build
uv run rslib serve
```

Open **http://127.0.0.1:8000**. The initial scene is an offline synthetic fixture near Itatiaia, Brazil. The basemap/terrain tiles require internet access. Choose Earth Search or Planetary Computer to discover actual satellite scenes. The browser has live collection discovery, AOI/cloud/date controls, NDVI/NDMI/NBR/EVI/RGB, cloud masks, 3D terrain draping, footprint filtering, COG/JSON export, printable reports, and a Rust storm laboratory. API documentation: `/docs`.

**See the progress:** [visual gallery](docs/showcase/index.html), [live browser capture](docs/showcase/05-live-sentinel-analysis.png), [terminal](docs/showcase/07-terminal-workbench.svg), [native physics figure](docs/showcase/08-rust-physics.png), and [concept art](docs/showcase/02-concept-earth-workbench.png). Built browser versions expose the gallery at `/showcase/` through **Development captures**. Concept art and synthetic/model scenarios are clearly separated from actual satellite observations.

```bash
uv run rslib tui                # keyboard-driven terminal workbench, true-color half blocks
uv run rslib demo               # offline acquisition → mask → index → COG/PNG/HTML/JSON
uv run rslib hydro-demo         # native Rust hypothetical storm, input + results saved
uv run rslib doctor
uv run rslib stack              # different synthetic sensor grids → common stack + time series
uv run rslib stack --live       # actual Sentinel-2 + Landsat; small AOI defaults
```

TUI: `d` loads demo scenes, `s` searches, `a` analyzes, `w` prepares an optical stack, `[` / `]` changes stack dates, `g` toggles observed/interpolated/missing support, `j` opens the durable job journal, `h` runs the Rust scenario, `q` quits. Stack demo mode uses a changing multi-sensor fixture; live mode discovers both optical catalogs. Use Tab to focus controls and Enter to select a scene. Network and raster jobs run in background workers. `hubtui` inspired responsiveness and terminal imagery; `field_atlas` inspired reproducible artifacts, explicit provenance, and scientific readiness distinctions. No source code was copied from either project.

For frontend development, run `uv run rslib serve` and `npm --prefix web run dev` in separate terminals; Vite proxies `/api`. An installed wheel includes the browser only if built **after** `npm --prefix web run build`. The Rust binary is a separate native artifact; set `RSLIB_HYDRO_BIN` or put `rslib-hydro` on PATH when using a wheel outside this checkout.

## Search and analyze real data

```bash
uv run rslib search --bbox=-44.75,-22.5,-44.55,-22.3 \
  --dates 2026-06-01/2026-08-01 --cloud 20 --limit 10 \
  --output data/scenes.json
uv run rslib analyze data/scenes.json --index ndvi

# Elevation discovery: DEM acquisition dates and cloud cover are not optical filters.
uv run rslib search --bbox=-44.75,-22.5,-44.55,-22.3 \
  --collection cop-dem-glo-30 --dates '' --cloud -1 \
  --output data/elevation-scenes.json
```

Search uses core STAC Item Search, bounded pagination, GET/POST next links, retries, deduplication, a bounded persistent TTL response cache, and client-side scene-cloud filtering. It reports page/item caps and unknown-cloud exclusions. Ranking is within fetched results, not a global optimum or AOI clear-coverage estimate. Discover current collection IDs with `/api/collections/{provider}`.

Rasterio/GDAL reads the requested AOI into a bounded common grid, using remote COG range access and overviews instead of downloading full scenes. Optical bands use explicit STAC calibration or documented provider-specific rules. Earth Search defaults to `sentinel-2-c1-l2a`: the legacy `sentinel-2-l2a` collection has inconsistent offset metadata and is rejected for analysis. Nodata is preserved before calibration. Sentinel SCL keeps classes 4/5/6; Landsat C2 uses QA_PIXEL bits 0–5 plus QA_RADSAT, where zero is a valid saturation flag. QA uses nearest-neighbor resampling. Planetary Computer assets are signed only at read time; tokens are excluded from reports.

**The scene explorer and single-scene TUI analysis use preview grids.** Statistics describe sampled WGS84 pixels, not full-resolution area-weighted zonal statistics. Downsampling can miss small clouds. The raster library accepts explicit projected grids for quantitative work. Their cloud buffers use output pixels. The separate optical stack workflow uses projected metric grids and native QA buffering, as described in the operations guide. A valid fraction of zero is a real result, not silently replaced by unmasked data.

## Scientific library

Classical spectral processing now includes reusable **PCA, VCA and fully constrained least-squares unmixing**, plus explicitly calibrated **OLI TOA tasseled cap** and a **Sentinel-2 BCY threshold adaptation**. [Algorithm contracts and examples](docs/CLASSICAL_ALGORITHMS.md) · [interactive satellite spectral figure](docs/showcase/spectral.html) · [quantitative method review](docs/REMOTE_SENSING_RESEARCH.md). The searchable review covers 98 methods, including 28 classical-method records; candidates remain separate from executable operations.

```bash
uv run rslib spectral-analysis data/runs/RUN_ID data/spectral/my-analysis --source-index 2
uv run rslib compare-sensors data/runs/RUN_ID --max-hours 48 --output data/agreement.json
```

The first command exports observed-scene PCA, numbered spectral fractions and reflectance residuals as COGs, with source hashes, fitted coefficients, a printable report and artifact bundle. Open **Analyze observed spectra** on a completed browser run, or press `x` in the TUI, to execute the same workflow as a durable spectral job. [Working browser](docs/showcase/37-queued-spectral-workbench.png) · [printable report](docs/showcase/38-spectral-project-report.png) · [same-job terminal and numerical parity](docs/showcase/40-spectral-interface-parity.json). The second measures common-clear-cell Landsat/Sentinel agreement; browser and TUI expose the same checks. The first real pair has weak NIR agreement despite strongly correlated NDVI—see [the results](docs/VALIDATION.md) before treating these sensors as interchangeable. The BCY and tasseled-cap TOA primitives reject the existing SR workflow's radiometry and are not default QA or automatic biophysical retrievals.

Super-resolution now has an opt-in [SEN2SRLite](https://github.com/ESAOpenSR/SEN2SR) adapter and native-grid CLI. A real 128² RGB+NIR Sentinel-2 patch ran at **0.077 s median warm inference** on the local RTX 3050 6 GB, producing 512² output with **102.5 MiB peak Torch allocation**. That memory figure excludes CUDA context/driver and other processes; timing excludes acquisition/loading/export. See the [actual comparison](docs/showcase/09-superresolution.png), [machine-readable measurement](docs/showcase/09-superresolution-evidence.json), and [research/model survey](docs/RECONSTRUCTION_RESEARCH.md). Finer pixel spacing does not establish finer measured spatial resolution.

```bash
uv sync --extra sr
uv run rslib sr-fetch
# Input: cloud-masked physical reflectance, bands R,G,B,NIR, projected 10 m grid.
uv run rslib superresolve input-rgbn.tif --device cuda --precision float16
```

The Python API also includes whole-spectrum quality/medoid compositing, irregular time-series gap interpolation, and a clear-observation-preserving contract for supplied inpainting predictions. See the [computed temporal showcase](docs/showcase/10-temporal-baselines.png). Evaluate a completed optical run with `rslib validate-series data/runs/RUN_ID --output data/validation.json`, or **Withhold acquisition days** in the browser. This excludes all sensors on each withheld UTC day, reports scoring coverage and paired MAE/RMSE/bias, and checks the stack against its manifest checksum. The first six-acquisition satellite evaluation is recorded in [validation results](docs/VALIDATION.md).

These temporal algorithms are baselines; pretrained cloud-removal and temporal diffusion adapters are research work, documented with current upstream availability in the survey. SR is currently a library/CLI workflow, not a browser model-execution control.

```python
from rslib.soil import soc_stock, saxton_rawls, soilgrids_vrt
from rslib.raster import Grid, read_band
from rslib.hydro import demo_problem, simulate

stock = soc_stock(soc_g_kg=20, bulk_density_g_cm3=1.3,
                  thickness_cm=30, coarse_fraction=0.1)  # 70.2 Mg C/ha
hydraulic = saxton_rawls(sand_fraction=0.4, clay_fraction=0.2,
                         organic_matter_percent=2.5)
result = simulate(demo_problem())  # our Rust implementation, not an external TRIGRS model
```

Other modules:

| Module | Implemented capability |
| --- | --- |
| `rslib.indices` | NDVI, NDMI, NBR, EVI, cloud masks, valid statistics, quality-based best-pixel composites with source indices |
| `rslib.raster` | Bounded aligned reads, calibration, nodata, COG export, STAC asset resolution |
| `rslib.soil` | SoilGrids unit conversion and VRT URLs, six depth intervals, coarse-fragment-corrected SOC stock, explicit stock-change CO₂ mass equivalence, seeded independent uncertainty propagation, Saxton–Rawls fine-earth pedotransfer |
| `rslib.terrain` | Metric DEM slope, compass aspect, hillshade, static infinite-slope screening |
| `rslib.jobs` | Local durable queue, immutable recipe/inventory, progress journal, cancellation and cache-aware retry |
| `rslib.validation` | Whole-date temporal holdouts, paired nearest baseline, explicit scoring coverage and input checksums |
| `rslib.ml` | Spatial grouping, disjoint train/calibration/test groups, random-forest regression, split conformal intervals, held-out metrics and feature schema |
| `rslib.deep` | Model-supplied Torch segmentation with tiled halo inference, nodata restoration, output/memory budgets; no pretrained weights bundled |
| `rslib.superresolution` | Opt-in verified SEN2SRLite RGBN ×4 inference, scale-aware halo tiles, native-grid COG/provenance CLI; weights downloaded explicitly |
| `rslib.compositing` | Whole-spectrum quality/L1-medoid composites, source indices and eligible observation counts |
| `rslib.timeseries` | Irregular datetime gap interpolation with maximum bracket length, no extrapolation, support/source metadata |
| `rslib.reconstruction` | Merge caller-supplied predictions while retaining clear observations, support labels and optional model standard deviations |
| `rslib.workflows` | One async recipe shared by browser/API/CLI/TUI: discovery → stack → regular series → exports |
| `rslib.stack` | Prepared scene cache with byte budget, aligned sensor/time/band arrays, daily mosaics, regular index series, source brackets and xarray interoperability |
| `rslib.harmonization` / `rslib.preparation` | Explicit S2 A/B/C and Landsat 8/9 profiles, narrow NIR equivalence, HLS V2 bandpass coefficients, preharmonized HLS inputs, native QA before area-weighted resampling |
| `rslib.acquisition` | Date-stratified scene planning with per-day footprint set cover, reducing redundant overlap within a bounded acquisition budget |
| `rslib.hydro` | SI-unit bridge to native Rust wet-column diffusion, storm superposition, FS profiles, D8 runoff routing and water-balance diagnostics |
| `rslib.store` | Optional PostGIS geometry + JSONB scene ingestion and AOI queries |
| `web/src/layers.ts` | Reusable typed layer entry points: GeoJSON, COG preview bitmap, raster tiles, terrain, MVT, 3D Tiles, point clouds, heatmap, hexagons, contours; GPU data filtering and optional experimental terrain draping |

SOC stocks are not emissions measurements. Stock-change CO₂ equivalents are not verified carbon credits. SoilGrids marginal quantiles do not define joint spatial uncertainty. The independent Monte Carlo helper states its assumptions. Pedotransfer outputs do not identify cohesion, friction, soil depth, diffusivity or an initial water table. Conformal intervals require exchangeability; spatial blocking does not establish coverage under domain shift. See [scientific methods](docs/SCIENCE.md).

## Rust implementation of reference TRIGRS physics

`crates/rslib-hydro` independently implements the public reference equations. It does **not** require an installed TRIGRS model, Fortran executable, or native TRIGRS input deck.

```bash
cargo test --locked --workspace
cargo run --release --locked -p rslib-hydro < examples/storm.json > data/storm-result.json
uv run rslib hydro examples/storm.json
```

Implemented: wet/tension-saturated analytical infiltration, infinite and finite no-flow basal boundaries, variable rainfall pulses, initial steady pressure head, the reference pressure-head cap, depth/time FS profiles, heterogeneous cells, Rayon parallelism, optional instantaneous D8 runon routing, and explicit excess-water accounting. A late-time eigenfunction expansion avoids slow finite-boundary image-series convergence.

**Not implemented yet:** unsaturated Gardner/Richards coupling and moving water tables, upward initial-flow cases, flat/depression hydrology, travel-time/storage routing, continuous critical-depth search, and certified numerical parity with legacy TRIGRS. Unsupported conditions fail explicitly. See [equation map and validation plan](docs/HYDRO.md).

## Optional Docker / PostGIS

```bash
docker compose up --build -d
# API/browser: http://127.0.0.1:8000
uv run rslib ingest data/scenes.json \
  --dsn postgresql://rslib:rslib_local@localhost:5432/rslib
docker compose down
```

Compose builds the browser and Rust kernel and starts the API with PostGIS. A named data volume persists artifacts, and a separate PostgreSQL volume persists the spatial catalog. Database migration/init runs only on a fresh volume. PostGIS is optional; discovery/analysis works with local SQLite caching. This is a loopback-bound local development stack. Deployment hardening and shared multi-user jobs are future work.

## Validation and direction

```bash
uv run pytest
cargo test --locked --workspace
cargo clippy --locked --workspace --all-targets -- -D warnings
npm --prefix web run build
uv run python scripts/benchmark.py --size 512
```

See [architecture](docs/ARCHITECTURE.md), [source registry](docs/SOURCES.md), [roadmap](docs/ROADMAP.md), and [validation results](docs/VALIDATION.md). This release prioritizes a runnable, auditable vertical slice. SAR processing, foundation-model adapters, distributed cubes, distributed job execution, field-specific acquisition targets, deeper report templates, and full unsaturated TRIGRS-equivalent physics are tracked explicitly rather than advertised as complete.

MIT license for this code; each source dataset, basemap and future model weight retains its own license and attribution.

## Reference cases and documentation

Six small actual-satellite reference cases retain prepared-input hashes and development/holdout roles. The [case viewer](docs/showcase/reference-cases.html) shows per-acquisition reflectance and QA support, saved/daily query missingness and unscored temporal comparisons. The five new cases include pinned public STAC and collection/license metadata. Independent labels remain absent; see the [reference guide](docs/reference-projects/README.md).

```bash
uv run rslib reference-check seasonal-crops
uv run rslib reference-audit --output data/reference-audit.json
uv run --only-group docs mkdocs serve
uv run --only-group docs mkdocs build --strict
```

Reference checks require the retained local input artifacts; metadata alone do not include the rasters. The documentation site is static and does not run the analysis service. [Publishing setup](docs/DOCUMENTATION.md).
