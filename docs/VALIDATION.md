# Validation record

Local checks updated 2026-10-18. This is a reproducible engineering record, not certification of scientific accuracy or a comparison with all competing libraries.

## Automated checks

- Python core: **82 passed, 4 skipped** in the standard development environment. Three skips require optional Torch; one requires optional xarray. The xarray stack integration was also exercised with that dependency installed. The earlier SR/reconstruction test files additionally passed **8 tests** in an isolated environment using the existing local Torch/CUDA installation; actual pretrained GPU inference and the COG CLI were exercised separately.
- Rust: **9 physics tests** pass, plus `cargo fmt --check` and Clippy with warnings denied. Tests cover special functions, finite/infinite responses, pulse superposition, pressure caps, routing mass balance and boundary convergence. A separate Python finite-volume method-of-lines reference compares transient pressure profiles with the analytical kernel.
- Python Ruff checks pass. Tests cover STAC pagination/cache/budgets, dates, calibration and QA, source-preserving composites, irregular gap limits, reconstruction invariants, COG georeferencing, scientific units, grouped ML evaluation, API/CLI/TUI and display-only DEM filling.
- TypeScript type checking and production browser build pass. The terrain worker is bundled locally, avoiding a runtime dependency on a worker CDN. NPM audit reports no known vulnerabilities in the resolved tree at the time checked.
- The wheel and source distribution are built after the browser; browser/worker/gallery assets are checked in the wheel. Generated assets are build artifacts, excluded from source control but explicitly included in packaging.

```bash
uv sync --locked --extra dev --extra ml --extra postgis
uv run pytest
uv run ruff check src tests scripts
cargo test --locked --workspace
cargo fmt --all -- --check
cargo clippy --locked --workspace --all-targets -- -D warnings
npm --prefix web ci
npm --prefix web run build
npm --prefix web audit
uv build
docker compose config --quiet
```

Optional SR tests require Torch; `uv run --extra sr pytest tests/test_superresolution.py` runs those in a suitable configured environment. GPU installation depends on the platform and available CUDA runtime.

## Actual public data and interfaces

The live browser capture selected `S2B_T23KNR_20260729T131748_L2A` from Earth Search Collection 1. It produced **256,902 / 262,144 valid preview samples (98.00%)**, mean NDVI **0.79684**, and a georeferenced COG/report/manifest. The latest capture measured about **10.85 seconds** for that run; network conditions and caches affect this. These are sampled WGS84-grid statistics, not native-resolution area-weighted estimates. [Capture evidence](showcase/capture-evidence.json) records the actual scene, timing and zero page/console errors for the fresh desktop/terrain/mobile run.

The direct terrain endpoint acquired Copernicus GLO-30 elevation for the AOI, encoded a bounded display mesh, and draped the analysis PNG on it. Small display voids can be filled explicitly, while the downloadable DEM preserves nodata. The separate scientific terrain module requires metric grids; display terrain is not used as a hidden substitute.

The new [operational optical recipe](OPERATIONS.md) was exercised through CLI, API, browser and TUI. Its synthetic multi-grid fixture combines eight observations from five emulated platforms with different DN conventions and pixel origins. Tests independently check bandpass arithmetic, narrow NIR selection, pre-aggregation cloud exclusion, partial scene-edge support, same-day source mosaics, real-date interpolation, COG layout/band dates, cache recovery/budget/reuse, xarray coordinates and terminal navigation. Signing and fresh-token raster retries have controlled transient-failure tests.

The [live workflow capture](showcase/14-live-optical-workflow.png) processes four actual acquisitions from Landsat 8/9 and Sentinel-2 B/C into a 69 × 75 projected 30 m grid and 46 daily index queries. All four preparations were reused; processing/export took approximately **0.3 s** in the captured warm run, excluding catalog discovery. Its small scene budget leaves **76.35%** of the requested AOI/time support missing; this is explicitly reported, with long gaps and edges left unsupported. This measurement is not full-scene throughput or reconstructed-image accuracy. [Live evidence](showcase/14-live-workflow-evidence.json), [synthetic workflow evidence](showcase/11-workflow-evidence.json).

