# Quantitative remote-sensing methods and open-model review

Checked **2026-10-17** against primary author repositories, model cards, agency algorithm pages and the publisher's book contents. The [reviewed inventory](research/INDEX.md) has **98 entries across 46 overlapping method/application domains**. [Machine-readable records](research/methods.json) retain input contracts, targets/units, artifact availability, code-versus-weight licensing, hardware evidence and evaluation requirements. A [source snapshot](research/source-snapshot.json) records 53 repository metadata responses and nine model cards, including checkpoint revisions and file lists. No model weights were downloaded or executed for this survey.

This is a broad selection across the main sensing modalities and applications, rather than an exhaustive inventory or a cross-task leaderboard. Some entries are established reference algorithms needed to assess recent learned systems. Claims in author benchmark tables remain claims on those datasets; this review does not establish a universal best model or absence from every existing library. RSLIB integration status is separate from source availability. The browsable inventory is available at **`/showcase/research.html`** after a browser build.

Classical spectral and image processing now has its own [implementation and review guide](CLASSICAL_ALGORITHMS.md): BCY/MSScvm versus the Sentinel-2 adaptation, sensor/radiometry-specific tasseled cap, PCA/MNF, VCA/FCLS, spectral detectors, texture and statistical change. The inventory includes 28 explicit classical-method records. PCA, VCA and FCLS run on a verified observed acquisition; the BCY and OLI TOA tasseled-cap primitives enforce their separate calibration requirements.

## Advanced Remote Sensing

