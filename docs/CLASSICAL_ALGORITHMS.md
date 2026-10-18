# Classical remote-sensing algorithms

Classical processing is part of the analysis core. A new learned model must be compared with suitable spectral, temporal and physical baselines. The [reviewed inventory](research/INDEX.md) now includes explicit classical-method records alongside physical models, data products and learned methods. **A reviewed candidate is not an installed operation.** The implemented spectral workflow now runs through the shared durable queue in the browser, TUI, CLI and Python.

## Implemented spectral operations

`rslib.spectral` uses a final band axis (`height, width, bands` or `samples, bands`), named bands and physical reflectance. Missing or masked samples remain missing in every output. Fit operations reject empty/degenerate training data. Arrays are bounded; tile large datasets. No function changes the acquisition's cloud mask.

| Operation | Implemented behavior | Limits |
| --- | --- | --- |
| `fit_pca` / `PCABasis.transform` | Centered covariance eigendecomposition; explicit loadings, mean, eigenvalues and retained variance; reuse the same fitted basis on subsequent observations | No automatic standardization, whitening or MNF. Equal eigenvalues can permit different valid rotations. A transform fitted on evaluation data leaks information into a downstream evaluation |
| `vca` | Independent implementation of Nascimento and Bioucas-Dias (2005), Algorithm 1; affine and projective branches; seeded random directions, source-cell indices, projected and observed spectra | Caller selects the branch; no invented SNR. Requires linear mixing and pure-pixel assumptions. Rejects degeneracy, duplicate extremes and unresolved projective denominators. No automatic material labels |
| `fcls` | Unweighted nonnegative, sum-to-one least squares; exact simplex-face enumeration, chunked application and convex first-order optimality gap | 2–8 endmembers; face count grows exponentially. Affinely dependent or ill-conditioned libraries fail explicitly. Fractions are conditional on the library, not validated ground composition |
| `tasseled_cap` | Baig 2014 Landsat-8 OLI TOA brightness/greenness/wetness; exact sensor, band-order and radiometry checks | Deliberately rejects the existing SR workflow, Landsat-9, TM/ETM+ and Sentinel-2. The SR profiles identified below remain unintegrated until their original coefficient tables are verified |
| `bcy_sentinel_candidates` | Sentinel Hub's simple Sentinel-2 BCY adaptation; explicit SWIR threshold; unknown / not detected / candidate labels | Native L1C TOA inputs only; no shadow processing. “Not detected” does not certify clear sky. Not enabled as the stack's QA policy |