The revised optical workspace is recorded in [capture 16](showcase/16-cell-inspection.png), [satellite capture 17](showcase/17-live-cell-inspection.png) and [mobile capture 18](showcase/18-inspection-mobile.png). Python checks compare inspected observed, estimated and missing cells with exported arrays, including both original source identities, bracket lengths, null values, coordinates and bounds/AOI rejection. The full Python suite and Ruff pass; optional Torch/xarray skips remain as described above. No Rust code changed in this interface/inspection revision.

The [browser interaction record](showcase/16-inspection-evidence.json) verifies explicit execution, prepared-cache reuse, coordinate and mouse cell selection, exported CSV values/source IDs, recipe save/load, reopening without a new acquisition, support legends and a 390 px layout. It records zero page errors. [Satellite inspection evidence](showcase/17-live-inspection-evidence.json) identifies a June 11 cell estimate bracketed by actual June 10 Landsat 8 and June 18 Landsat 9 observations; it also records zero page errors. Missing coverage is now prominent, and the interface reports output creation separately from coverage. These checks establish the implemented interactions, not professional usability or scientific accuracy. See the [product audit](PRODUCT_AUDIT.md) for the outstanding acceptance work.

The actual Textual interface was exercised with synthetic discovery/analysis and exported as SVG. The initial three demo dates reference the same synthetic image; no measured time trend is implied. The separate temporal showcase generates a deliberately changing synthetic sequence and executes the new baseline algorithms over it.

## Consumer GPU super-resolution

Actual native 10 m Sentinel-2 RGBN → nominal 2.5 m grid using pinned SEN2SRLite on RTX 3050 6 GB: **0.0769 s median of three warmed runs**, **102.5 MiB peak Torch allocated / 136 MiB reserved**. Input is 128², output 512², batch 1 with halo tiles. Memory excludes driver/context/other processes; timing excludes acquisition, loading, warm-up and exports. The separate CLI first inference took about 0.91 s. This is not an HR accuracy benchmark. [Evidence and limitations](showcase/09-superresolution-evidence.json), [method/model survey](RECONSTRUCTION_RESEARCH.md).

## Container and database

A built image was started as the unprivileged application user. Health, browser root, synthetic raster analysis and the compiled Rust laboratory endpoint returned successful responses. Runtime GDAL import required `libexpat1`; the Dockerfile includes it and `libgomp1`. The default image excludes optional Torch/SR weights, keeping its geospatial service independent of GPU dependencies.

A disposable local PostGIS instance accepted a real Sentinel-2 Item, an upsert and a spatial AOI query. Compose configuration is validated separately; verification uses allocated loopback ports because this machine already has unrelated services on 8000/5432. No existing services or volumes are removed. Provider-aware catalog identities remain future work; colliding collection/item IDs from different providers should use separate catalogs.

## Scientific limits that remain

There is no certified numerical parity with legacy TRIGRS and no implemented unsaturated Gardner/Richards or moving-water-table model. Wet-column analytical behavior has independent checks, but application to a field site still requires appropriate measured material/initial/forcing inputs. The stock and pedotransfer helpers have unit/arithmetic checks, not universal regional validation. Cloud reconstruction adapters beyond the supplied-prediction contract are not installed. Model-derived SR detail, conformal transfer coverage, carbon flux estimates and hazard forecasts require separate domain-specific validation.

## Monitoring project revision

The saved monitoring workflow adds polygon drawing/import, a geographic map, fractional-cell statistics, a fixed observed cohort, support-driven acquisition, and local project/run persistence shared with CLI/TUI. [Browser interaction evidence](showcase/19-project-evidence.json) covers imported holes, actual map drawing/removal, project revisions, map area/cell selection, field CSV values and area conservation, reopening without reacquisition, support layers, empty fixed-cohort handling and a 390 px layout. Page errors: zero. [Current browser](showcase/19-monitoring-project.png), [support](showcase/20-area-support.png), [mobile](showcase/21-monitoring-mobile.png), [terminal](showcase/23-project-terminal.svg).

