# Product audit — 2026-10-18

RSLIB currently supports bounded optical preparation and inspection, with separate research modules for hydrology, soil calculations and model inference. It has not demonstrated professional readiness for a complete monitoring project, scientific superiority, or production-scale throughput. Earlier presentation gave the implemented demonstrations too much prominence relative to these gaps.

## What a user can do now

- Prepare Sentinel-2 and Landsat surface reflectance for a small bounding box, with explicit band mapping, calibration, native QA, common projected grid and partial bandpass adjustment.
- Inspect a regular index series at a grid cell, distinguish observed daily mosaics from estimates, and identify the two source acquisitions used for an interpolation. Export that series as CSV.
- Export georeferenced index/composite COGs for GIS work, plus the six-band stack, support arrays and source manifest for Python analysis.
- Define named polygon areas, inspect projected fractional-cell statistics by date, and compare a constant observed spatial footprint.
- Save a project and run history locally, reopen it from the browser or TUI, and execute it from the CLI.
- Measure native-QA temporal support and acquire further planned candidates toward a declared coverage goal, within a scene budget.
- Submit an immutable job, inspect scene/export checkpoints, cancel cooperatively, retry using completed scene caches, and recover the same job after a process restart. Browser and TUI share the queue.
- Withhold each complete acquisition day across sensors, compare linear and nearest-bracket reconstruction on paired clear cells, and inspect scoring coverage, per-date errors and input checksums.
- Compare disjoint near-coincident Landsat/Sentinel acquisitions on identical clear cells by band and NDVI, inspect before/after local coefficient residuals and spectral angles, and select plotted cells in the existing browser inspector. Browser, TUI and CLI use the same diagnostic core.
- Fit observed-scene covariance PCA, select geometric VCA endmembers and export FCLS fractions/residual COGs with coefficients, source cells and hashes through the shared browser/TUI/API/CLI/Python path. Jobs pin source checksums, save fit parameters, support cancellation/recovery and export a printable report/artifact bundle; material-fraction accuracy is unvalidated.
- Change the interval, index or interpolation bracket without repeating compatible scene preparation. Save a browser recipe as the same JSON request accepted by the API; reopen an existing run by URL.

These operations support exploratory data preparation. An index change is not automatically a vegetation diagnosis, a carbon estimate or evidence of a landslide. The synthetic example verifies processing behavior; it cannot establish satellite-data accuracy.

## Problems in the previous interface

| Finding | Consequence | Correction in this revision |
| --- | --- | --- |
| Slogans such as “One recipe. Many sensors.” and “Every source stays attached.” | Occupied space without describing an action, result or limitation | Functional headings; removed promotional copy from the workflow, scene explorer and capture gallery |
| Automatically ran synthetic input | The first visible result did not answer the user's own question | Start with an empty workspace and explicit satellite or synthetic execution |
| Reported “Complete” when 76.35% of requested pixel dates were unsupported | Processing success could be mistaken for adequate data | Missing coverage shown above the rasters; output status includes the missing fraction |
| Three static images and an AOI-average curve | A user could not investigate a local anomaly or trace a filled value | Raster cell selection, exact values, source brackets, dated chart and cell CSV |
| Chart lacked date ticks and an index/units label | Values could not be read independently of surrounding controls | UTC dates, named dimensionless index, selected-date guide, distinct markers for estimated cell values |
| Decorative synthetic swatches beside catalog scenes | Looked like image thumbnails without showing source imagery | Removed; catalog rows contain acquisition metadata |
| Small warm-cache processing time was prominent | Could imply fast acquisition or large-area performance | Time labeled processing/export only; catalog search explicitly excluded |