PCA is available in [Spectral Python](https://www.spectralpython.net/algorithms.html); [Orfeo ToolBox](https://www.orfeo-toolbox.org/CookBook/Applications/app_VertexComponentAnalysis.html) also provides VCA; [PySptools](https://pysptools.sourceforge.io/) supplies numerous unmixing, detection and spectral routines. These algorithms are established methods. RSLIB's contribution here is a bounded observed-data workflow with source tracking, explicit calibration requirements and numerical checks. Cross-implementation validation on public real hyperspectral benchmarks remains necessary.

## Run an observed-scene analysis

```bash
# Select one source from a completed optical run's observation inventory.
uv run rslib spectral-analysis data/runs/RUN_ID data/spectral/my-analysis \
  --source-index 2 --endmembers 3 --seed 0
```

This verifies `stack.npz` against the published run manifest, selects only complete native-QA-valid spectra inside the AOI, fits one source acquisition and writes `pca.tif`, `abundance.tif`, `reconstruction-rmse.tif`, previews, `report.html`, `request.json`, `report.json` and `bundle.zip` into a new directory. Partial exports are staged until all products are ready. Existing result directories are not overwritten. The source run stays unchanged. The report contains the input SHA256, exact source, grid, fitted coefficients, selected observed spectra/cells, solver certificate and output SHA256. The COGs retain CRS, affine transform, nodata, band descriptions and source/hash tags. Open **Analyze observed spectra** from a completed optical run, or `/spectral.html?run=RUN_ID`, to execute the same fit through a durable job. In the TUI, press `x`, load a run inventory and choose the source/settings. The earlier standalone browser figure remains a saved showcase.

```python
from rslib.spectral import fit_pca, vca, fcls

bands = ("blue", "green", "red", "nir", "swir16", "swir22")
# cube: Y,X,B physical reflectance; valid: Y,X boolean acquisition QA + AOI
basis = fit_pca(cube, bands=bands, valid=valid, components=3)
scores = basis.transform(cube, bands=bands, valid=valid)
next_scores = basis.transform(next_cube, bands=bands, valid=next_valid)
vertices = vca(cube, bands=bands, valid=valid, endmembers=3,
               projection="affine", seed=0)
mixture = fcls(cube, vertices.endmembers, bands=bands,
               endmember_bands=bands, valid=valid)
```

The first satellite example uses `S2B_T23KNR_20260619T131449_L2A`, **4,897** complete cells on the saved 30 m EPSG:32723 common grid. FCLS median reflectance RMSE is **0.002821**, P95 **0.008445**. The maximum convex optimality gap is **1.42 × 10⁻¹⁶ reflectance²**. These are in-scene reconstruction and optimization diagnostics, not material-fraction accuracy. The [report](showcase/35-live-spectral-report.json), [interactive figure](showcase/spectral.html) and [capture](showcase/35-live-spectral-analysis.png) retain the distinction. No temporal interpolation or generated imagery is used. The PCA component setting controls the separately exported PCA scores; VCA computes its own p−1/p dimensional projection from the endmember count, following its selected branch. The source is already the run's prepared, partially bandpass-adjusted product; it is not a fresh native-grid hyperspectral validation dataset.

## BCY: preserve the original method and its adaptation

The original authors are **Braaten, Cohen and Yang**. Their [2015 paper and MSScvm implementation](https://github.com/jdbcode/MSScvm) target four-band Landsat MSS, including cloud-shadow processing and terrain inputs. The [Sentinel Hub adaptation](https://custom-scripts.sentinel-hub.com/custom-scripts/sentinel-2/cby_cloud_detection/) is a short spectral decision rule, not a port of that full workflow. Its executable example uses `B11 > 0.1`; the discussion proposes `B11 > 0.2`. RSLIB requires the caller to choose the threshold and does not transplant it onto bandpass-adjusted L2 surface reflectance.

The implemented decision is `swir > threshold AND ((green > 0.175 AND green > red) OR green > 0.39)`. Tests cover strict threshold boundaries, missing data and the different SWIR choices. Thin/cirrus clouds and snow remain known limitations. The next integration gate is an independent cloud/shadow benchmark stratified by bright surfaces, snow, thin cloud, terrain and cloud-edge distance, with omission and commission reported separately. Native SCL/QA_PIXEL remains the default.

## Tasseled cap: coefficients are part of the input contract

[Baig et al. 2014](https://doi.org/10.1080/2150704X.2014.915434) derived Landsat-8 OLI **at-satellite reflectance** coefficients. The included first three components were cross-checked against **Table B1** of [NASA DEVELOP technical report 20220005937](https://ntrs.nasa.gov/citations/20220005937). They are not silently accepted on SR or other sensors. “Wetness” is a transform component, not volumetric water content.

The review also identified [Zhai et al. 2022](https://doi.org/10.1016/j.rse.2022.112992), which supplies separate OLI TOA/SR and five-/six-band profiles, and [Wang et al. 2026](https://doi.org/10.1016/j.srs.2025.100353), which addresses harmonized Landsat-8/9 SR coefficients. Their full original coefficient tables have not been verified in this checkout; no guessed profiles are shipped. Sensor identity, processing level, blue-band inclusion and exact coefficient reference belong in every future profile and output report.

## Reuse and next implementations

[TorchGeo's stable 0.10.1 transform documentation](https://docs.torchgeo.org/en/stable/api/transforms.html) provides many spectral indices and EO augmentations. Its `RandomGrayscale` discussion permits user-supplied PCA weights; that does not fit a PCA basis. The inspected transform page does not document fitted tasseled cap or VCA. [Model documentation](https://docs.torchgeo.org/en/stable/api/models.html) includes Presto, Tessera, DOFA, Copernicus-FM and other integrations. Prefer a typed converter to supported TorchGeo interfaces over duplicating a model loader. Check exact band order, mask meaning, dates, location, scaling and checkpoint terms first. This inspection does not claim that these classical algorithms are absent from all other libraries.

Remaining classical candidates have concrete acceptance requirements:

- MNF/noise-adjusted PCA needs a measured or defensible noise covariance, regularization and correlated-noise tests. Spatial gradients are not automatically sensor noise.
- PPI/FIPPI, N-FINDR, ATGP and endmember-count estimation need pure-pixel/noise tests, initialization sensitivity and comparison on public imaging-spectrometer references.
- SAM/SID, RX, matched filters and ACE need response-matched reference spectra, controlled background covariance and target-absent false-alarm tests.
- Continuum removal and absorption features need wavelengths, bandwidths, atmospheric/bad-band masks and reference spectra; six broad bands cannot replace an imaging spectrometer.
- Haralick textures need nodata-aware windows, declared quantization, direction and spatial support; a texture value cannot transfer across arbitrary resolutions unchanged.
- MAD/IR-MAD need registration controls, paired masks and conditioned covariance. Long-history LandTrendr/COLD/CCDC methods need enough dates and explicit disturbance evaluation.
- Whittaker, Savitzky–Golay, HANTS, LOESS and state-space smoothing need actual dates, QA weights, withheld observations, edge/gap policies and change-retention tests. Estimated values must retain their status.

The wider [quantitative review](REMOTE_SENSING_RESEARCH.md) connects these operations to radiative transfer, biophysical retrieval, thermal energy balance, radar, water, snow, soil and uncertainty. New methods should enter the same provenance and evaluation path.


## Shared spectral jobs — 2026-10-18

Spectral submissions use `POST /api/jobs` with `kind: "spectral"` and a `spectral` object containing `run_id`, `source_index`, `components`, `endmembers`, `projection` and `seed`. The server pins both source stack and manifest SHA256 at submission. A saved request also contains those expected input hashes; an input change fails explicitly. `GET /api/jobs?source_run_id=RUN_ID` reopens this run's analyses without mixing them into its optical-run history.

A succeeded job's result lives under `data/analyses/ANALYSIS_ID`. Its `manifest_url` points to `/api/analyses/ANALYSIS_ID/report.json`. This is a spectral report, not an optical stack manifest. The browser/TUI inspect all saved component maps, loadings, source endmembers, exact cells, fractions and residuals. Data-missing cells retain missing values; they do not become zero abundance. API cell responses use physical values from the pinned input and COGs, not the stretched preview colors.

The printable report includes the parent acquisition recipe and temporal support, source/product/calibration metadata, selected spectra, fitted coefficients, limitations and artifact checksums. It records Python/NumPy/Rasterio/GDAL/RSLIB versions and implementation source hashes. Replaying a request uses the installed implementation; compare that record across environments rather than assuming bitwise cross-version reproduction. The bundle contains the report and analysis artifacts; it references the parent input by checksum and does not duplicate that source cube.

```bash
uv run rslib jobs submit --spec request.json --data data
# Keep a server or TUI running against that data directory to execute the queue.
```

Cancellation is cooperative at fit/export checkpoints and every 4,096 FCLS cells. An interrupted fit restarts on the pinned prepared input; it does not resume an eigendecomposition internally. Atomic publication keeps partial results private. The source run is not modified. See [job semantics](JOBS.md), [working browser capture](showcase/37-queued-spectral-workbench.png), [printable report](showcase/38-spectral-project-report.png), [same-job TUI/parity evidence](showcase/40-spectral-interface-parity.json) and [actual process-kill recovery](showcase/41-spectral-process-recovery.json).