The identified book is **Advanced Remote Sensing: Terrestrial Information Extraction and Applications**, second edition, by **Shunlin Liang and Jindi Wang**, Academic Press, published in November 2019. The [publisher's public record and contents](https://shop.elsevier.com/books/advanced-remote-sensing/liang/978-0-12-815826-5) were inspected; the full copyrighted text was not reviewed. Its quantitative scope is useful for organizing the library. Recent implementation choices also require the original method papers, current algorithm theoretical basis documents (ATBDs) and actual reference data.

| Publisher chapter group | Library requirement |
| --- | --- |
| 2–5: geometry, temporal processing, fusion, atmosphere | Physical sensor/grid metadata, image registration, native QA, calibrated reflectance and explicit forward/resampling operators |
| 6–9: solar/thermal radiation and albedo | Angular reflectance, irradiance and thermal quantities retain different units and observation models |
| 10–16: vegetation chemistry, structure and productivity | Retrieve declared biophysical parameters with identifiable models and independent targets |
| 17–21: precipitation, ET, soil moisture, snow and water storage | Distinguish surface/root-zone state, flux versus stock, footprint support and temporal aggregation |
| 22–24: product integration, data management and change | Assimilate evidence with uncertainty, retain provenance, and evaluate change against independent events |

The operational implication is a measurement-to-retrieval chain. An embedding, an index, a physical parameter and an observed flux should occupy distinct product types.

## Quantitative contract

Represent an observation as `y = H(x, sensor response, geometry, atmosphere) + error`. The desired state `x` might include LAI, canopy water, surface temperature or soil moisture. Inversion needs assumptions about `H`, observation errors and parameter priors. A fitted empirical mapping is also a retrieval model and needs independent targets. For a derived quantity, a first-order covariance calculation `Σ_out ≈ J Σ_in Jᵀ` requires the relevant cross-variable covariances; independent marginal quantiles are insufficient.

Every quantitative operation should declare:

1. Input product level, radiometric convention, physical units, spectral response/band order, spatial footprint/PSF, geometry, time and valid-data masks.
2. Estimated variable and units, training/reference population or physical model, parameter priors and admissible input domain.
3. Observation, retrieval and model-parameter uncertainty separately, including covariance assumptions and spatial/temporal dependence.
4. Source identity, software/model version, immutable artifact hashes, processing history and measured or inferred support for each output.
5. A target-specific independent validation design, declared tolerances and behavior when inputs are missing, outside the training domain or insufficient for identification.

[CEOS LPV](https://lpvs.gsfc.nasa.gov/) has target-specific validation guidance. Its [vegetation-index group](https://lpvs.gsfc.nasa.gov/NDVI/NDVI_home.html) explicitly distinguishes index-unit uncertainty, sensitivity to actual vegetation conditions and long-term stability. Its [ET guidance](https://lpvs.gsfc.nasa.gov/ET/ET_home.html) points to flux-tower validation. These are stronger acceptance requirements than visual agreement or a model name.

## Recent learned models worth evaluating

The table separates promising inputs/interfaces from actual local acceptance. Most are **not integrated**. Exact checkpoint revisions and license fields are in the source snapshot. A published parameter count or checkpoint size is not a measured inference-memory requirement.

| Candidate | Useful property for RSLIB | Release and deployment evidence | Main gate |
| --- | --- | --- | --- |
| [TESSERA v2 students](https://github.com/ucam-eo/tessera/blob/master/tessera_infer_v2/README.md) | Pixel-wise time-series features with compact student variants and truncated embedding dimensions | Author documents Nano/Small/Medium/Large students at 1.07/7.11/21.03/43.83M parameters; Medium checkpoint about 84 MB. Nano and Medium cards inspected, CC0-1.0; repository MIT. Local throughput unmeasured | Exact S2 band order, cloud masks/day-of-year, optional S1 orbits and preprocessing; independent task heads and missing-modality tests |
| [Galileo](https://github.com/nasaharvest/galileo) | Global/local multimodal features; small variants for frozen-feature workflows | Nano/Small/Base files in the inspected MIT model card; no local consumer benchmark | Verify normalization, dates and missing modalities; compare simple supervised baselines |
| [Presto](https://github.com/nasaharvest/presto) | Lightweight temporal features for crop/land-use work | Author code and pretrained loading path; local resources not measured | Crop/region/season splits and actual input contract rather than fabricated auxiliary values |
| [TerraMind 1.0 Tiny](https://github.com/IBM/terramind) | Optical/SAR/DEM fusion and adapted maps; generation available as a separate task | Tiny checkpoint metadata verified; Apache-2.0 card and code | Separate observed data from generated modalities; reproduce task-head preprocessing and benchmark |
| [Prithvi-EO 2.0 300M-TL](https://huggingface.co/ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL) | HLS/time/location-aware features and existing crop/flood/burn workflows | Checkpoint metadata Apache-2.0; code-repository metadata MIT | HLS-compatible input/temporal contracts, task-head validation and measured activation memory |
| [AnySat](https://github.com/gastruc/AnySat) / [UniverSat](https://github.com/gastruc/UniverSat) | Native scale/modality diversity and explicit physical patch extents | UniverSat Base checkpoint verified under MIT; author describes about 201M parameters. Tiny is a training configuration, not a released pretrained Tiny checkpoint | Sensor-specific radiometry, physical extents and token budget; unseen-sensor evaluation |
| [Copernicus-FM](https://github.com/zhu-xlab/Copernicus-FM) / [DOFA](https://github.com/zhu-xlab/DOFA) | Wavelength/variable-aware representations | Copernicus-FM checkpoint card CC-BY-4.0; referenced code directory Apache-2.0/MIT. DOFA code MIT; weight terms need their own review | Bandwidth/response transfer, auxiliary variable embeddings and independent sensor splits |
| [OlmoEarth v1.2](https://github.com/allenai/olmoearth_pretrain) | Small temporal multimodal variants and published evaluation infrastructure | Nano metadata verified; custom OlmoEarth Artifact License, including field-of-use restrictions | Confirm the intended use fits the actual license and preserve checkpoint input conventions |
| [SpectralEarth](https://github.com/AABNassim/spectral_earth) / [HyperSIGMA](https://github.com/WHU-Sigma/HyperSIGMA) | Imaging-spectrometer representations and hyperspectral tasks | Author code/checkpoint links. SpectralEarth license not identified in inspected metadata; HyperSIGMA code Apache-2.0, checkpoint terms separately unverified | Wavelength/bad-band transfer, spectral fidelity, target references and memory |
| [SatlasPretrain](https://github.com/allenai/satlaspretrain_models), [RemoteCLIP](https://github.com/ChenDelong1999/RemoteCLIP), [SamGeo](https://github.com/opengeos/segment-geospatial) | Infrastructure mapping, semantic search and assisted boundaries | Public implementations; each pretrained backbone retains its own artifact/data terms | Object/boundary labels and GSD transfer; semantic scores do not establish physical-unit estimates |

Other reviewed candidates include [SMARTIES](https://github.com/gsumbul/SMARTIES), [THOR](https://github.com/FM4CS/THOR) and [DINOv3](https://github.com/facebookresearch/dinov3). They need equivalent-task comparisons and checkpoint-specific access/license checks before integration. Large satellite variants are not assumed to fit a 6 GB GPU.

Two important release distinctions: [SkySense++](https://github.com/kang-wu/SkySensePlusPlus) limits its pretrained weights/pretraining code to non-commercial research. [AlphaEarth's primary announcement](https://deepmind.google/blog/alphaearth-foundations-helps-map-our-planet-in-unprecedented-detail/) releases annual embedding data; this review did not verify a local inference checkpoint. Neither should be silently described as an unrestricted bundled model.

## Physical and operational methods across application branches

The inventory provides the longer input/acceptance contracts. These are the principal model families to support or compare against; established methods remain useful even when recent learned models are evaluated.

| Branch / output | Physical or operational approach and open implementation | Quantitative validation needed |
| --- | --- | --- |
| Geometry and sensor agreement | [AROSICS](https://github.com/GFZ/arosics), physical band-response integration, [HLS NBAR/bandpass chain](https://hls.gsfc.nasa.gov/algorithms/) | Stable-area tie points, residual offsets, angular/atmospheric stratification and independently calibrated measurements |
| Atmosphere and radiometry | [Py6S/6S](https://github.com/robintw/Py6S), [Eradiate](https://github.com/eradiate/eradiate), [ISOFIT](https://github.com/isofit/isofit), [libRadtran](https://www.libradtran.org/) | Radiative closure, aerosol/adjacency assumptions, sensor response and atmospheric uncertainty; optional solver licenses remain distinct |
| Temporal preparation | Quality/medoid compositing, robust smoothing, state-space models, constrained interpolation, [COLD/S-CCD](https://github.com/GERSL/pycold) | Real date/event holdouts, temporal consistency, change retention, abstention and observational support |
| Spatial/temporal fusion | STARFM/ESTARFM/FSDAF families, [cuFSDAF](https://github.com/HPSCIL/cuFSDAF), uncertainty-aware fusion | Withheld fine observations, matched coarse sensor response, spatial edges and abrupt changes |
| Cloud masks/reconstruction | [CloudSEN12](https://github.com/cloudsen12/models), [s2cloudless](https://github.com/sentinel-hub/sentinel2-cloud-detector), UnCRtainTS/EMRDM/AnytimeFormer | Independent real clouds, cloud-shadow omissions, observed-pixel preservation, spectral errors and calibrated uncertainty |
| Super-resolution | [SEN2SR](https://github.com/ESAOpenSR/SEN2SR), [OpenSR](https://github.com/ESAOpenSR/opensr-model) | Matched PSF/MTF and spectral response, observed-resolution consistency, held-out high-resolution references and model-created detail |
| LAI, pigments, leaf water | [PROSAIL](https://github.com/jgomezdans/prosail), physical LUT/GP/emulator inversions, learned biophysical retrievals | Parameter identifiability, priors, wavelength response and independent field targets |
| Fluorescence/photosynthesis/productivity | [SCOPE](https://github.com/Christiaanvandertol/SCOPE), fluorescence/radiation/energy coupling and separately validated learned emulators | SIF/radiance plus physiological/tower references; GPP is not directly observed by NDVI |
| Albedo/radiation | Ross-Li kernels, documented NBAR/albedo and radiative-transfer integration | Physical geometry, coefficient conditioning, irradiance convention and ground radiation networks |
| Temperature/thermal sharpening | Documented Landsat/ECOSTRESS thermal products, split-window/TES families and [pyDMS](https://github.com/hectornieto/pyDMS) | Emissivity/atmosphere error, thermal-footprint conservation, field radiometry and independent fine-scale references |
| ET and crop water use | [pyTSEB](https://github.com/hectornieto/pyTSEB), [pyWaPOR/ETLook](https://github.com/DHI-GRAS/pywapor), energy/water balance | Flux towers, energy-closure convention, daily integration and meteorological/roughness uncertainty |
| Radar backscatter and soil moisture | [pyroSAR](https://github.com/johntruckenbrodt/pyroSAR), calibrated terrain-flattened SAR, physical microwave retrievals | Incidence/terrain/layover effects, roughness/vegetation confounding and calibrated moisture references |
| Passive-microwave soil moisture | [SMAP tau-omega model family](https://smap.jpl.nasa.gov/system/internal_resources/details/original/316_L2_SM_P_ATBD_v7_Sep2015.pdf), current documented products and assimilation | Footprint-matched networks, sensing depth, temperature/vegetation uncertainty and CEOS soil-moisture guidance |
| InSAR, subsidence and geohazards | [ISCE3](https://github.com/isce-framework/isce3), [MintPy](https://github.com/insarlab/MintPy), coherent time-series inversion | GNSS, interferogram closure, atmospheric delay, unwrapping failures and line-of-sight/reference conventions |
| Forest height/biomass | [Lang canopy-height model](https://github.com/langnico/global-canopy-height-model), GEDI/lidar calibration, BioMassters baselines and [BIOMASS suite](https://github.com/BioPAL/BPS) | Plot/lidar references, biome transfer, high-biomass saturation, allometry and footprint/date mismatch |
| Soil properties and carbon | [SoilGrids](https://docs.isric.org/globaldata/soilgrids/), local spectroscopy/regression, pedotransfer and equivalent-soil-mass comparisons | Independent profiles, depth/bulk-density/coarse-fragment uncertainty, spatial dependence and stock versus flux distinction |
| Ocean/inland-water color | [ACOLITE](https://github.com/acolite/acolite), SeaDAS/OCSSW, [C2RCC](https://seadas.gsfc.nasa.gov/help-9.0.0/c2rcc/C2RCCAlgorithmSpecification.html), QAA/OCx families | Water-leaving radiometry, in situ constituents, glint/adjacency and optically complex-water strata |
| Coasts/shoreline change | [CoastSat](https://github.com/kvos/CoastSat), tidal/datum correction and change analysis | Surveyed coastlines, geolocation, tides/runup and beach-slope uncertainty |
| Atmospheric composition and greenhouse gases | [SASKTRAN2](https://github.com/usask-arg/sasktran2), optimal-estimation retrievals, [mag1c](https://github.com/markusfoote/mag1c) and [EMIT](https://github.com/nasa/EMIT-Data-Resources) products | Radiometric/background/transport uncertainty; methane enhancement alone does not establish an emission rate |
| Precipitation and hydrologic forcing | [GPROF-NN](https://github.com/simonpf/gprof_nn), microwave retrievals and gauge/radar merging | Independent gauges/radar, extremes, sensor/climate transfer and distribution calibration |
| Snow, ice and glaciers | [SMRT](https://github.com/smrt-model/smrt), [OGGM](https://github.com/OGGM/oggm), [PINNICLE](https://github.com/ISSMteam/PINNICLE), geodetic mass balance | Snow microstructure/SWE, velocity/thickness and constitutive/boundary uncertainty; snow fraction is not SWE |
| Terrain, lidar and 3D | [xDEM](https://github.com/GlacioHack/xdem), [PDAL](https://github.com/PDAL/PDAL), lidar return/footprint models | Vertical datum, stable terrain, point density/occlusion, spatial error covariance and survey controls |
| Water storage and catchments | [gravity-toolkit](https://github.com/tsutterley/gravity-toolkit), [NeuralHydrology](https://github.com/neuralhydrology/neuralhydrology), physical assimilation | GRACE leakage/corrections and basin-scale support, gauges, water balance and out-of-period/basin holdouts |
| Urban/infrastructure/disaster maps | Satlas, Open-CD, task-adapted Prithvi/TerraMind, object/segmentation baselines | Object-level and area errors, event/geographic transfer, damage labels and image registration |
| Ecology/biodiversity | [DeepForest](https://github.com/weecology/DeepForest), canopy/trait retrievals and local ecological models | Independent species/crown/trait references; imagery-derived habitat is a proxy whose ecological relation must be validated |
| Earth-system context | [Prithvi-WxC](https://github.com/NASA-IMPACT/Prithvi-WxC), [Aurora](https://github.com/microsoft/aurora), physical/data-assimilated forecasts | Supported variables/levels, independent initialization dates/lead times, physical-unit errors and resource budgets |
| Planetary imaging | [USGS ISIS](https://github.com/DOI-USGS/ISIS3), mission radiometry and SPICE-based geometry | Mission calibration, reference body/frame and control networks; Earth atmosphere/CRS assumptions do not apply |

Cross-cutting land-cover, agriculture, forestry, fire/flood, urban heat, water quality and ecological applications combine several rows. Disease/ecological exposure work additionally requires independently validated outcome data; a remotely sensed habitat or heat proxy is not an observed health outcome. Field-specific algorithm selection must account for that distinction.

## Consumer-hardware evaluation order

Start with a CPU baseline and a small frozen representation on the same spatial/temporal holdout. The first candidate set is **TESSERA students, Galileo Nano/Small and Presto**, followed by **TerraMind Tiny** when its input modalities are available. This is an integration-priority judgment based on documented model interfaces and sizes, not a measured accuracy or speed ranking.

Use batch-one/tiled inference with explicit token/halo budgets, record cold/warm latency, source preparation, peak RSS, GPU allocation/reservation and complete workflow time. A checkpoint's bytes are only part of its runtime footprint. Existing local SEN2SRLite measurements apply to that adapter and patch size; they cannot be transferred to another architecture.

Retain tree/linear models and physical LUT/emulator baselines. Fine-tuning a large model is justified only by an improvement on the intended held-out target, uncertainty or operational cost. Large diffusion restorers, generalist teachers and Earth-system models remain separate optional backends until measured.

## Evaluation infrastructure to reuse

[TorchGeo](https://github.com/microsoft/torchgeo) and [TerraTorch](https://github.com/torchgeo/terratorch) already provide geospatial learning and model integration. [PANGAEA](https://github.com/VMarsocci/pangaea-bench) covers multiple sensors, resolutions and applications, including change, agriculture, flood and biomass tasks. [CropHarvest](https://github.com/nasaharvest/cropharvest) supplies agricultural benchmarks. AllClear is relevant to real cloud reconstruction; OpenSR-test is relevant to SR consistency. These are starting points, with each dataset's original license/split/label limitations retained.

For RSLIB evaluation, separate fitting, model selection, uncertainty calibration and final testing by geography and time. Report withheld support and class/land-cover distributions. Reuse exact splits and inputs for baselines and learned models. Include failed/unscorable cases and do not count correlated pixels as independent experimental replicates. Target-specific tolerances must be declared before the final test set is inspected.

## Implementation delivered with this review

`rslib.agreement` now measures near-coincident Landsat OLI/Sentinel-2 MSI agreement on complete common clear spectra. Closest-time disjoint pairing prevents repeated use of one source across accepted pairs. Minimum clear overlap and maximum timestamp separation are explicit. The report retains skipped/unpaired scenes, per-band bias/MAE/RMSE/correlation, residual quantiles, spectral angle, NDVI disagreement, sampled-cell coordinates and input SHA256.

For recorded local affine transforms, it also reconstructs **before-local-bandpass** values on the same QA-masked/resampled cells and compares them with the current stack. It does not undo upstream HLS or native resampling. The working browser displays all-band metrics and an interactive per-band scatter; the API and CLI return the same report. Existing run artifacts remain immutable.

```bash
uv run rslib compare-sensors data/runs/RUN_ID --max-hours 48 \
  --min-cells 100 --output data/agreement.json
# GET /api/runs/RUN_ID/agreement?max_hours=48&min_cells=100
```

On the retained actual satellite stack, the June 18 Landsat 9 and June 19 Sentinel-2B acquisitions are **24.346 hours** apart, with **4,897 common clear cells**. NIR reflectance correlation is only **0.1860**, with RMSE **0.07466**; high NDVI correlation (**0.9789**) and a small spectral angle do not establish agreement in absolute reflectance. NDVI disagreement has **bias +0.01602** and **RMSE 0.03046**; median six-band spectral angle is **1.632°**. Local bandpass adjustment slightly reduced per-band RMSE in red/NIR/SWIR and slightly increased it in blue/green. This single pair cannot isolate sensor calibration error from real temporal, angular, atmosphere or registration differences. No acceptance threshold or universal improvement is inferred. [Exact input-bound report](showcase/30-live-sensor-agreement.json).

## Next implementation gates

1. **Geometry and complete harmonization.** Add stable-area registration diagnostics/correction, angular metadata and direct high-level HLS discovery/access. Preserve the current partial-harmonization label until the whole chain is supported and measured.
2. **Temporal reliability.** Evaluate cloud-shaped/long-gap/change-event holdouts, robust smoothing/state-space baselines and change-aware abstention. Preserve observed spectra and distinguish every estimate from an observation.
3. **Small optional features.** Implement versioned input/checkpoint manifests for one small temporal representation after the actual preprocessing is reproducible. No silent missing-band/meteorology fabrication or remote model-code execution.
4. **One physical retrieval.** Build a sensor-response-aware PROSAIL LUT/emulator/uncertainty workflow with independent LAI/leaf-water references, or ingest a documented thermal product and evaluate ET forcing. Each requires an application-specific target and acceptance data.
5. **SAR and quantitative extensions.** Establish calibrated/terrain-corrected backscatter and orbit/layover QA before SAR-optical fusion, moisture inversion or displacement applications. Keep soil, carbon, energy and hydrology models conditional on their necessary physical inputs.

The Rust TRIGRS-related engine remains the independently implemented public-equation research path requested for this project. Learned optical representations cannot substitute for measured or independently estimated cohesion, friction, depth, diffusivity and initial groundwater conditions.