The [satellite monitoring run](showcase/22-live-project-evidence.json) started with four planned acquisitions and measured **23.65%** supported AOI pixel dates. It added two acquisitions and reached **73.34%** support, comprising **12.60% observed** and **60.74% linearly estimated** pixel dates. **26.66% remained missing**. Its 80% goal was not met, and the planned candidate pool was exhausted. The gain is largely permitted temporal interpolation, not newly observed imagery or validated reconstruction. Total measured workflow time was **22.228 s**: 1.590 s catalog discovery and 20.638 s preparation/export. Four preparations were reused; two required preparation. This is a tiny 69 × 75 cell AOI, not a full-scene throughput benchmark. The two monitoring polygons are user-defined analysis boundaries, not cadastral data.

An external comparison against **exactextract 0.3.0** used the same live-run COG values and projected polygon geometries. Across **276 statistic/date/area evaluations (82 nonempty numeric means)**, maximum absolute mean disagreement was **7.30 × 10⁻¹²** index units and maximum area disagreement was **0.000245 m²**. Numerical tolerances were specified beforehand: 1 × 10⁻⁶ for means and 0.25 m² for areas. [Reference evidence](showcase/24-area-reference.json) includes package versions, input hashes, null checks and individual differences. This validates agreement of fractional aggregation kernels; shared projection inputs, physical cell homogeneity, satellite calibration, harmonization and interpolation accuracy are outside this comparison.

```bash
python scripts/capture_projects.py --live  # explicit public-network/browser check
uv run python scripts/export_project_tui.py
uv run --with exactextract==0.3.0 python scripts/validate_area_reference.py data/runs/RUN_ID
```

The `rslib:monitoring` container image was rebuilt with the locked Shapely dependency and current browser/gallery assets. With external networking disabled, its actual HTTP API created a polygon project, acquired the synthetic fixture toward an 80% support goal (stopping after six preparations), exported the area CSV and served the current gallery. After restarting the container process, the project recipe, run reference and area results reopened successfully. The disposable verification container was then removed. The wheel/source distribution build and Compose configuration check also pass; the wheel contains the project/area modules and captures/reference evidence 19–24.

## Whole-date satellite reconstruction check

The six-acquisition June 10–July 14 stack recorded in `22-live-project-evidence.json` is now evaluated by removing each complete UTC acquisition day across every sensor. The remaining clear days reconstruct the withheld reference with the same production gap interpolator and a 20-day whole-bracket limit. The paired nearest-bracket baseline uses identical cells and admissible brackets; an equal-distance tie chooses the earlier source. No edge extrapolation or same-day sensor leakage is allowed.

| Measure | Linear interpolation | Nearest bracket |
| --- | ---: | ---: |
| NDVI MAE / unit 1 | 0.01705973 | 0.01974583 |
| NDVI RMSE / unit 1 | 0.02251936 | 0.02561222 |
| Bias, prediction minus held-out / unit 1 | 0.00226734 | 0.00753316 |

**19,349 / 29,600 clear cell dates (65.368%)** were scorable, across **4 / 6 dates**. Both boundary dates remain unscorable and contribute to the coverage denominator. The per-date results include training-bracket medians; the aggregate is weighted by scored cell dates. This tiny AOI has correlated neighboring cells; counts do not represent independent statistical replicates. Clear measurements are not independent ground truth and do not reproduce the distribution under actual clouds. Cross-sensor/atmospheric/registration residuals contribute to these errors. The result does not establish calibrated uncertainty, causal forecasting, cross-region generalization or model superiority.

