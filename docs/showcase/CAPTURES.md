# Visual progress gallery

Open [the gallery](index.html) or use **Development captures** in the browser after rebuilding. Screenshots are captured from working software; concept art is explicitly marked. Scientific figures are rendered from actual model outputs.

| Artifact | What it shows |
| --- | --- |
| [01 — browser](01-browser-demo.png) | Working local explorer and cloud-masked synthetic NDVI; not satellite observations |
| [02 — concept](02-concept-earth-workbench.png) | AI-generated future visual direction; proposed terrain/soil cutaway, linked uncertainty, richer browser/TUI views |
| [03 — terrain](03-browser-terrain.png) | Working deck.gl Copernicus DEM GLO-30 surface mesh with synthetic NDVI texture; source elevation acquired from AWS |
| [04 — Rust laboratory](04-rust-storm-lab.png) | Working storm-simulation dialog, hypothetical SI-unit materials/forcing |
| [05 — live imagery](05-live-sentinel-analysis.png) | Actual Sentinel-2 C1 data searched, window-read, calibrated and masked by the application |
| [06 — mobile](06-mobile-workbench.png) | Responsive browser layout |
| [07 — terminal](07-terminal-workbench.svg) | Actual Textual application rendered with its half-block raster preview |
| [08 — scientific figure](08-rust-physics.png) | Actual Rust pressure-head and FS calculations; [SVG](08-rust-physics.svg), [input](08-rust-physics-input.json), [result](08-rust-physics-result.json) |
| [09 — consumer SR](09-superresolution.png) | Actual pretrained SEN2SRLite inference over native-grid Sentinel-2 RGBN, compared with nearest/bicubic display; [measurement](09-superresolution-evidence.json); no HR accuracy reference |
| [10 — temporal analysis](10-temporal-baselines.png) | Actual quality/medoid compositing, source indices/counts and irregular gap interpolation over an explicitly synthetic sequence; [evidence](10-temporal-evidence.json) |
| [11 — practical workflow](11-practical-optical-workflow.png) | Actual browser recipe, common-grid multi-sensor preparation, composite, timeline and real prepared-cache reuse over synthetic native sensor grids; [evidence](11-workflow-evidence.json) |
| [12 — gap support](12-gap-support.png) | Actual per-date observed/interpolated/unsupported support view |
| [13 — workflow on mobile](13-workflow-mobile.png) | Actual responsive workflow UI |
| [14 — live multi-sensor workflow](14-live-optical-workflow.png) | Actual Landsat 8/9 and Sentinel-2 B/C data, temporal filling, visible coverage limits and shared prepared cache; [evidence](14-live-workflow-evidence.json) |
| [16 — cell inspection](16-cell-inspection.png) | Revised interface, exact cell values, source brackets, missing coverage and CSV export over synthetic input; [interaction evidence](16-inspection-evidence.json) |
| [17 — live cell inspection](17-live-cell-inspection.png) | Revised interface with four actual satellite acquisitions; [inspection evidence](17-live-inspection-evidence.json); large temporal gaps remain missing |
| [18 — cell inspection on mobile](18-inspection-mobile.png) | Revised workspace at 390 px width |
| [19 — monitoring project](19-monitoring-project.png) | Actual saved project, imported polygon holes, map selection, fractional-cell area statistics and QA-measured acquisition over synthetic inputs; [evidence](19-project-evidence.json), [CSV](19-area-series.csv) |
| [20 — area support](20-area-support.png) | Selected-date support over monitoring polygons |
| [21 — monitoring on mobile](21-monitoring-mobile.png) | Current project UI at 390 px width |
| [22 — satellite monitoring](22-live-monitoring-project.png) | Actual support-driven preparation of six satellite acquisitions; [evidence](22-live-project-evidence.json) |
| [23 — terminal project](23-project-terminal.svg) | Actual TUI reopening the same saved browser project, with date/area tables; [evidence](23-terminal-project-evidence.json) |
| [24 — aggregation reference](24-area-reference.json) | Numerical comparison with exactextract 0.3.0 on actual satellite COGs and projected polygons |
| [15 — terminal workflow](15-terminal-optical-workflow.svg) | Actual Textual optical recipe with date navigation and gap support |

`capture-evidence.json` records browser errors, capture types and live scene/statistics. The concept was created using the built-in imagegen tool; [the full prompt](concept-prompt.txt) is retained. Some depicted capabilities and source names are artistic proposals and are not implemented. Illustrative cloud comparisons do not imply that cloudy pixels can be recovered from one observation.

Refresh the gallery as the software changes:

