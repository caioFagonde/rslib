# RSLIB delivery roadmap

Proposed 2026-10-17, based on the [product audit](PRODUCT_AUDIT.md), [validation record](VALIDATION.md) and [quantitative-method review](REMOTE_SENSING_RESEARCH.md). Release labels below describe proposed scope, not scheduled dates. Sequence work by acceptance evidence; estimate dates after measuring the first milestone and confirming engineering capacity.

The first supported project should be concrete: select an area and interval, discover suitable observations, prepare comparable optical data, inspect quality and temporal support, run an analysis, and export a reproducible report. Browser, TUI, CLI and Python must execute the same saved recipe. A project should remain usable when data are missing, a provider fails, or a process restarts.

## Existing baseline

Implemented: bounded Sentinel-2/Landsat preparation; native QA before aggregation; partial bandpass adjustment; common projected grids; daily source-preserving mosaics; bracket-limited interpolation; fractional polygon statistics; saved projects; a recoverable local queue; whole-date reconstruction checks; cross-sensor diagnostics; observed-scene PCA/VCA/FCLS through shared library/CLI/browser/TUI jobs; separate TOA-only tasseled-cap and BCY primitives; opt-in SR inference; soil helpers; and an independent Rust wet-initial-condition infiltration/slope engine.

Do not schedule these as new features. Their integration, validation, scale and coverage still need work. In particular, the current xarray adapter wraps materialized data and HLS high-level discovery is incomplete. Spectral execution/report integration is implemented; independent fraction/cloud labels and broader scientific evaluation remain absent.

## Release A: dependable optical monitoring

### A1. Establish reference projects and finish an existing workflow

**User outcome:** reopen a project, understand its available data, execute the existing analysis and reproduce its exports without reconstructing parameters manually.

- Freeze reference inventories and licensed fixtures across humid/cloudy vegetation, seasonal agriculture, urban/bare surfaces, water/coast, snow and steep terrain. Keep development, tuning and evaluation sites/seasons disjoint. Preserve real failure examples.
- Retain small offline fixtures for CI and a separate opt-in live regression suite. Public observations and independent labels serve different roles; do not replace labels with another model's predictions without identifying that reference.
- Add live PCA/VCA/FCLS execution to the shared job contract and browser/TUI, with saved parameters, fit-source selection, component inspection, cancellation and exports. Preserve the existing immutable source run.
- Add a project report containing sources/product versions, recipe, quality/support, observed versus estimated values, diagnostics, limitations and export links. Reports should support one useful monitoring task before adding numerous templates.
- Remove stale capability/status descriptions across the interfaces and documentation.

**Acceptance:** one pinned project executes through all four interfaces with equivalent numerical outputs and source hashes. It reopens after restart; a failed/cancelled job leaves no published partial result. A reviewer can identify the source of a plotted/exported value and reproduce the report from the recipe. Keep actual desktop/TUI/mobile captures and interaction evidence.

### A2. Establish sensor and QA comparability

**User outcome:** choose a supported processing policy and see whether acquisitions are suitable for comparison.

- Integrate documented HLS L30/S30 discovery/access, current product versions, Fmask/aerosol policy, access requirements and source provenance. Existing preharmonized ingestion must not receive the local bandpass transform twice.
- Investigate the measured NIR disagreement using multiple near-coincident pairs, stable target areas, native footprints, residual image offsets, acquisition angles and atmosphere/QA. A common grid is not proof of coregistration; do not fit a correction to this one pair.
- Add optional registration diagnostics, then correction with an explicit transform and retained uncorrected input if justified. Add angle-based normalization only when required angles/coefficients exist. Keep topographic correction separate from BRDF normalization and test low-illumination terrain behavior.
- Compare native QA with supported Fmask/cloud-probability policies; include thin cloud, shadow, snow, bright surfaces, haze and cloud-edge distance. Expose policy and buffer choices with their effect on coverage. Keep the TOA BCY adaptation separate from the original MSS method and SR masks.
- Verify original published SR tasseled-cap coefficient tables before adding sensor/product-specific profiles.

**Acceptance:** publish per-band residuals and spatial-offset diagnostics across held-out sites/seasons, with sample coverage and land-cover/geometry strata. Publish cloud/shadow omission and commission separately. Set task-specific tolerances before evaluating the held-out set. Do not promote a correction or QA default solely because it improves aggregate NDVI or one scene.

