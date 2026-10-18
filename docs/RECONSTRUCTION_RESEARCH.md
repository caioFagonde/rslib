# Reconstruction and consumer-hardware super-resolution

Survey checked 2026-10-16 against papers, author repositories and model cards. A paper's benchmark result is not evidence of superiority on our regions, sensors or hardware. Public research code is different from a supported library API. Absence from this survey cannot establish absence from every library.

## Implemented and measured here

`rslib.superresolution` wraps the installed **ESAOpenSR SEN2SRLite RGBN ×4** architecture. It loads two pinned, SHA-256-verified safetensors files; it does not execute a downloaded model loader. Input is calibrated Sentinel-2 L2A **B04/B03/B02/B08**, native 10 m, with cloud QA already applied. Output has 2.5 m grid spacing, retained georeferencing and expanded nodata. There is no claim of independently observed 2.5 m detail. The upstream model and training domain are described in [SEN2SR](https://github.com/ESAOpenSR/SEN2SR) and its [pinned model metadata](https://huggingface.co/tacofoundation/SEN2SR/blob/469e9b3a049f9320ba66b3a39b9655dbd31480b3/SEN2SRLite/NonReference_RGBN_x4/mlm.json).

Measured on the local **NVIDIA RTX 3050 6 GB Laptop GPU**, using actual Sentinel-2 Collection 1 imagery near Itatiaia, Brazil:

| Setting | Observed result |
| --- | --- |
| Input / output | 4 × 128 × 128 → 4 × 512 × 512 |
| Execution | Batch 1; 128-pixel tiles, 16-pixel halo; FP16 convolutions, FP32 Fourier correction |
| Three warmed runs | 0.0769, 0.0837, 0.0745 seconds |
| Median warmed inference | **0.0769 seconds** including transfers and tile assembly |
| Peak Torch allocation / reservation | **102.5 / 136 MiB** |
| Scope | Acquisition, loading, warm-up, export, driver/CUDA context and other processes excluded |
| Accuracy | No high-resolution reference in this example; not measured |

The CLI's separate first inference was about 0.91 seconds, illustrating why the warm measurement is not an end-to-end latency promise. Small patches and one GPU are not a full-scene throughput benchmark. The actual [comparison figure](showcase/09-superresolution.png) and [evidence JSON](showcase/09-superresolution-evidence.json) retain the source, grid, weights, timings and diagnostic box-average residuals. Box averaging is not a calibrated sensor point-spread function.

```bash
# Install a suitable PyTorch build for the platform before GPU use if necessary.
uv sync --extra sr
uv run rslib sr-fetch
# Four-band, cloud-masked, physical-reflectance GeoTIFF, native metric 10 m grid.
uv run rslib superresolve input-rgbn.tif --device cuda --precision float16 \
  --output data/superresolution/output.tif
# CPU path is available; its speed is not benchmarked here.
uv run rslib superresolve input-rgbn.tif --device cpu --precision float32

# Reproduce the real-data showcase; explicit public acquisition/weight download.
uv run --extra sr --with matplotlib python scripts/showcase_superresolution.py
```

SEN2SR's Fourier constraint is global within each model tile. Halo stitching reduces edge effects but does not prove exact full-image consistency. Zero-filled cloud context can affect neighboring clear outputs. Model-derived pixels retain a separate interpretation from observed reflectance; use a matched sensor forward model and high-resolution references before quantitative downstream use.

## Models to evaluate next

| Method | Why it is useful | Availability and integration status |
| --- | --- | --- |
| [SEN2SR full / 20 m band variants](https://github.com/ESAOpenSR/SEN2SR) | Efficient EO-specific SR; reference-guided red-edge/SWIR refinement is more relevant than an RGB-only enhancement | Public package/checkpoints. Full version requires Mamba/CUDA tooling. Only Lite RGBN ×4 is integrated and measured here. |
| [LDSR-S2 / OpenSR](https://github.com/ESAOpenSR/opensr-model) | EO latent diffusion with spectral consistency; current upstream development includes short DPM-Solver++ sampling and back-projection | Public package/checkpoints. Candidate optional quality mode; no local VRAM/speed/accuracy claim until benchmarked. |
| [SwinIR light](https://github.com/JingyunLiang/SwinIR) | Established lightweight transformer reference for generic image SR | Public code/weights. RGB baseline; not a sensor-specific multispectral model. Not integrated. |
| [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) | Practical RGB perceptual display baseline, tiled/Vulkan deployment options | Public code/weights. Presentation use requires separate evaluation from reflectance science. Not integrated. |
| [OpenSR-test](https://github.com/ESAOpenSR/opensr-test) | Real-world EO evaluation of consistency and model-created detail | Public benchmark package. Use alongside matched-reference tests rather than ranking by sharpness alone. Not yet wired into CI. |

## Advanced cloud removal and temporal reconstruction

These are research candidates, not installed adapters. Their published evaluations use different datasets, normalizations and tasks; their scores should not be combined into one leaderboard.

| Method | Relevant algorithm | What is actually available |
| --- | --- | --- |
| [UnCRtainTS](https://github.com/PatrickTUM/UnCRtainTS) | Multitemporal attention with multivariate predictive uncertainty | Author code exists. Check training radiometry carefully: SEN12MS-CR time-series preprocessing is not interchangeable with our L2A calibrated inputs. |
| [EMRDM, CVPR 2025](https://github.com/Ly403/EMRDM) | Mean-reverting diffusion restoration and efficient sampling | Official implementation exists; a possible diffusion baseline. |
| [RESTORE-DiT, RSE 2025](https://github.com/SQD1/RESTORE-DiT) | Multimodal sequential diffusion transformer reconstructing optical sequences with SAR context | Author code exists; requires a correctly prepared SAR/optical temporal dataset. |
| [AnytimeFormer, RSE 2026](https://github.com/tangkai-RS/AnytimeFormer) | Irregular, asynchronous SAR/optical fusion with queries at arbitrary times | Author code exists. Dependency modernization and training-domain evaluation remain integration work. |
| [SADER, 2026 preprint](https://arxiv.org/abs/2602.00536) | Cloud-aware structure conditioning and deterministic diffusion resampling | [Author code](https://github.com/zyfzs0/SADER) exists. Research candidate, not a universal performance guarantee. |
| [AGFlow, CVPR 2026 MORSE](https://openaccess.thecvf.com/content/CVPR2026W/MORSE/html/Fallah_Asynchronous_Remote_Sensing_Time-Series_Fusion_for_Cloud_Removal_and_Anytime_CVPRW_2026_paper.html) | Timestamp-conditioned spatiotemporal flow matching for asynchronous fusion, full-frame gaps and anytime reconstruction | [Project repository](https://github.com/AGFlow-model/AGFlow-model) claims release, but its inspected default-branch tree contained only README and LICENSE; the README's linked `AGFlow` repository returned 404 and checkpoint link was a placeholder. Treat executable availability as **unverified**, not proof no implementation exists. |
| [GeoCR, September 2026 preprint](https://arxiv.org/abs/2609.32510) | Generalist latent flow prior across RGB/multispectral, single/multiple dates and optional SAR; LoRA adaptation | [Official code](https://github.com/KAIST-VICLab/GeoCR) and [weights](https://huggingface.co/JeonghyeokDo/GeoCR) exist. Model card references a 4B base and mixed licenses. Not a measured 6 GB default; quantization/offload viability needs testing. |

The [AllClear dataset/benchmark](https://allclear.cs.cornell.edu/) is a useful evaluation starting point for cloud reconstruction. Real cloud-free references, geographic and temporal holdouts, and observed-pixel preservation matter more than attractive synthetic masks alone.

## Where RSLIB can contribute beyond another model wrapper

The following are **proposed integration/research directions**, not claims of algorithmic novelty or completed, validated methods:

1. **Joint cloud reconstruction and SR under the sensor forward model.** Estimate latent high-resolution reflectance while enforcing each available sensor's band response, PSF, sampling grid and observed clear pixels. Carry an ensemble of plausible outputs rather than only a sharp image. Existing spectral constraints mean consistency itself is not new.
2. **Change-aware temporal support.** Gate temporal borrowing using independent disturbance evidence and SAR/optical disagreement. Avoid reconstructing a harvested field or landslide from a visually similar pre-event date. Abstain when evidence conflicts.
3. **Task-level uncertainty.** Propagate reconstruction alternatives through NDVI/biophysical regression, SOC stock models and independently parameterized hydrology. Keep measurement, reconstruction and model-parameter uncertainty identifiable. Soil reflectance is not a direct cohesion/friction measurement.
4. **Acquisition by expected information gain.** Rank extra STAC observations by how much they are expected to reduce a particular decision's uncertainty per downloaded byte and GPU-second. The current geometric/cloud-cover planner is only a baseline.
5. **Budget-aware execution.** Select tile size, precision, model and sample count against measured hardware limits, with reproducible accuracy/latency/memory curves. Deploy the smallest model that passes the intended scientific acceptance tests.

I did not find a single supported library in the surveyed sources exposing this entire workflow with one auditable contract. That is a practical product gap to investigate; it is not evidence that no research group has implemented any component.

## Contracts already in the core

- `compositing.composite`: quality or L1 spectral-medoid selection of a complete observed spectrum, source index, eligible count, missing-data semantics and work budgets.
- `timeseries.interpolate_gaps`: actual irregular datetime spacing, maximum whole-bracket gap, no extrapolation, retained observed values, per-sample support labels and source brackets. A baseline, not learned cloud removal.
- `reconstruction.preserve_observations`: merge supplied model predictions while preserving complete clear spectra; separate unsupported/observed/model-derived labels and optional model standard deviations. This contract does not supply a pretrained inpainting model or establish uncertainty calibration.
- `deep.predict_tiles`: declared integer scale, halo trimming, nodata restoration, output budgets, shape checks and optional CUDA autocast.
- `superresolution`: verified SEN2SRLite loading, reproducible band/unit/grid contract, native-grid CLI COG export and provenance.

Before a cloud-removal adapter becomes operational: reproduce its reference results, verify preprocessing/band order/licensing, benchmark the consumer GPU, test observed-pixel invariance, evaluate masked-area radiometry/SAM and temporal change retention, and assess uncertainty on spatially and temporally independent data. For SR, include observed-resolution consistency, sensor PSF/MTF, cross-band indices and held-out high-resolution references. Carbon and hazard applications require their own field validation.