The [Wikipedia AI-writing guide](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing) describes promotional language, significance inflation and repeated rhetorical structures. It is a descriptive editorial guide, not an authorship test. Its warning against merely hiding surface signs applies here: the task and evidence gaps must also be fixed. [NN/g's dashboard guidance](https://www.nngroup.com/articles/dashboards-preattentive/) emphasizes quantitative information that supports a decision; decorative counters do not provide that by themselves.

## Work still required

| Area | Current limitation | Evidence required before calling it ready |
| --- | --- | --- |
| Project workflow | Named polygon areas, drawing/import, local project persistence, run browser and CLI/TUI execution are implemented. Multi-project batch reports and remote collaboration remain absent | Browser interactions and API/CLI/TUI restart tests exercise saved projects; external GIS round-trip and operator usability review remain required |
| Coverage acquisition | Native-QA support now drives additional acquisition within a bounded planned pool. Metadata ranks unread candidates; there is no global optimum or field-specific target guarantee | Goal/budget stopping and measured support progression are tested. Candidate-pool expansion, source-read costs and larger-area evaluation remain pending |
| Harmonization | Ordinary S2/Landsat SR receives bandpass adjustment; no common atmospheric reprocessing, BRDF normalization or image-based registration. A first 24.35-hour pair shows weak NIR agreement (r=0.186, RMSE=0.07466); high NDVI correlation does not establish reflectance agreement | Common-clear-cell diagnostic and inverse local-coefficient checks are implemented. Broaden pairs across regions/seasons/land cover; independently measure registration, illumination and atmospheric contributions; compare HLS as a reference product, not ground truth |
| Gap filling | Whole-date multisensor holdouts now measure paired linear/nearest errors and scoring coverage. The first six-acquisition satellite test scores only 65.37% of clear cell dates. No calibrated uncertainty or general accuracy claim | Extend to independent regions/seasons and real cloud-shaped missingness; stratify by gap length, land cover and change. Declare application tolerances before evaluating those sets |
| Field statistics | Fractional polygon/cell weights, observed/estimated/missing area, and a fixed observed footprint are implemented; cell homogeneity and projected planar area are explicit assumptions | Analytic rectangles, holes, slivers and changing-population tests pass. An external exactextract comparison on the live COGs agrees within recorded numerical tolerances (see VALIDATION.md). Field-data validation remains pending |
| Reliability | Local durable queue, immutable recipes/inventories, per-scene journal, cancellation, cache-aware retry and atomic output publication are implemented. No distributed scheduling, quotas or retention policy | An owned API process was killed after a completed native scene read; the same job resumed as attempt 2, reused that cache and published one result. Browser reload/cancel/retry and TUI shared-job reopening pass. Storage-failure, load and long-running soak tests remain required |
| Performance | Bounded arrays/local COGs; catalog, processing/export and workflow-total times are separate. Demonstrations still use tiny AOIs, often warm | Measure catalog, signing, range reads, preparation, temporal work and export separately; record wall time, bytes read, cache state and peak RSS on fixed small and larger fixtures |
| Interoperability | Optional xarray view wraps materialized data; NPZ is the portable stack export | Validate round trips in external GIS/Python tools; evaluate a chunked storage/loading backend for larger jobs |
| Scientific applications | Soil helpers, hydrology equations and SR inference are separate components | Site-specific inputs, independent numerical references, held-out observations and application-specific error tolerances; no carbon-flux or hazard claims from demonstrations |
| Classical spectral methods | PCA/VCA/FCLS library and observed-scene CLI are implemented, with explicit TOA-only BCY/tasseled-cap primitives. Browser/TUI execution, source/component/cell inspection and printable project-context reports are implemented. No independent material-fraction validation | Analytical simplex recovery, independent SLSQP comparison, nodata/band/calibration guards, COG/hash checks and actual-data cell inspection pass. Same-job browser/TUI reopening, four-interface numerical parity and real SIGKILL recovery on the satellite input pass. Public hyperspectral reference comparisons and application labels remain required; MNF/noise covariance and SR tasseled-cap profiles remain candidates |

Acceptance tolerances for scientific errors must be declared for a specific application before evaluating a held-out set. Reporting a test count or adding a model name does not satisfy these requirements.

## Existing work to build upon

[NASA HLS](https://hls.gsfc.nasa.gov/algorithms/) already defines a harmonization chain including common atmospheric processing, masks, BRDF normalization, spectral adjustment and common grids. RSLIB's coefficient transform on ordinary SR implements only part of that chain. Prefer ingesting the complete HLS product when it fits the task; support for direct HLS discovery/access still needs to be integrated into the high-level workflow.

[odc-stac](https://odc-stac.readthedocs.io/en/latest/) already loads STAC Items into xarray datasets. [Copernicus openEO](https://documentation.dataspace.copernicus.eu/APIs/openEO/openEO.html) provides a data-cube processing API. A custom STAC-to-array path alone does not establish novelty. A comparative benchmark is needed before replacing or claiming an advantage over an existing loader.

The local monitoring workflow now implements saved polygon projects, support-driven acquisition, map/source inspection and fractional-cell statistics. First cross-sensor residuals, whole-date reconstruction checks, an external aggregation comparison and a real process-kill recovery test are recorded in VALIDATION.md. The next acceptance work is broader sensor/cloud/change-stratified evaluation, larger-area resource measurements and storage/load failure testing. The research inventory and observed-scene spectral extension do not close those operational/scientific gaps.


## A1 delivery and remaining reference coverage

The spectral execution/report path from roadmap A1 is implemented. [Browser acceptance](showcase/37-spectral-job-browser-evidence.json) and [four-interface parity](showcase/40-spectral-interface-parity.json) use the same actual satellite source. A dedicated [process-kill check](showcase/41-spectral-process-recovery.json) verifies recovery at an export checkpoint. This does not establish distributed/load/storage-failure readiness.

[The reference-project registry](reference-projects/README.md) now freezes six small actual-satellite runs, including five sites selected with development/holdout roles before processing. The new captures retain unsigned STAC inventories, collection/license documents and hashes. CLI capture/resume, immutable registration, local verification and site/AOI/source split checks are implemented. [The case audit](showcase/42-reference-case-audit.json) retains low-support and unscorable results; the crop and snow cases show that the saved five-day query grid can miss acquisition days. Daily-query diagnostics do not change the frozen recipes.

This is still an engineering set. Independent cloud/material labels, declared application tolerances and a held-out accuracy evaluation remain absent. The older Itatiaia case lacks pre-acquisition full licensing/source metadata. Capturing a collection's license declaration is evidence, not automatic legal clearance. A1's full reference-coverage gate and later release milestones remain open.

The larger live acquisition exercise also exposed Planetary Computer signing rate limits. Container-scoped SAS reuse is now bounded, thread-safe and in-memory; expiry refresh and read-failure invalidation avoid signing every band separately. HTTP-date/numeric Retry-After values are honored within the bounded retry budget; a longer server cooldown fails instead of retrying early. Offline concurrency/expiry/error tests pass, and all five pinned new cases completed after the change. This does not establish service availability or a throughput benchmark.