HLS already supplies a harmonization chain; integrate it before attempting to reproduce that entire chain. Its documented snow, aerosol and shadow limitations remain relevant. [NASA HLS on AWS](https://registry.opendata.aws/nasa-hls/).

### A3. Process larger projects within a declared resource budget

**User outcome:** a longer interval or larger AOI does not require loading the whole cube into RAM.

- Define a versioned cube contract: physical units, sensor/product level, named bands/spectral responses, time, CRS/grid, nodata, categorical QA, observational support, lineage and any separately defined uncertainty.
- Benchmark the existing GDAL path against an ODC-STAC/xarray/Dask implementation with equivalent calibration, QA and aggregation. Select the execution backend from evidence. Changing array containers must not change scientific semantics.
- Implement window/chunk execution, COG-aligned reads, bounded concurrency, partial-result reuse, cancellation boundaries and resumable exports. Use COG for maps and chunked Zarr for persistent temporal arrays after round-trip/version checks.
- Serve overviews/tiles and bounded inspector queries to the browser. Keep full-resolution reducers/export on the analysis backend. Cache identity must include calibration, QA, geometry and method versions.
- Use optional PostGIS for persistent spatial scene/project queries where it is useful. Retain the local installation and job store; require a concrete multi-user deployment before introducing distributed scheduling.

**Acceptance:** chunked and existing bounded outputs agree within declared numerical tolerances, including chunk seams, masks, timestamps and source indices. Interruption resumes without reacquiring completed compatible chunks. Record processing time, request/byte counts, cache states, peak RSS, output size and failures.

**Proposed benchmark profile, not current performance:** a 16 GB RAM workstation, optional 6 GB GPU; 2 × 2, 10 × 10 and 50 × 50 km AOIs, a 30 m common grid and a year of pinned optical acquisitions. Target worker peak RSS at or below 8 GiB on the largest case. Separate cold acquisition, prepared-cache reuse and product reopening. Establish wall-time targets after baseline measurements. For cached local projects, target p95 cell/date interaction below 250 ms over at least 100 scripted interactions, excluding network acquisition and basemap loading.

[ODC-STAC](https://odc-stac.readthedocs.io/en/latest/) already loads STAC Items into xarray; [xarray/Dask](https://docs.xarray.dev/en/stable/user-guide/dask.html) supplies chunked execution. Reuse these capabilities when parity and resource tests support the choice.

### A4. Deliver dependable composites and temporal analysis

**User outcome:** request a monthly composite or a regular series and understand which observations support it, where it is estimated and where it remains unavailable.

- Expose quality/medoid composites with full-spectrum consistency, per-cell source date, observation count, temporal spread and coverage. Define overlap/seam policy explicitly.
- Add QA-weighted Whittaker smoothing as the first operational smoothing candidate, with an explicit irregular-time formulation or recorded resampling. Compare with the existing linear/nearest baselines; evaluate local polynomial and state-space alternatives when they address a measured failure.
- Add event-sensitive gap rules, maximum gap/age, no extrapolation by default and explicit abstention. Preserve acquired values in reconstruction products; keep smoothed estimates in a separate product.
- Extend whole-date holdouts to contiguous gaps, real cloud-shaped masks and abrupt-change periods. Separate retrospective interpolation from causal updating. If uncertainty is emitted, evaluate calibration and out-of-domain behavior.
- Add phenology summaries only when temporal support is adequate. Candidate acquisition should report whether a new read increased usable support and its cost.

**Acceptance:** evaluate identical held-out cells against fixed baselines, reporting errors alongside reconstruction coverage and abstention. Stratify by gap length, season, cloud context and change. Do not accept lower error obtained merely by refusing difficult cases. Report any coverage/error tradeoff. Include a real-data composite/series comparison with inspectable source dates.

**Release A exit:** the same monitoring project can be acquired, resumed, inspected, analyzed and reported at the declared benchmark scales. Scientific limitations and operational failures remain visible. This is the first release suitable for a focused external operator trial.

## Release B: classical analysis and additional sensing modalities

### B1. Complete a coherent classical toolbox

Implement related operations as reproducible fit/apply workflows, with saved coefficients and mask contracts:

1. Spectral indices and verified tasseled-cap profiles; PCA fit reuse; MNF with a defensible noise covariance and conditioning controls.
2. SAM/SID, RX, matched filters and ACE with declared background/reference spectra and false-alarm evaluation.
3. VCA/FCLS validation, PPI/N-FINDR and endmember-count diagnostics; spectral-response resampling and continuum/absorption features for actual imaging-spectrometer data.
4. Haralick textures and morphology with declared quantization, physical window size, directions and nodata/edge treatment.
5. MAD/IR-MAD and relative normalization; COLD/CCDC/LandTrendr-style long-history analysis only when sufficient temporal history exists.

Integrate supported [OTB](https://www.orfeo-toolbox.org/CookBook/Applications/app_DimensionalityReduction.html), Spectral Python and PySptools routines where their behavior and licensing fit. Do not independently implement every reviewed algorithm. Preserve the distinction between exploratory scores and calibrated physical estimates.

**Acceptance:** independent numerical/reference comparisons, public hyperspectral cases with appropriate labels, held-out task evaluations and resource measurements. Browser/TUI/CLI execute saved operations rather than presenting a static showcase as an execution control. Ship a report template only when it uses those actual outputs.

### B2. Add calibrated Sentinel-1 and optical/SAR workflows

- Start with supported analysis-ready backscatter or a separately reproducible calibration/terrain-correction backend.
- Preserve orbit, polarization, acquisition geometry, linear versus dB units, incidence effects, layover/shadow masks and speckle assumptions. Do not treat ascending/descending observations as interchangeable.
- Add evaluated speckle policies and temporal statistics, then flood/wetness/change tasks with independent reference events. Sensor fusion needs defined spatial footprints and temporal offsets.
- Keep SAR-assisted optical estimation labeled as estimation. InSAR needs a separate complex-data/interferometric workflow and reference validation.

**Acceptance:** geometry/radiometry comparison with reference processing and geographically separated event/season evaluation. Adding SAR must demonstrate useful information beyond the optical baseline while reporting missingness and domain limitations.

### B3. Integrate a small number of measured ML improvements

- Use a model-adapter contract with exact preprocessing, band/time masks, product level, checkpoint checksum, license, output units/type, tiling, supported device and resource limits.
- Start with one compact temporal/frozen-feature candidate and a tree/linear baseline on the same target/splits. Reuse supported [TorchGeo interfaces](https://docs.torchgeo.org/en/stable/api/models.html) instead of duplicating loaders.
- Benchmark cloud reconstruction only after A4's missingness/change evaluation is available. Extend SR only after spectral/observed-resolution consistency and independent reference comparisons exist.
- Record complete local deployment costs: weight loading, preprocessing, inference, stitching, export, wall time, peak process RAM and total GPU memory. Report warm inference separately.

**Acceptance:** a defined task improves on a declared held-out baseline under a declared consumer-hardware budget, or offers a justified accuracy/cost tradeoff. A smaller checkpoint, sharper image or successful inference alone does not satisfy the gate. Weights remain opt-in.

**Release B exit:** a user can execute reproducible classical and selected optical/SAR analyses through the workbench, with reference comparisons and exportable results. Model integration is limited to demonstrated improvements.

## Release C: quantitative applications

Deliver one application at a time against its required measurements. The following are independent modules, not capabilities implied by a shared map.

| Module | Prerequisites and deliverable | Acceptance evidence |
| --- | --- | --- |
| Vegetation biophysics | Sensor-response-aware PROSAIL LUT/inversion, declared priors, LAI/leaf-water units and identifiability diagnostics | Independent field targets, geographic/seasonal splits, uncertainty coverage and comparison with a simple empirical baseline |
| Thermal and ET | Ingest documented LST/emissivity with QA; align meteorological forcing; evaluate TSEB/ETLook-type energy-balance workflow | Ground/tower references, footprint/time alignment, energy closure, sensitivity to forcing and uncertainty |
| Soil and SOC | Typed SoilGrids depth/property stacks, local survey assimilation, equivalent-soil-mass comparisons and defensible joint uncertainty | Unit/depth/mass conservation, sampled site validation and correlation sensitivity. Stock change is not measured emissions |
| Inland/coastal water | Water-appropriate atmospheric/adjacency processing, explicit optical-water conditions and target retrieval | Matchups for reflectance and target water-quality variables; cloud/glint/shoreline controls and transfer limits |
| Forest structure/carbon | Registered lidar/height references, inventory plots and explicit allometry; disturbance history | Independent plot/site validation, propagated structural/allometric uncertainty; stock versus flux kept distinct |

The remaining sensing/application branches stay in the [research inventory](research/INDEX.md) until a user task, required inputs, implementation choice and acceptance data justify a delivery milestone.

## Independent Rust hydrology track

This remains an independent implementation of public TRIGRS reference equations, without requiring an installed TRIGRS executable. It can progress alongside the product milestones but must not delay or silently broaden the optical release.

1. Maintain the implemented wet-initial-condition kernel, equation map, independent numerical references and mass accounting; add independently transcribed published benchmark cases and parameter sensitivity.
2. Implement the unsaturated Gardner/Richards formulation incrementally. Validate initial/boundary conditions, root/series convergence, limiting cases and independent PDE solutions before coupling a moving water table.
3. Define capillary-fringe, moving-water-table and material/input conventions explicitly. Extend rainfall fields and routing only with declared depression, storage and travel-time assumptions.
4. Add spatial parameter stacks and ensembles, exposing the provenance and absence of required hydraulic/geotechnical inputs. Pedotransfer results must not silently supply diffusivity, cohesion, friction or soil depth.
5. Couple rainfall/soil/terrain into a reproducible scenario workbench with pressure, FS, critical sampled depth/time, sensitivity and water balance. Compare public reference outputs when available and obtain independent site observations before hazard evaluation.

**Acceptance:** equation-specific convergence and independent numerical agreement, mass accounting and uncertainty/sensitivity evidence before field-use claims. Keep hypothetical scenarios separate from observations. See [HYDRO.md](HYDRO.md).

## Execution and presentation rules

- Limit active product work to one milestone and one enabling infrastructure item. Keep specialist research scoped separately. Do not turn every research entry into an active implementation project.
- Prefer one complete user task over partially wired controls. Each substantial delivery includes the shared library operation, recipe, error/recovery behavior, export, validation record and real browser/TUI captures where applicable.
- Maintain one declared supported hardware/deployment profile before adding distributed/GPU services. Add PostGIS/Compose services for demonstrated persistent-query or deployment needs.
- Add deck.gl layers when a result benefits from them: overview/tiled rasters, linked plots and swipe first; terrain profiles/cutaways for validated terrain models; point clouds only with a supported lidar workflow. Turf remains useful for interaction, with quantitative calculations using the documented backend geometry/CRS path.
- Concept art should explore a specific upcoming interaction and remain labeled as proposed. Capture implemented behavior separately; no conceptual screenshot is acceptance evidence.
- Record application error tolerances before opening held-out results. Track numerical parity, QA errors, reconstruction error/coverage, cache/recovery behavior, resource use and operator task completion separately.

## Immediate implementation sequence

1. Freeze the current real-run evidence and define the multi-site reference-project manifest, labels and evaluation split policy.
2. Put the existing spectral analysis behind the durable job contract and add saved browser/TUI execution, inspection and reproducible report export.
3. Implement HLS high-level discovery/access and expand near-coincident pair/QA diagnostics; investigate the weak NIR result without fitting to it.
4. Baseline larger pinned jobs and select a chunk execution/storage path that passes calibration/QA parity checks.
5. Add QA-weighted temporal/composite policies and evaluate them against the existing paired holdouts before selecting an optional reconstruction model.

A1 is the recommended next milestone. A2 starts with the existing poor-NIR example as a retained diagnostic case. A3 begins with measurement and parity design, not a broad rewrite.


## A1 progress — 2026-10-18

Delivered: spectral jobs in the shared queue with pinned source hashes, saved fit parameters, browser/TUI execution and inspection, per-source-run history, cooperative cancellation, atomic exports, restart recovery, downloadable requests/COGs/bundle and a printable report with parent recipe/support and implementation provenance. Existing optical queue records and pre-kind idempotency keys remain compatible. Actual satellite browser/TUI captures, four-interface numerical parity and a real process-kill recovery record are available in VALIDATION.md.

Reference coverage now includes six small actual-satellite runs: Itatiaia, Ames, Las Vegas, Santos, Tromso and Manaus. The five new site/partition choices were frozen before processing; public STAC/collection documents, input hashes, source license declarations and retained failures are recorded. CLI acquisition, immutable registration, verification, split checks and a support/paired-diagnostic audit are implemented. The viewer distinguishes saved-query support from daily and per-acquisition support. Independent labels, application tolerances and held-out accuracy evaluation remain open, so A1 is not complete. A2–C remain proposed work.
