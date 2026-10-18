# Optical preparation and inspection

The optical workflow prepares a bounded Sentinel-2/Landsat stack and index series through browser, terminal, CLI or Python. The [monitoring project guide](PROJECTS.md) describes polygon areas, saved projects, map inspection, area statistics and adaptive acquisition. The [product audit](PRODUCT_AUDIT.md) records its current uses, scientific limits and missing project capabilities.

## Run a preparation

```bash
uv run rslib serve --port 8768
# http://127.0.0.1:8768/workflows.html — also linked from the Explorer

uv run rslib stack                     # explicitly synthetic multi-grid fixture
uv run rslib stack --live \
  --bbox=-44.66,-22.41,-44.64,-22.39 \
  --dates 2026-06-01/2026-07-16 --limit 4
# Reuse prepared scenes; change only the temporal product.
uv run rslib stack --live --step 10 --max-gap 14
uv run rslib tui                       # w builds; [ ] dates; g gap support
```

Live discovery uses Earth Search Sentinel-2 C1 and Planetary Computer Landsat C2. The common optical profiles support Sentinel-2 A/B/C and Landsat 8/9 OLI. Broad Sentinel B08 is never silently used as Landsat-equivalent NIR: the shared NIR channel uses **B8A / OLI B05**.

The synthetic fixture deliberately contains different 10/20/30 m source grids, a 15 m Landsat origin shift, DN conventions, cloud patterns, known spectral offsets and a changing land-cover patch. Its eight observations represent five platforms. It is not satellite imagery or a real-world accuracy benchmark. Sensor, date and scene-limit controls also apply to the fixture.

```python
from pathlib import Path
from rslib.workflows import StackRequest, prepare_optical

# In an async application/notebook. Use asyncio.run(...) in a synchronous script.
report = await prepare_optical(
    StackRequest(demo=False, datetime="2026-06-01/2026-07-16"),
    Path("data"),
)
print(report["summary"], report["coverage_notes"])
```

`POST /api/stack` accepts the same typed recipe. The HTTP API resolves its own trusted catalog assets rather than accepting arbitrary file URLs.

## Decisions made consistently