[Evaluation JSON and input SHA256](showcase/25-live-temporal-validation.json) · [actual browser evaluation](showcase/27-live-reconstruction-check.png). Run `uv run rslib validate-series data/runs/1315d34695e8484093cf6a0ec3cdacad --output data/temporal-validation.json` against the retained local inputs, or select **Withhold acquisition days** in the browser. Changing source files invalidates the stored manifest checksum and is rejected. Analytic tests verify exact linear reconstruction, whole-day exclusion including a conflicting second sensor, nearest-baseline error, non-extrapolation, bracket abstention and null metrics when nothing is scorable.

## Durable job execution

The [process-kill record](showcase/26-job-recovery-evidence.json) uses actual native raster preparation on an explicitly synthetic multisensor fixture. After the first completed scene checkpoint, the isolated owned API process group received SIGSTOP/SIGKILL. A new process recovered the same job/run IDs as attempt 2, retained eight candidate scenes, reused the completed scene cache and published one complete run. There is no injected worker delay or mocked raster processing. Unfinished output directories remained private.

The [browser acceptance record](showcase/27-browser-job-validation-evidence.json) cancels an actual satellite job, retries its saved job, reloads during execution and receives a complete result with **one original recipe submission**. The 390 px layout has no horizontal overflow and no browser page errors were recorded. The reconstruction endpoint exactly matches the checksummed evaluation JSON. [Terminal capture](showcase/29-terminal-job-journal.svg) and [evidence](showcase/29-terminal-job-evidence.json) open the same completed satellite job without another acquisition.

Automated cases also inject a source failure after a completed native scene, change the project revision, and verify retry preserves the original revision/index, reuses its cache even for an original refresh request, and attaches exactly one project-run reference. Tests cover queue idempotency, conflicting request keys, event cursors, queued/running cancellation, restart state recovery and a TUI attached to the server-owned queue. The [execution contract](JOBS.md) identifies cooperative cancellation, cache eviction, publication races, local-storage deployment and untested storage/load-failure limits.

The rebuilt `rslib:jobs` image was also exercised with Docker networking disabled: native synthetic preparation and temporal evaluation completed, the same completed job/run survived container restart, and the served evaluation capture matched the source SHA256. The disposable container was removed. [Runtime acceptance record](RUNTIME_ACCEPTANCE.json); rerun with `python scripts/accept_container_jobs.py --image rslib:jobs` after building the image. The wheel includes the job/progress/validation modules and the current 26/27/29 captures; their archive contents were compared with the source assets.


## Common-clear-cell sensor agreement

`compare-sensors` verifies the input stack checksum, chooses closest-time disjoint Landsat/Sentinel pairs within an explicit time limit and scores complete common clear spectra. The first real pair uses Landsat-9 `LC09_L2SP_218076_20260618_02_T1` and Sentinel-2B `S2B_T23KNR_20260619T131449_L2A`, separated by **24.34597 hours**, with **4,897** common cells (**95.9%** of AOI centre cells).

| Common band | Bias MSI−OLI | RMSE before local coefficients | Current RMSE | Current correlation |
| --- | ---: | ---: | ---: | ---: |
| Blue | −0.00253 | 0.00766 | 0.00779 | 0.542 |
| Green | −0.00187 | 0.01162 | 0.01171 | 0.447 |
| Red | −0.00318 | 0.01074 | 0.01068 | 0.796 |
| Narrow NIR | +0.00421 | 0.07478 | 0.07466 | 0.186 |
| SWIR1 | +0.00233 | 0.04786 | 0.04784 | 0.599 |
| SWIR2 | +0.00118 | 0.02750 | 0.02746 | 0.698 |

All reflectance errors have units 1. Before means inversion of only the run's recorded affine MSI bandpass coefficients; it is not a different atmospheric/BRDF processing chain. NDVI bias is **+0.01602**, RMSE **0.03046**, correlation **0.9789**. Median six-band spectral angle is **1.632°**, P95 **3.531°**. The weak NIR agreement remains a material finding despite favorable NDVI correlation. This pair cannot isolate atmospheric, angular, registration, temporal or calibration causes. It does not validate cross-sensor interchangeability or general coefficient improvement.