```bash
# A local server must already be running on port 8768.
python scripts/capture_showcase.py --live  # requires Playwright and Chromium
python scripts/capture_workflow.py --live
python scripts/capture_projects.py --live
uv run python scripts/export_project_tui.py
uv run python scripts/export_tui.py
uv run python scripts/export_workflow_tui.py
uv run --with matplotlib python scripts/export_science_figure.py
uv run --extra sr --with matplotlib python scripts/showcase_superresolution.py
uv run --with matplotlib python scripts/showcase_temporal.py
npm --prefix web run build
```

Captures 01–15 retain earlier interfaces. Captures 16–18 document the revised optical workspace. The [product audit](../PRODUCT_AUDIT.md) distinguishes implemented actions from missing validation and project infrastructure.

Captures 19–23 are the current monitoring workflow. Captures 16–18 retain the previous cell-inspection interface. Reference record 24 tests fractional aggregation separately from imagery and interpolation accuracy.


| Current extension | Evidence |
| --- | --- |
| [30 — satellite sensor agreement](30-live-sensor-agreement.png) | Actual 24.35-hour Landsat-9 / Sentinel-2B pair, common clear cells, band residuals and inspectable scatter; [JSON](30-live-sensor-agreement.json) |
| [31 — sensor agreement mobile](31-agreement-mobile.png) | Actual responsive diagnostic panel |
| [32 — searchable methods](research.html) | Research tool with 98 reviewed entries, including 28 classical-method records; candidates are identified separately from installed operations |
| [34 — terminal sensor agreement](34-terminal-sensor-agreement.svg) | Actual shared diagnostic core on the same published satellite run; [checks](34-terminal-checks-evidence.json) |
| [35 — satellite spectral analysis](spectral.html) | Interactive computed RGB/PCA/FCLS/residual rasters, observed-cell spectra, source endmembers and report download; [capture](35-live-spectral-analysis.png), [report](35-live-spectral-report.json), [browser evidence](35-spectral-browser-evidence.json) |
| [36 — spectral figure mobile](36-spectral-mobile.png) | Same saved actual-data analysis at 390 px width |

Reproduce the spectral figure with `uv run rslib spectral-analysis data/runs/1315d34695e8484093cf6a0ec3cdacad data/spectral/20260619-vca --source-index 2` (choose a new output directory if one exists), then `uv run python scripts/export_spectral_showcase.py`. After the browser build and local server, use system `python scripts/capture_spectral.py` and `python scripts/capture_agreement.py`; these opt-in scripts require Playwright and the recorded local satellite run. No synthetic inputs are substituted when it is absent.


| Queued spectral workflow — 2026-10-18 | Evidence |
| --- | --- |
| [37 — working spectral browser](37-queued-spectral-workbench.png) | Actual queued execution on the retained Sentinel-2 scene, saved fit parameters, exact cell inspection and component maps/loadings; [browser assertions](37-spectral-job-browser-evidence.json), [saved request](37-saved-spectral-request.json) |
| [38 — printable project report](38-spectral-project-report.png) | Computed report with parent acquisition recipe/coverage, source spectra, fit/implementation metadata, limitations and artifact hashes |
| [39 — spectral workbench mobile](39-spectral-workbench-mobile.png) | Actual execution/result workspace at 390 px width |
| [40 — shared terminal job](40-terminal-spectral-job.svg) | The same browser job in the TUI; [separate CLI/Python numerical parity](40-spectral-interface-parity.json) |
| [41 — spectral process recovery](41-spectral-process-recovery.json) | Actual SIGKILL at an export checkpoint, private incomplete output, same job/result ID recovered as attempt 2 on the pinned satellite stack |

Opt-in reproduction: start `uv run rslib serve --port 8769 --data data`, run system `python scripts/capture_spectral_jobs.py` with Playwright, then `uv run python scripts/export_spectral_job_tui.py`. Run `uv run python scripts/check_spectral_recovery.py` separately; it creates and cleans up its own isolated server and preserves a scratch data directory. The recovery harness introduces a checkpoint delay only, not synthetic raster values. The local satellite run is required; there is no silent synthetic fallback.

| Reference coverage | Evidence |
| --- | --- |
| [42 — reference case viewer](reference-cases.html) | Six actual-satellite sites; acquisition RGB/false color, retained QA, source/daily/saved-query support and explicit unscored comparisons; [audit JSON](42-reference-case-audit.json) |
| [43 — reference browser capture](43-reference-case-browser.png) | Actual interactive viewer; selection and image-loading checks recorded separately |
| [44 — documentation site](44-documentation-site.png) | Actual local preview of the generated GitHub Pages documentation |