1. **Choose useful acquisitions.** Fetch a bounded candidate set per sensor, group by UTC day, and use sampled footprint set cover to avoid unnecessary overlapping tiles. Stratify the requested time interval before spending the raster budget. Selection remains a geometric/scene-cloud heuristic, with native QA checking actual usability. Search and planning limits are retained in the result.
2. **Use one grid.** Select a local UTM CRS by default, snap pixel edges to the resolution lattice, and apply a densified AOI center mask. A common 30 m grid avoids advertising upsampled Landsat detail as a finer observation. Wide/polar areas require an explicit suitable metric CRS in the library.
3. **Mask before averaging.** Read bounded native AOI windows with context. Decode Sentinel SCL, Landsat QA/saturation or HLS Fmask, buffer invalid pixels in metres, and map QA to each native band grid. Apply calibration after identifying nodata. Area-average only valid reflectance with GDAL; track clear support separately, retaining invalid/scene-exterior source area as zero support. Defaults require at least 90% support and a clear center in every requested spectral band.
4. **Make spectral adjustment explicit.** Apply the platform-specific NASA HLS V2 MSI-to-OLI bandpass coefficients for ordinary S2 SR; OLI is the spectral reference. This is **partial harmonization**. It does not reproduce HLS BRDF normalization, common atmospheric processing or image-based co-registration. HLS L30/S30 V2 inputs can be supplied directly through `build_stack(..., harmonization="hls")`; their adjustments are not applied twice. [NASA HLS methods](https://hls.gsfc.nasa.gov/algorithms/)
5. **Mosaic complete spectra.** Each output pixel on a UTC day keeps one complete eligible spectrum, its original acquisition identity and the eligible observation count. Overlapping scenes on one day do not become multiple independent time steps. The displayed latest-clear composite can contain different dates; its source-index/count COG records them.
6. **Regularize with support.** Compute a scalar index from each daily spectrum. Interpolate at actual requested dates using clear bracketing days; the entire bracket must fit the chosen maximum gap. Exact observed days retain their values, while estimates and unsupported pixels have separate labels. No extrapolation or silent nearest-date relabeling. Daily spacing displays acquisition days; a five-day point timeline may have only estimated values if acquisition days fall between its queries.
7. **Reuse completed work.** The prepared AOI cache keys source metadata, grid, bands, calibration/QA recipe and processing version. Changing only the series interval, index or gap limit reuses the six-band preparation. Corrupted entries are rebuilt, writes are atomic, and a 2 GiB LRU byte budget bounds prepared-cache storage. Explicit refresh handles upstream asset changes. Job artifacts have separate retention and are not pruned by this cache.
8. **Recover from transient services.** Catalog discovery retries transient failures. Planetary Computer signing retries temporary HTTP/transport failures; native raster retries reopen GDAL with fresh signing. Completed scene preparations remain cached after a later failure. Permanent missing/denied sources still return an actionable failure rather than substituting synthetic data.

Clear fractions and timeline support fractions use AOI pixel centers as their denominator, excluding padding added by grid snapping. A selected output cell summarizes its accepted source samples; clear-support thresholds and QA resolution remain relevant to interpretation.

## Work directly with the stack

```python
from rslib.stack import Observation, OpticalStack, build_stack

# Trusted STAC Items or local COG assets, with explicit source providers.
stack = build_stack(
    [Observation(sentinel_item, "earth-search"),
     Observation(landsat_item, "planetary-computer")],
    bbox,
    resolution=30,
)
daily = stack.daily()
series = stack.regular_series(index="ndvi", step_days=5, max_gap_days=20)
stack.save(Path("data/optical.npz"))
restored = OpticalStack.load(Path("data/optical.npz"))

# Optional cube extra: uv sync --extra cube
dataset = stack.to_xarray()  # time, band, y, x; sensor/provider/item coordinates + CRS
```

The xarray view wraps a bounded materialized stack. It is not a claim that the acquisition backend already implements a distributed lazy cube. Keep SAR, thermal, DEM and soil channels in their own physical units and processing pipelines; the optical bandpass transform is not applicable to them.

## Outputs and failure behavior

Each run writes a portable, pickle-free reflectance stack, a regular-series archive containing support and both source brackets, a dated multiband index COG, a six-band latest-clear COG, a categorical provenance COG, previews and a JSON recipe/source/checksum manifest. Band descriptions are written before COG conversion so subsequent metadata edits do not invalidate the COG layout.

The browser starts without running synthetic data. Select satellite catalogs or explicitly run the synthetic example. Missing pixel-date coverage appears above the selected-date raster and latest-clear composite. Click either raster, or enter a zero-based row/column, to inspect a cell's dated values and the source acquisitions bracketing an estimate. The chart identifies observed and estimated cell values separately. Cell CSV exports include source dates/IDs, support, bracket length, coordinates, index, units and the synthetic-input flag. The terminal uses the same preparation and artifacts with date/support navigation.

Save/load recipe buttons use the `StackRequest` JSON accepted by `POST /api/stack`. A successful run adds `?run=<id>` to the browser URL; reopening it reads persisted artifacts without repeating acquisition. This requires the original server's run directory and is not a remote project-sharing service. Older runs can reopen, but need a new preparation for cell inspection if they lack the tiled support companion.

`GET /api/runs/{id}/pixel?row=R&col=C` returns a cell's index series, support codes, source records and coordinates. It reads small windows from `analysis.tif` and `series-support.tif` rather than decompressing a full stack. The latter has four consecutive band groups in timeline order: support, left source index, right source index and bracket days. Source indices refer to the manifest's original observations; missing indices are −1. Its categorical overviews use nearest-neighbor sampling. Unsupported index values are JSON null.

With `coverage_target` set, the workflow prepares an initial subset, measures AOI pixel-date support and adds planned candidates until the goal or budget is reached. Coverage includes permitted estimates; the target does not establish interpolation accuracy. Without a target it prepares the fixed planned scene set. When the scene budget leaves too few clear dates, the workflow reports coverage notes and leaves long gaps missing. Raising the raster scene limit, narrowing the interval, choosing daily queries or obtaining additional observations can help; increasing a gap limit does not establish the accuracy of a longer interpolation. Abrupt change may be smeared by linear filling. There is no invented calibrated uncertainty.

Budgets are explicit: up to 32 observations, 1,048,576 common-grid pixels, 32 million spectral samples, 16 million temporal samples and 1,024 requested dates. Reduce scenes, tile an area or coarsen its grid when a budget is reached. Source-window reads and intermediate interpolation arrays are bounded. The service uses background threads with bounded job concurrency. The [local durable queue](JOBS.md) adds checkpoint progress, cooperative cancellation, pinned inventories and restart recovery. Distributed scheduling remains future work.

Actual captures and evidence: [browser](showcase/11-practical-optical-workflow.png), [gap support](showcase/12-gap-support.png), [mobile](showcase/13-workflow-mobile.png), [terminal](showcase/15-terminal-optical-workflow.svg). Live evidence is recorded separately from the synthetic fixture.


## Sensor agreement and observed-scene spectral transforms

In the browser, **Compare sensor pairs** evaluates disjoint near-coincident Landsat/Sentinel acquisitions with a user-selected hour limit and minimum common-clear-cell count. The signed bias is comparison MSI minus reference OLI. All eligible cells enter the statistics; at most 400 deterministic row-major samples per pair are plotted. Click a scatter point to open that exact grid cell on the comparison acquisition date. Changing the plotted band does not recompute acquisition or change the reported sample population. Empty overlap/pair results remain explicit.

`GET /api/runs/{id}/agreement?max_hours=48&min_cells=100`, `rslib compare-sensors`, and the TUI **Quantitative checks** tab use the same verified source stack. Before/after residuals reverse only local recorded affine coefficients; upstream HLS or unknown transforms do not get an invented unadjusted spectrum. Timestamp separation, overlap and source IDs remain in the JSON. This is an observational diagnostic, not an automatic calibration correction or causal attribution of differences.

`rslib spectral-analysis RUN_DIRECTORY NEW_OUTPUT_DIRECTORY --source-index 2` fits PCA/VCA/FCLS on one QA-valid observed acquisition and exports COGs and a reproducible report. The existing run is immutable. See [classical algorithm contracts](CLASSICAL_ALGORITHMS.md) for axis conventions, fit reuse, limits and TOA-only BCY/tasseled-cap inputs. The earlier [interactive spectral figure](showcase/spectral.html) is retained. Live browser execution now starts from **Analyze observed spectra** on a completed run, or `/spectral.html?run=RUN_ID`. The TUI `x` binding opens the same saved-source workflow.

The [research browser](showcase/research.html) is also served at `/showcase/research.html`. Its filters describe reviewed candidates and available source artifacts, not operations installed in the processing menu. [The quantitative review](REMOTE_SENSING_RESEARCH.md) records the book scope, primary sources and integration gates.