[Exact metrics and input hashes](showcase/30-live-sensor-agreement.json) · [actual browser capture](showcase/30-live-sensor-agreement.png) · [browser/research interactions](showcase/32-agreement-research-browser-evidence.json) · [same-run terminal checks](showcase/34-terminal-checks-evidence.json). Browser acceptance covers identical API/report values, exact scatter-cell selection on the comparison date, band switching, explicit empty overlap and responsive layout. Numerical tests cover analytical residuals, affine reversal, disjoint pairing, unknown upstream transforms, constant spectra, invalid parameters and checksum tampering. The terminal exercises both agreement and whole-date holdouts.

## Classical spectral methods

Seven spectral tests cover PCA orthonormality/inverse reconstruction, fixed-basis reuse and masks; VCA recovery of known simplex vertices with both original projection branches, source-cell mapping and repeatable seeds; FCLS pure/interior/boundary/outside-simplex solutions, sum-to-one/nonnegativity, a convex optimality gap and independent SciPy SLSQP comparisons; published OLI TOA coefficient checks and sensor/radiometry rejection; BCY strict threshold boundaries, missing inputs and the differing published SWIR variants. The CLI export test prepares a synthetic run, checks COG CRS/band descriptions/nodata, verifies artifact SHA256 and immutable input, and rejects tampered input.

The actual Sentinel-2 observed-scene analysis uses 4,897 cells, with FCLS median reconstruction RMSE **0.002821**, P95 **0.008445**, maximum convex optimality gap **1.42 × 10⁻¹⁶ reflectance²** and sum-to-one error **2.22 × 10⁻¹⁶** before float32 COG storage. These measure fit and numerical optimization, not material-fraction accuracy. VCA assumes pure pixels and linear mixing, neither independently established here. Public hyperspectral cross-implementation/reference comparisons remain pending. [Algorithm contracts](CLASSICAL_ALGORITHMS.md) · [source-bound report](showcase/35-live-spectral-report.json) · [interactive satellite figure](showcase/spectral.html) · [exact-cell/download/mobile browser evidence](showcase/35-spectral-browser-evidence.json).

The research survey records 98 reviewed entries, including 28 classical-method records, plus separately timestamped repository/checkpoint metadata. No weights were downloaded or inferred for that survey. It is not an execution or accuracy test of those candidates. The book review uses the publisher's public record/contents, not the full text.


## Shared spectral workflow — 2026-10-18

The operational browser/TUI now execute saved PCA/VCA/FCLS recipes through the durable queue, with a pinned source run, separate spectral result identity, component maps/loadings, source-cell selection, printable project-context report and portable request/artifact bundle. This replaces the earlier CLI-only execution limitation; the original standalone spectral page remains a historical saved showcase.

Seven queue/reference tests in `tests/test_spectral_jobs.py` exercise API/Python/CLI numerical parity; idempotent submissions and conflicts; source-checksum pinning at submission and execution; artifact tamper rejection; source-run-filtered history; cancellation before publication and pinned retry; reconciliation after publication without refitting; TUI submission, component selection, same-job reopening and cell inspection; unavailable-source handling without fabricated cells; input snapshot checking; and pre-kind SQLite/idempotency migration. The full suite is **82 passed, 4 skipped**. Existing optional-dependency skips retain the meaning described above.

[Real browser evidence](showcase/37-spectral-job-browser-evidence.json) uses `S2B_T23KNR_20260619T131449_L2A` from the retained six-source optical run. It checks actual job submission, numerical agreement with the prior CLI fit, publication/final journal events, raster/source-cell selection, component maps/loadings, missing cells, reload without duplicate submission, saved request/bundle consistency, report content, cancellation/retry and a 390 px layout. Page errors: zero. [Browser](showcase/37-queued-spectral-workbench.png) · [printable report](showcase/38-spectral-project-report.png) · [mobile](showcase/39-spectral-workbench-mobile.png).

[The same published browser job opens in the TUI](showcase/40-terminal-spectral-job.svg), sharing the running server's worker. [Four-interface evidence](showcase/40-spectral-interface-parity.json) compares the exact source checksums, PCA loadings, projected VCA spectra and FCLS diagnostics with separate Python and CLI executions on the same actual input. It does not establish scientific accuracy or universal cross-version bitwise equivalence.

[The real process-death experiment](showcase/41-spectral-process-recovery.json) uses an isolated owned server and the actual local satellite stack. Its harness delays only the production export checkpoint, sends SIGKILL before publication, restarts without that delay and recovers the **same job and analysis ID as attempt 2**. The incomplete report returns 404; the final result matches the original source hashes/FCLS diagnostics, both fits and recovery are journaled, and private staging disappears after publication. The fit restarts on the pinned input; internal eigensolver/FCLS state is not resumed. The separate unit test covers publication-before-database-commit reconciliation. These are specific interruption checks, not storage-failure, soak or load certification.

[The reference registry](reference-projects/README.md) now freezes six small actual-satellite runs. The five new case selections precede raster processing and retain full public STAC/collection documents, original site/partition roles, input hashes and source/license declarations. `reference-acquire` resumes a pinned inventory; `reference-register` refuses to replace a frozen entry; `reference-check` verifies local inputs and source metadata. Split checks reject shared declared sites, overlapping AOIs and exact shared source IDs across development/holdout roles. Independent cloud/material labels and held-out accuracy evaluation remain unfulfilled A1 work.

## Multi-site reference diagnostics and documentation

[The numerical audit](showcase/42-reference-case-audit.json) includes all six cases and 26 acquisitions. It reports per-source complete-spectrum support, query-date support, a separate one-day-query diagnostic, whole-UTC-date reconstruction scoring coverage and accepted/rejected sensor pair diagnostics. Unsupported cell dates and zero-scored comparisons are retained. The Ames crop-selection case has zero support on its saved five-day query grid despite retained source spectra; evaluating every day leaves 94.17% unsupported. Tromso similarly has zero saved-grid support and 98.39% daily-query missingness. Manaus daily-query missingness is 99.71%. The inputs and frozen recipes were not changed to improve these outcomes.

[The actual case viewer](showcase/reference-cases.html) reads prepared observations, not generated illustrations: fixed 0–0.30 RGB and 0–0.50 NIR/SWIR1/red display scales, explicit missing cells and a separate retained-QA mask. [Browser evidence](showcase/43-reference-browser-evidence.json) checks first/last acquisitions at each site, image loading, partition/source labels, timeline row counts, documentation search/navigation, mobile overflow and JavaScript errors. [Desktop reference capture](showcase/43-reference-case-browser.png), [mobile](showcase/43-reference-mobile.png), [documentation desktop](showcase/44-documentation-site.png) and [documentation mobile](showcase/44-documentation-mobile.png) retain the actual rendered result.

Planetary Computer rate limiting interrupted the first new acquisition campaign. Container-scoped, expiry-aware SAS reuse now avoids signing every native band independently. Offline tests exercise concurrent single-token acquisition, expiry refresh, invalidation, separate-container scopes, invalid/expired responses, numeric/HTTP-date Retry-After and explicit failure on a longer server cooldown. Tokens stay in memory. The five new cases subsequently completed from their retained inventories and caches; this is recovery evidence, not a throughput benchmark.

The local suite passed **93 Python tests with 4 optional-dependency skips** and **9 Rust physics tests**. Python formatting/lint, Rust formatting/clippy, frontend type checking/build, strict documentation build, lock validation and wheel/sdist build passed. A fresh hosted CI run separately checks the committed implementation. Test counts and successful builds do not supply independent accuracy labels.
