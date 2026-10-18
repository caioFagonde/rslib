"""Build the browsable research inventory from reviewed primary-source records.

Records describe candidates, not installed adapters. Repository and checkpoint
licenses remain separate, and linked weights differ from metadata-verified files.
"""

import json
from pathlib import Path

from research_classical import extend

ROOT = Path("docs/research")
SNAPSHOT = json.loads((ROOT / "source-snapshot.json").read_text())
REPOS = {r["requested_repository"]: r for r in SNAPSHOT["repositories"]}
MODELS = {m["requested_model"]: m for m in SNAPSHOT["models"]}
METHODS = []


def add(
    identifier,
    name,
    domain,
    kind,
    target,
    inputs,
    repository,
    gate,
    *,
    model=None,
    weights=None,
    license_note=None,
    hardware="CPU or small GPU candidate; not benchmarked here",
    priority="quantitative_extension",
    notes="",
    status="candidate",
):
    repo = REPOS.get(repository)
    source = (
        "https://github.com/" + repository if not repository.startswith("https://") else repository
    )
    if model:
        card = MODELS[model]
        if card.get("http_status") != 200:
            raise ValueError(f"Unverified model metadata: {model}")
        files = [
            f
            for f in card["files"]
            if f.endswith((".pt", ".pth", ".safetensor", ".safetensors", ".ckpt", ".bin"))
        ]
        if not files:
            raise ValueError(f"No checkpoint files in model metadata: {model}")
        checkpoint = {
            "url": "https://huggingface.co/" + model,
            "revision": card["revision"],
            "license": (card.get("card_data") or {}).get("license", "unverified"),
            "gated": card.get("gated"),
            "files": files,
        }
        availability = "checkpoint_metadata_verified"
    else:
        checkpoint = (
            {"url": weights, "license": "unverified separately from code"} if weights else None
        )
        availability = (
            "checkpoint_linked"
            if weights
            else "published_product_reference"
            if kind == "data_product"
            else "code_available"
            if repo or source.startswith("https://github.com/")
            else "method_or_product_reference"
        )
    code_license = repo.get("license_spdx") if repo else None
    if code_license in {None, "NOASSERTION"}:
        code_license = "Not identified by repository metadata; review primary terms"
    METHODS.append(
        {
            "id": identifier,
            "name": name,
            "domain": domain,
            "kind": kind,
            "target_and_units": target,
            "input_contract": inputs,
            "source": source,
            "availability": availability,
            "checkpoint": checkpoint,
            "code_license": code_license,
            "license_note": license_note
            or "Repository metadata is not a checkpoint or dataset license. Verify all applicable terms before integration.",
            "hardware": hardware,
            "priority": priority,
            "rslib_status": status,
            "evaluation_gate": gate,
            "notes": notes,
        }
    )


add(
    "tessera-v2",
    "TESSERA v2 students",
    "Multisensor representations",
    "learned_model",
    "Pixel embeddings; downstream labels or physical variables require a trained and validated head",
    "Time-ordered Sentinel-2 bands in the documented non-wavelength order, cloud masks and day-of-year; optional ascending/descending Sentinel-1 series",
    "ucam-eo/tessera",
    "Geographic/temporal holdouts, phenology and missing-modality tests; compare frozen features with simple spectral/time-series baselines",
    model="geotessera/TESSERA-V-2.0-2B-M",
    license_note="Repository MIT; the inspected Medium checkpoint card is CC0-1.0. Separate source-data terms still apply.",
    priority="daily_workflow",
    notes="Author inference documentation lists 1.07M/7.11M/21.03M/43.83M student parameters and 4/28/84/175 MB checkpoints. These are author sizes, not local RAM/VRAM measurements. The 2B teacher is not the consumer default.",
)
add(
    "galileo",
    "Galileo",
    "Multisensor representations",
    "learned_model",
    "Global/local embeddings for classification, segmentation and regression",
    "Declared optical/SAR/static/meteorological modalities, temporal masks, coordinates and model-specific normalization",
    "nasaharvest/galileo",
    "Spatially separated linear-probe and fine-tuning tests, sensor/domain shifts, missing inputs and peak memory",
    model="nasaharvest/galileo",
    priority="daily_workflow",
    notes="Nano, small and base checkpoint files are listed by the model API; embeddings alone do not estimate carbon or soil properties.",
)
add(
    "presto",
    "Presto",
    "Agriculture and phenology",
    "learned_model",
    "Time-series features and crop/land-use predictions; trained target required",
    "Correct band order, actual timestamps, location, missing-band masks and declared auxiliary data",
    "nasaharvest/presto",
    "CropHarvest plus independent field/season holdouts; compare with a small tree model and retain sparse-observation coverage",
    weights="https://github.com/nasaharvest/presto",
    priority="daily_workflow",
    notes="Lightweight temporal candidate. Exact training preprocessing must be inspected before an adapter accepts RSLIB's six-band stack.",
)
add(
    "terramind",
    "TerraMind 1.0",
    "Multisensor representations",
    "learned_model",
    "Dense features, downstream maps and generative modalities",
    "Model-specific optical/SAR/DEM inputs, separate tokenizers and normalization; generative outputs retain model-derived provenance",
    "IBM/terramind",
    "PANGAEA/Geo-Bench tasks, missing-modality robustness and generative observed-pixel/radiometry checks",
    model="ibm-esa-geospatial/TerraMind-1.0-tiny",
    notes="Tiny checkpoint is verified; use a frozen or small-head baseline before optional generative inference.",
)
add(
    "prithvi",
    "Prithvi-EO 2.0",
    "Land cover and hazards",
    "learned_model",
    "Task-adapted crop, flood and burn mapping; representations are dimensionless",
    "HLS-compatible reflectance/band order, temporal/location embeddings and task-head preprocessing",
    "NASA-IMPACT/Prithvi-EO-2.0",
    "Reproduce the task-head benchmark; compare against small models with the same regions, dates and labels",
    model="ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL",
    license_note="Inspected code repository metadata MIT; this 300M-TL checkpoint card Apache-2.0. Preserve the distinction.",
    hardware="GPU candidate; 300M checkpoint and activation memory not benchmarked here",
)
add(
    "anysat",
    "AnySat",
    "Multisensor representations",
    "learned_model",
    "Tile, patch or dense features over multiple resolutions",
    "Per-sensor normalization and dates; modality grids must describe consistent physical extents",
    "gastruc/AnySat",
    "Cross-sensor/resolution holdouts and patch-count resource curves",
    weights="https://huggingface.co/g-astruc/AnySat",
    notes="Native multi-resolution interfaces are relevant to acquisition design; do not force all model inputs into our six-band 30 m stack.",
)
add(
    "universat",
    "UniverSat",
    "Multisensor representations",
    "learned_model",
    "Features over varying spectral, spatial and temporal patches",
    "Universal patch encoder input metadata plus sensor-specific radiometry and wavelength semantics",
    "gastruc/UniverSat",
    "Unseen-sensor tests, frozen-head baseline, token budget and actual consumer-GPU resource measurements",
    model="g-astruc/UniverSat",
    hardware="GPU candidate; released Base is about 201M parameters, not locally measured",
    notes="Upstream distinguishes the released Base weights from a Tiny training configuration. Do not advertise a pretrained Tiny model from configuration files alone.",
)
add(
    "clay",
    "Clay",
    "Multisensor representations",
    "learned_model",
    "Geospatial embeddings; task head required for quantitative targets",
    "Declared platform/bands, wavelengths, ground sample distance, location/time and normalization",
    "Clay-foundation/model",
    "Out-of-region task tests, input-band ablation and comparison with smaller frozen representations",
    weights="https://github.com/Clay-foundation/model",
    license_note="The author README explicitly applies Apache-2.0 to both code and trained weights; documentation CC-BY-4.0. Artifact download locations were not separately pinned here.",
)
add(
    "olmoearth",
    "OlmoEarth v1.2",
    "Multisensor representations",
    "learned_model",
    "Temporal multimodal embeddings and adapted maps",
    "Prescribed sensor bands, stored pixel encodings, modality masks, temporal sampling and model-specific statistics",
    "allenai/olmoearth_pretrain",
    "Reproduce independent downstream tasks and measure input/memory costs for Nano or Tiny",
    model="allenai/OlmoEarth-v1_2-Nano",
    license_note="Custom OlmoEarth Artifact License with field-of-use restrictions; publicly available is not equivalent to unrestricted open source.",
    notes="Small published variants are relevant to local deployment, subject to the actual use terms; do not silently bundle.",
)
add(
    "dofa",
    "DOFA",
    "Multisensor representations",
    "learned_model",
    "Wavelength-conditioned representations across modalities",
    "Spectral metadata and preprocessing matched to each checkpoint, not just the number of input channels",
    "zhu-xlab/DOFA",
    "Unseen sensors and bandwidth/response mismatches, using identical tasks and spatial splits",
    weights="https://github.com/zhu-xlab/DOFA",
)
add(
    "copernicus-fm",
    "Copernicus-FM",
    "Multisensor representations",
    "learned_model",
    "Representations across Copernicus data modalities",
    "Supported sensor bands or variable descriptions, sampling/normalization and model-specific metadata",
    "zhu-xlab/Copernicus-FM",
    "Independent modality/task benchmarks; verify variable-embedding component dependencies",
    model="wangyi111/Copernicus-FM",
    license_note="Inspected subdirectory README Apache-2.0 with MIT components; checkpoint card CC-BY-4.0. Referenced language-derived variable embeddings need their own terms.",
)
add(
    "dinov3",
    "DINOv3 satellite variants",
    "Very-high-resolution mapping",
    "learned_model",
    "Visual features for downstream RGB interpretation",
    "Checkpoint-specific RGB/patch preparation; spectral quantitative variables require separate evidence",
    "facebookresearch/dinov3",
    "Ground-sample-distance and region transfer, geometry/object boundaries, approved checkpoint access and memory",
    weights="https://github.com/facebookresearch/dinov3",
    license_note="Custom DINOv3 License; exact checkpoint access/terms apply.",
    hardware="Large satellite variants need separate resource planning; no 6 GB fit claim",
)
add(
    "satlas",
    "SatlasPretrain",
    "Urban and infrastructure",
    "learned_model",
    "Land cover, objects and infrastructure maps",
    "Backbone-specific Sentinel/aerial channel order, scaling, resolution and downstream head",
    "allenai/satlaspretrain_models",
    "Regional holdouts, object-level precision/recall and pixel-level IoU; separate code/weight/data rights",
    weights="https://github.com/allenai/satlaspretrain_models",
)
add(
    "remoteclip",
    "RemoteCLIP",
    "Visual search and interpretation",
    "learned_model",
    "Image/text embeddings and semantic retrieval scores",
    "Documented RGB image preprocessing, text prompts and ground sample distance",
    "ChenDelong1999/RemoteCLIP",
    "Retrieval and scene interpretation tests across sensors; no physical-unit retrieval claims from text similarity",
    weights="https://huggingface.co/chendelong/RemoteCLIP",
)
add(
    "samgeo",
    "SamGeo with a declared SAM backbone",
    "Segmentation and boundaries",
    "software",
    "Prompted object masks and polygons",
    "Georeferenced display imagery, prompt coordinates and a versioned backbone/checkpoint",
    "opengeos/segment-geospatial",
    "Boundary/area errors and missed/merged objects on local labels, including ambiguous prompts",
    license_note="SamGeo wrapper MIT; selected SAM model/code and weight terms are separate. A wrapper license does not cover every backbone.",
    priority="daily_workflow",
)
add(
    "skysense",
    "SkySense++",
    "Multisensor representations",
    "learned_model",
    "Multimodal task features and segmentation",
    "Prescribed multi-date, multimodal training pipeline and adapted task heads",
    "kang-wu/SkySensePlusPlus",
    "Reference-task reproduction and license suitability before considering an adapter",
    weights="https://github.com/kang-wu/SkySensePlusPlus",
    license_note="Author README limits pretrained weights and pretraining code to non-commercial research. Keep this outside a default unrestricted distribution.",
    hardware="Author training setup uses multi-node A100 hardware; local inference unmeasured",
    priority="research",
)
add(
    "spectralearth",
    "SpectralEarth",
    "Hyperspectral and minerals",
    "learned_model",
    "Hyperspectral representations for classification/segmentation/regression",
    "Imaging-spectrometer wavelengths, bad-band masks and training-compatible surface reflectance",
    "AABNassim/spectral_earth",
    "Sensor wavelength transfer, spectral fidelity and held-out mineral/vegetation targets",
    weights="https://syncandshare.desy.de/index.php/s/Po5bTPipz6EEHx3",
    license_note="Code and checkpoints are linked publicly; repository license was not identified in the metadata snapshot. Do not infer unrestricted reuse.",
    priority="research",
)
add(
    "hypersigma",
    "HyperSIGMA",
    "Hyperspectral and minerals",
    "learned_model",
    "Spatial/spectral features for imaging spectroscopy tasks",
    "Model-specific hyperspectral channels, normalization and spatial patches",
    "WHU-Sigma/HyperSIGMA",
    "Cross-instrument and spatial holdouts, spectral metrics and memory budget",
    weights="https://github.com/WHU-Sigma/HyperSIGMA",
    hardware="Large hyperspectral backbone; local consumer inference unmeasured",
    priority="research",
)
add(
    "smarties",
    "SMARTIES",
    "Multisensor representations",
    "learned_model",
    "Spectrum-aware sensor representations",
    "Supported spectral descriptors, model-specific normalization and downstream head",
    "gsumbul/SMARTIES",
    "PANGAEA-style task reproduction and sensor-transfer tests",
    weights="https://github.com/gsumbul/SMARTIES",
    priority="research",
)
add(
    "thor",
    "THOR",
    "Multisensor representations",
    "learned_model",
    "Task-adapted geospatial features",
    "Versioned pretraining and downstream modality/band contracts",
    "FM4CS/THOR",
    "Same-split low-label evaluation; verify released artifact and license terms separately",
    weights="https://github.com/FM4CS/THOR",
    priority="research",
)
add(
    "hls",
    "HLS V2 preprocessing chain",
    "Radiometry and harmonization",
    "operational_method",
    "Surface reflectance / unit 1 on a 30 m NBAR product grid",
    "Atmospheric correction, masks, geometry/BRDF and spectral-band adjustment; original product metadata",
    "https://hls.gsfc.nasa.gov/algorithms/",
    "Co-located physical measurements and intercomparison stratified by land cover, view/solar geometry and residual registration",
    priority="daily_workflow",
    status="partial_support",
    notes="RSLIB accepts upstream HLS stacks; ordinary S2/OLI processing currently implements a partial bandpass adjustment, not the complete chain.",
)
add(
    "prosail",
    "PROSPECT + SAIL / PROSAIL",
    "Vegetation biophysics",
    "physical_model",
    "Canopy reflectance; inverse LAI / m² m⁻², pigments and leaf water with explicit units",
    "Leaf optical/structural parameters, LAI, soil spectra, solar/view geometry and sensor response functions",
    "jgomezdans/prosail",
    "Independent field LAI/pigment/water references; inversion identifiability, parameter priors, sensor band integration and emulator error",
    license_note="Public implementation exists; repository metadata did not identify its license. Review the exact implementation and bundled model/data terms before use.",
    priority="quantitative_extension",
    notes="Prefer physically parameterized LUT/GP/emulator retrieval over treating a vegetation index as LAI or carbon.",
)
add(
    "scope",
    "SCOPE",
    "Vegetation biophysics",
    "physical_model",
    "Radiance, fluorescence, photosynthesis and canopy energy fluxes",
    "Leaf/canopy structure, biochemical parameters, soil, geometry and meteorological forcing",
    "Christiaanvandertol/SCOPE",
    "Radiance/fluorescence plus tower-flux references; quantify equifinality and forcing uncertainty",
    hardware="Specialist radiative-transfer/energy backend; CPU simulations or a separately validated emulator",
    notes="A physiological forward model requires measured/defensible inputs; RGB appearance does not supply them.",
)
add(
    "py6s",
    "6S / Py6S",
    "Atmospheric correction",
    "physical_model",
    "Atmosphere-to-sensor transfer and surface reflectance / unit 1",
    "Radiance/TOA reflectance, aerosols, water vapour, ozone, elevation, geometry and spectral response",
    "robintw/Py6S",
    "Reference radiative-transfer cases and reflectance validation; keep wrapper and external 6S runtime terms distinct",
    hardware="CPU LUT/backend candidate; external radiative-transfer executable required",
)
add(
    "eradiate",
    "Eradiate",
    "Radiative transfer and validation",
    "physical_model",
    "Spectral radiance/reflectance from 3D scenes",
    "Physical scene/optical properties, atmosphere, illumination and sensor configuration",
    "eradiate/eradiate",
    "Radiative closure, variance/convergence and reference-scene comparisons",
    hardware="Monte Carlo radiative-transfer backend; scene/sample-dependent CPU costs",
    priority="specialist",
)
add(
    "isofit",
    "ISOFIT",
    "Hyperspectral and minerals",
    "physical_model",
    "Joint atmosphere/surface inverse estimates with retrieval uncertainty",
    "Calibrated imaging-spectrometer radiance, wavelengths/FWHM, uncertainty and forward-model auxiliaries",
    "isofit/isofit",
    "Spectral/radiometric closure, in situ surface references and uncertainty calibration",
    hardware="CPU/GPU emulator or radiative-transfer backend; data/solver dependent",
    notes="Backend choice matters: optional proprietary radiative-transfer software is not made open by the Apache-licensed fitting framework.",
)
add(
    "thermal-product",
    "Landsat Collection 2 surface temperature",
    "Thermal and urban heat",
    "data_product",
    "Surface temperature / K with product uncertainty/QA",
    "Documented thermal calibration, emissivity and atmospheric auxiliaries; distinguish product scaling from reflectance",
    "https://www.usgs.gov/landsat-missions/landsat-collection-2-surface-temperature",
    "CEOS LST protocol, in situ radiometry, cloud-distance effects and emissivity/ASTER gaps",
    priority="quantitative_extension",
    notes="Prefer retrieving the documented product before inventing an NDVI-to-temperature transform.",
)
add(
    "tseb",
    "TSEB / pyTSEB",
    "Evapotranspiration and energy",
    "physical_model",
    "Latent/sensible/soil heat / W m⁻²; ET after explicit time conversion",
    "Radiometric temperature, vegetation structure, radiation, meteorology, roughness and soil/canopy partition assumptions",
    "hectornieto/pyTSEB",
    "Flux-tower comparison with explicit energy-closure treatment, land cover/season holdouts and uncertainty",
    hardware="CPU physical-model candidate; run/window costs unmeasured",
)
add(
    "pydms",
    "pyDMS thermal sharpening",
    "Thermal and urban heat",
    "operational_method",
    "Disaggregated thermal field on a finer grid",
    "Coarse thermal observations plus fine optical predictors and a matched aggregation operator",
    "hectornieto/pyDMS",
    "Conservation at thermal observation scale and independent high-resolution thermal references",
    notes="Finer output spacing does not establish observed fine-scale temperature.",
)
add(
    "pywapor",
    "pyWaPOR / ETLook",
    "Evapotranspiration and energy",
    "physical_model",
    "Evaporation, transpiration and productivity; explicit daily units",
    "Versioned thermal/optical/meteo/terrain products, date conventions and energy/water assumptions",
    "DHI-GRAS/pywapor",
    "Flux-tower and basin water-balance checks, temporal aggregation and product-version provenance",
)
add(
    "cold",
    "COLD / S-CCD via pycold",
    "Change and disturbance",
    "operational_method",
    "Spectral break dates, harmonic models and change magnitudes",
    "Long, calibrated quality-screened multi-band time series with real timestamps and sufficient clear observations",
    "GERSL/pycold",
    "Independent event dates, false alarms/omissions, detection delay and seasonal/observation-density strata",
    priority="daily_workflow",
    notes="More appropriate for sustained change than interpolating straight through every spectral break; short six-date runs are insufficient for a reliable harmonic history.",
)
add(
    "opencd",
    "Open-CD",
    "Change and disturbance",
    "software",
    "Task-specific bitemporal change masks",
    "Co-registered before/after imagery and a checkpoint-specific spatial/spectral contract",
    "likyoo/open-cd",
    "Geographic holdouts, unchanged-area false alarms, object boundaries and real event labels",
    weights="https://github.com/likyoo/open-cd",
)
add(
    "cloud-mask",
    "s2cloudless / CloudSEN12 comparisons",
    "Clouds and reconstruction",
    "operational_method",
    "Cloud probability/masks, rather than inferred clear reflectance",
    "Detector-specific reflectance level/bands and documented cloud/shadow labels",
    "sentinel-hub/sentinel2-cloud-detector",
    "CloudSEN12-like geographically independent labels, cloud/shadow omissions and downstream index contamination",
    weights="https://github.com/sentinel-hub/sentinel2-cloud-detector",
    priority="daily_workflow",
    notes="Do not feed the six-band L2A stack to a detector trained for a different TOA/band contract. Native QA remains the operational default.",
)
add(
    "uncrtaints",
    "UnCRtainTS",
    "Clouds and reconstruction",
    "learned_model",
    "Multitemporal reconstructed reflectance and model uncertainty",
    "Model-specific optical/SAR band order, normalization, timestamps and cloud masks",
    "PatrickTUM/UnCRtainTS",
    "AllClear/geographic-temporal holdouts, spectral angle, observed-pixel preservation and empirical uncertainty coverage",
    weights="https://github.com/PatrickTUM/UnCRtainTS",
    hardware="Tiled GPU candidate; no local resource or calibration result",
    notes="Uncertainty output is not automatically calibrated uncertainty.",
)
add(
    "emrdm",
    "EMRDM",
    "Clouds and reconstruction",
    "learned_model",
    "Diffusion-restored cloud-obscured optical imagery",
    "Paired modalities, scale and normalization matching the author checkpoint",
    "Ly403/EMRDM",
    "Real cloudy/clear references, spectral error, abrupt-change retention and compute budgets",
    weights="https://github.com/Ly403/EMRDM",
    hardware="Iterative GPU candidate; local VRAM/latency unmeasured",
    priority="research",
)
add(
    "anytimeformer",
    "AnytimeFormer",
    "Clouds and reconstruction",
    "learned_model",
    "Optical reconstruction at requested times from asynchronous sensors",
    "Irregular optical/SAR timestamps, calibrated inputs, masks and model-specific preprocessing",
    "tangkai-RS/AnytimeFormer",
    "Withhold complete dates/events; compare with bounded interpolation on paired supported areas",
    weights="https://github.com/tangkai-RS/AnytimeFormer",
    hardware="GPU candidate; local inference unmeasured",
    priority="research",
)
add(
    "sen2srlite",
    "SEN2SRLite / SEN2SR",
    "Super-resolution",
    "learned_model",
    "Model-derived reflectance on a finer grid",
    "Lite adapter: physical RGB + broad B08 NIR at native 10 m, QA and declared resampling/halo",
    "ESAOpenSR/SEN2SR",
    "Sensor-forward-model consistency and independent high-resolution spectral/spatial references",
    model="tacofoundation/SEN2SR",
    hardware="Lite locally measured on RTX 3050 6 GB; see prior benchmark scope",
    status="implemented_lite",
    notes="Only Lite RGBN ×4 is integrated here. Full/reference-band variants remain candidates; no verified fine-detail accuracy from sharper output alone.",
)
add(
    "opensr",
    "OpenSR / LDSR-S2",
    "Super-resolution",
    "learned_model",
    "Diffusion-derived high-resolution multispectral imagery",
    "Correct Sentinel-2 bands, normalization and observation-consistency operator",
    "ESAOpenSR/opensr-model",
    "OpenSR-test plus paired high-resolution references, spectral indices and hallucination/change diagnostics",
    weights="https://github.com/ESAOpenSR/opensr-model",
    hardware="Iterative tiled GPU candidate; unmeasured locally",
    priority="research",
)
add(
    "cufsdaf",
    "FSDAF / cuFSDAF",
    "Spatiotemporal fusion",
    "operational_method",
    "Frequent fine-grid estimates from sparse fine and frequent coarse observations",
    "Spectrally matched fine/coarse pairs, acquisition dates, footprints and aggregation/PSF assumptions",
    "https://github.com/HPSCIL/cuFSDAF",
    "Withheld real fine observations, abrupt-change cases, coarse-resolution consistency and spatial-edge behavior",
    hardware="CUDA implementation; scene/domain-decomposition costs must be measured",
    notes="Classical fusion baseline alongside STARFM/ESTARFM; this is a different observation problem from single-image SR.",
)
add(
    "sar-preparation",
    "pyroSAR and SAR terrain-flattening workflows",
    "SAR and soil moisture",
    "software",
    "Calibrated geocoded radar backscatter; linear power and dB kept distinct",
    "GRD/SLC product, precise orbit, noise/calibration metadata, DEM and incidence/layover/shadow masks",
    "johntruckenbrodt/pyroSAR",
    "CEOS-ARD backscatter checks, topographic residuals, speckle assumptions and cross-orbit consistency",
    hardware="Specialist SAR backend and disk budget; CPU windowing possible",
    priority="quantitative_extension",
    notes="A soil-moisture estimate additionally needs roughness/vegetation or a trained retrieval. Backscatter is not volumetric moisture by itself.",
)
add(
    "isce",
    "ISCE3",
    "InSAR and deformation",
    "software",
    "Interferometric phase, coherence and geocoded SAR products",
    "Complex SLCs, orbit/timing, DEM, wavelength, baselines and a reference configuration",
    "isce-framework/isce3",
    "Phase/reference cases, geolocation and unwrapping/coherence failure behavior",
    hardware="Specialist CPU/CUDA backend with substantial I/O; not a generic RGB model",
)
add(
    "mintpy",
    "MintPy SBAS time series",
    "InSAR and deformation",
    "operational_method",
    "Relative line-of-sight displacement / m and velocity / m year⁻¹",
    "Coherent interferogram network, reference pixel/date, atmosphere/orbit corrections and unwrapping QA",
    "insarlab/MintPy",
    "Independent GNSS, network closure and atmospheric/topographic confounding",
    license_note="Inspected pyproject identifies GPL-3.0-or-later; GitHub metadata did not classify the license.",
    hardware="CPU time-series backend; memory/I/O depend on interferogram network",
    notes="Line-of-sight displacement is not a complete 3D displacement vector or automatic landslide forecast.",
)
add(
    "canopy-height",
    "Global canopy-height model (Lang et al.)",
    "Forestry and biomass",
    "learned_model",
    "Canopy top height / m, with model uncertainty",
    "Training-compatible Sentinel-2 observations and GEDI-reference context",
    "langnico/global-canopy-height-model",
    "Independent airborne lidar/field heights, footprint/time mismatch and biome/domain holdouts",
    weights="https://github.com/langnico/global-canopy-height-model",
    notes="Canopy height is not biomass or carbon. Allometry and plot-level validation remain separate.",
)
add(
    "biomass-benchmark",
    "BioMassters / PANGAEA regression",
    "Forestry and biomass",
    "benchmark",
    "Above-ground biomass / Mg ha⁻¹ where the benchmark defines that target",
    "S1/S2 time series and benchmark-specific reference maps/splits",
    "VMarsocci/pangaea-bench",
    "Spatially blocked regression, high-biomass saturation, reference-map uncertainty and biome-transfer checks",
    priority="quantitative_extension",
    notes="Use the benchmark to compare models; Finnish reference-map agreement does not validate global carbon accounting.",
)
add(
    "acolite",
    "ACOLITE DSF / adjacency correction",
    "Ocean and inland water",
    "physical_model",
    "Water-leaving reflectance and derived aquatic variables with explicit radiometric convention",
    "Aquatic-appropriate sensor bands, TOA inputs/ancillaries and documented glint/adjacency handling",
    "acolite/acolite",
    "AERONET-OC/in situ water radiometry and water-type/turbidity/adjacency strata",
    hardware="CPU atmospheric-correction backend and ancillary/LUT data",
    notes="Land L2A surface reflectance cannot be silently relabeled water-leaving reflectance.",
)
add(
    "seadas",
    "SeaDAS / OCSSW l2gen and C2RCC",
    "Ocean and inland water",
    "physical_model",
    "Rrs / sr⁻¹, chlorophyll / mg m⁻³ and optical-property products",
    "Sensor-specific ocean-color radiometry, atmospheric correction, quality flags and algorithm water type",
    "https://seadas.gsfc.nasa.gov/help-9.0.0/c2rcc/C2RCCAlgorithmSpecification.html",
    "Independent in-water/above-water radiometry and constituent samples; matchup windows and atmospheric flags",
    hardware="Specialist ocean-color backend; components have separate terms",
    notes="QAA/OCx/neural retrieval alternatives must be compared on the intended water regime, not one universal chlorophyll equation.",
)
add(
    "coastsat",
    "CoastSat",
    "Coasts and shorelines",
    "operational_method",
    "Shoreline positions and change / m",
    "Cloud-screened imagery, tidal datum/water level, beach slope and geolocation",
    "kvos/CoastSat",
    "Surveyed shorelines with tide/runup/geolocation uncertainty and seasonal beach morphology",
    hardware="CPU workflow candidate",
)
add(
    "sasktran",
    "SASKTRAN2",
    "Atmospheric composition",
    "physical_model",
    "Spectral radiance and atmospheric Jacobians for retrieval",
    "Geometry, atmospheric state, spectroscopy and calibrated radiance/uncertainty",
    "usask-arg/sasktran2",
    "Radiative-transfer reference cases, retrieval residuals, vertical sensitivity and averaging kernels",
    hardware="CPU radiative-transfer backend; spectral/geometry dependent",
    priority="specialist",
)
add(
    "mag1c",
    "mag1c methane matched filtering",
    "Atmospheric composition",
    "operational_method",
    "Path-integrated methane enhancement; plume emission requires a separate transport model",
    "Calibrated hyperspectral radiance, methane response spectrum, background/clutter and noise model",
    "markusfoote/mag1c",
    "Injection/controlled-release references, detection limits, background bias and wind-driven flux uncertainty",
    hardware="CPU/GPU matrix operations; windowing and covariance costs depend on scene",
    notes="Detection/enhancement is not emissions in kg h⁻¹ without transport and wind assumptions.",
)
add(
    "emit",
    "EMIT spectroscopy and methane products",
    "Hyperspectral and minerals",
    "data_product",
    "Surface mineral/reflectance products and methane plume products; variable-specific units",
    "Published EMIT product levels, wavelength/geolocation/QA and uncertainty arrays",
    "nasa/EMIT-Data-Resources",
    "Product ATBD validation, geolocation matchups and independent field/airborne references",
    notes="Prefer existing validated product ingestion before a new unconstrained spectral regression.",
)
add(
    "oggm",
    "OGGM",
    "Cryosphere",
    "physical_model",
    "Glacier geometry, mass balance and evolution",
    "Glacier outlines, DEM/thickness constraints, climate forcing and calibration periods",
    "OGGM/oggm",
    "Independent geodetic mass balance/velocity/thickness and out-of-period evaluation",
    hardware="CPU model/backend; glacier ensemble costs vary",
    notes="Satellite observations constrain a glacier model; the forward model is not itself a satellite retrieval.",
)
add(
    "xdem",
    "xDEM coregistration and uncertainty",
    "Terrain and elevation change",
    "operational_method",
    "DEM differences / m and volume change / m³",
    "Vertical datum, coregistration, stable-terrain masks, acquisition epochs and elevation uncertainty",
    "GlacioHack/xdem",
    "Stable-terrain residuals, slope/aspect biases, spatial error covariance and independently surveyed change",
    priority="daily_workflow",
)
add(
    "pdal",
    "PDAL point-cloud processing",
    "LiDAR and 3D structure",
    "software",
    "Ground/canopy point classes, height / m and derived grids",
    "Point CRS/vertical datum, return/scan attributes, ground classification and density metadata",
    "PDAL/PDAL",
    "Survey controls, ground-classification errors, density/occlusion effects and canopy reference validation",
    hardware="CPU streaming/tiling candidate; algorithm-dependent memory",
    notes="Keep footprint/return structure and vertical reference instead of flattening lidar into a display DEM.",
)
add(
    "neuralhydrology",
    "NeuralHydrology LSTM/hybrid baselines",
    "Hydrology and water storage",
    "learned_model",
    "Discharge or water-state predictions with declared units",
    "Catchment forcing/attributes, gauge targets and explicit temporal/basin splits",
    "https://github.com/neuralhydrology/neuralhydrology",
    "Ungauged-basin and out-of-period tests, water balance, extremes and target uncertainty",
    hardware="Small-model CPU/GPU candidate; architecture-dependent",
    notes="Hydrologic forecasting complements EO inputs. It does not supply unmeasured geotechnical parameters to the Rust slope model.",
)
add(
    "pinnicle",
    "PINNICLE",
    "Cryosphere",
    "physical_model",
    "Ice-flow state/parameter estimates constrained by observations and PDEs",
    "Ice geometry/velocity data, boundary conditions, constitutive parameters and PDE residual scales",
    "https://github.com/ISSMteam/PINNICLE",
    "Independent velocity/thickness, boundary conditions and PDE/data-loss sensitivity",
    hardware="Specialist CPU/GPU inverse-problem workflow",
    notes="Physics-informed losses do not by themselves establish identifiability or correct uncertainty.",
)
add(
    "prithvi-wxc",
    "Prithvi-WxC",
    "Weather and Earth-system context",
    "learned_model",
    "Weather/climate context and downstream fields",
    "Model-prescribed gridded atmospheric variables, levels, units and time sampling",
    "NASA-IMPACT/Prithvi-WxC",
    "Independent initialization dates/events and physically meaningful forecast/downscaling scores",
    weights="https://github.com/NASA-IMPACT/Prithvi-WxC",
    hardware="Large Earth-system model; no consumer-hardware inference claim",
    priority="specialist",
)
add(
    "aurora",
    "Aurora",
    "Weather and Earth-system context",
    "learned_model",
    "Earth-system forecasts: weather, air pollution or waves for supported checkpoints",
    "Checkpoint-specific surface/atmospheric variables, vertical levels and units",
    "microsoft/aurora",
    "Independent event/lead-time evaluation and physical-unit target scores",
    weights="https://github.com/microsoft/aurora",
    license_note="Custom model/code terms are referenced by the author. Treat checkpoint-specific licensing separately.",
    hardware="Large global model; Small variant still requires a local resource benchmark",
    priority="specialist",
)
add(
    "alphaearth",
    "AlphaEarth Foundations annual embeddings",
    "Multisensor representations",
    "data_product",
    "Published annual embedding features; trained physical targets require separate reference labels",
    "Earth Engine published embedding product/version, year, spatial support and dataset terms",
    "https://deepmind.google/blog/alphaearth-foundations-helps-map-our-planet-in-unprecedented-detail/",
    "Spatial/temporal task validation and comparison with locally reproducible feature pipelines",
    hardware="Published-data ingestion; local inference weights not verified",
    notes="The primary announcement releases annual embeddings. Do not describe that as an available local model checkpoint.",
)
add(
    "isis",
    "USGS ISIS planetary processing",
    "Planetary remote sensing",
    "software",
    "Planetary radiometry, geometry, mosaics and surface products",
    "Mission-specific instrument calibration, SPICE geometry, body reference frame and surface model",
    "https://github.com/DOI-USGS/ISIS3",
    "Mission calibration and geometric control networks; Earth CRS/atmosphere assumptions do not transfer",
    hardware="Specialist CPU planetary-processing backend",
    priority="specialist",
)
add(
    "ceos-lpv",
    "CEOS LPV product-validation protocols",
    "Validation and uncertainty",
    "validation_protocol",
    "Traceable target-unit errors and uncertainty across land products",
    "Independent references with their own uncertainty, spatial/temporal support and product QA",
    "https://lpvs.gsfc.nasa.gov/",
    "Use the target-specific vegetation, LAI, LST, ET, soil-moisture and land-cover protocols; document matchup and reference errors",
    hardware="Protocol and reference-data design",
    priority="daily_workflow",
)

add(
    "arosics",
    "AROSICS",
    "Geometry and registration",
    "operational_method",
    "Relative optical image offsets / pixels or metres",
    "Stable cloud-free texture, compatible bands/footprints, georeferencing and a clear interpolation policy",
    "https://github.com/GFZ/arosics",
    "Independent tie points, stable-terrain residual offsets, local warp failures and downstream edge/area errors",
    priority="daily_workflow",
    notes="Addresses a missing part of the current harmonization chain. A common GDAL output grid alone does not correct image displacement.",
)
add(
    "smap",
    "SMAP tau-omega soil-moisture retrieval",
    "Passive microwave and soil moisture",
    "physical_model",
    "Near-surface volumetric soil moisture / m³ m⁻³",
    "Brightness temperature, surface effective temperature, vegetation optical depth, roughness, water/frozen-ground flags and antenna footprint",
    "https://smap.jpl.nasa.gov/system/internal_resources/details/original/316_L2_SM_P_ATBD_v7_Sep2015.pdf",
    "CEOS soil-moisture validation, footprint-matched networks and triple-collocation assumptions; surface versus root-zone depth",
    hardware="CPU forward/retrieval model; prefer current documented products",
    notes="The cited ATBD establishes the model family; select the current product/version ATBD before implementation. Coarse footprint soil moisture is not a 30 m field measurement.",
)
add(
    "soilgrids",
    "SoilGrids and depth-aware SOC stock accounting",
    "Soils and carbon",
    "data_product",
    "Soil properties at declared depths; SOC stock / Mg C ha⁻¹ with bulk density/coarse fragments",
    "SoilGrids product scale factors, depth intervals, survey references and physical unit conversions",
    "https://docs.isric.org/globaldata/soilgrids/",
    "Independent soil profiles, depth/bulk-density error, equivalent-soil-mass comparisons and spatially correlated uncertainty",
    priority="quantitative_extension",
    status="partial_support",
    notes="RSLIB has unit/stock/pedotransfer helpers. Marginal property quantiles do not define a joint uncertainty distribution, and SOC stock is not measured carbon emissions.",
)
add(
    "gprof",
    "GPROF-NN",
    "Precipitation",
    "learned_model",
    "Passive-microwave precipitation retrieval and distributional outputs",
    "Sensor brightness temperatures, channel/scan geometry, atmospheric auxiliaries and model-specific training references",
    "https://github.com/simonpf/gprof_nn",
    "Independent radar/gauge references, precipitation extremes, sensor and climatic-domain shifts; calibrate distributional outputs",
    weights="https://github.com/simonpf/gprof_nn",
    hardware="Specialist microwave model; local tiled inference unmeasured",
)
add(
    "smrt",
    "SMRT microwave snow/ice radiative transfer",
    "Cryosphere",
    "physical_model",
    "Brightness temperature/backscatter/waveforms; inverse snow/ice properties need separate constraints",
    "Layered snow/ice density, microstructure, temperature, permittivity and sensor frequency/geometry",
    "https://github.com/smrt-model/smrt",
    "Independent snow pits/SWE/ice data and radiometric closure; quantify microstructure/temperature degeneracy",
    hardware="CPU radiative-transfer candidate",
    notes="Optical snow fraction does not determine snow water equivalent.",
)
add(
    "mcd43",
    "Ross-Li BRDF and albedo retrieval",
    "Albedo and radiation",
    "operational_method",
    "NBAR/albedo / unit 1 and angular model coefficients",
    "Multi-angle quality-screened reflectance, solar/view geometry and explicit kernel/illumination definitions",
    "https://hls.gsfc.nasa.gov/algorithms/",
    "Independent angular/ground-albedo measurements, coefficient conditioning and snow/land-cover transitions",
    priority="quantitative_extension",
    notes="Integrate supplied physical angles or upstream NBAR first. Do not infer BRDF coefficients from an arbitrary short clear stack.",
)
add(
    "libradtran",
    "libRadtran",
    "Albedo and radiation",
    "physical_model",
    "Spectral irradiance/radiance and radiative fluxes with declared units",
    "Atmospheric profiles, absorbers/aerosols, surface properties, spectral grids and illumination",
    "https://www.libradtran.org/",
    "Published radiative-transfer cases and independent surface-radiation networks; spectral/angle integration and solver convergence",
    hardware="CPU backend or a separately validated LUT/emulator",
    priority="specialist",
)
add(
    "biopal",
    "BioPAL BIOMASS Processing Suite",
    "Forestry and biomass",
    "software",
    "Mission-specific SAR processing and stack products for biomass workflows",
    "BIOMASS product levels, calibration/orbit geometry, interferometric stack and reference biomass/height data",
    "https://github.com/BioPAL/BPS",
    "Mission algorithm/reference-product reproduction, radiometry/geometry and independent plot/lidar comparisons",
    license_note="Official credits identify MIT portions plus separately licensed ARESYS kernels. A public suite is not evidence that every dependency is unrestricted.",
    hardware="Specialist SAR stack/backend and disk budget",
    priority="specialist",
)
add(
    "gravity",
    "GRACE/GRACE-FO gravity-toolkit",
    "Hydrology and water storage",
    "physical_model",
    "Large-scale water-equivalent mass/storage anomalies with reference conventions",
    "Gravity coefficients/mascons, geocentre/low-degree corrections, leakage and glacial-isostatic assumptions",
    "https://github.com/tsutterley/gravity-toolkit",
    "Basin-scale mass balance, reference-frame/correction sensitivity and independent water-storage constraints",
    hardware="CPU scientific backend",
    notes="Broad gravity footprints cannot establish local field-scale soil-water change.",
)
add(
    "deepforest",
    "DeepForest crown detection",
    "Biodiversity and ecology",
    "learned_model",
    "Tree-crown detections/counts; species and biomass need separate validated targets",
    "Aerial RGB data at supported ground sample distance, georeferencing and local annotation conventions",
    "https://github.com/weecology/DeepForest",
    "Independent biome/flight/season labels, crown matching, omission/commission and density effects",
    weights="https://github.com/weecology/DeepForest",
    hardware="Tiled GPU candidate; local throughput unmeasured",
)

extend(add)

ids = [m["id"] for m in METHODS]
if len(set(ids)) != len(ids):
    raise ValueError("Duplicate method identifier")
result = {
    "schema_version": "rslib-research-inventory/1",
    "checked_utc": SNAPSHOT["checked_utc"],
    "scope": "Broad primary-source survey across major EO methods and applications; not an exhaustive field-wide ranking or a list of installed adapters.",
    "source_snapshot": "source-snapshot.json",
    "methods": METHODS,
}
(ROOT / "methods.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
# The static page is a research aid, kept outside the operational method selector.
Path("docs/showcase/32-research-inventory.json").write_text(
    json.dumps(result, indent=2, ensure_ascii=False) + "\n"
)
lines = [
    "# Reviewed method inventory",
    "",
    "Generated from [methods.json](methods.json). All unintegrated entries are candidates. See [the quantitative review](../REMOTE_SENSING_RESEARCH.md) for scope and integration priorities.",
    "",
    "| Method | Domain | Availability | Integration |",
    "| --- | --- | --- | --- |",
]
for method in METHODS:
    lines.append(
        f"| [{method['name']}]({method['source']}) | {method['domain']} | {method['availability']} | {method['rslib_status']} |"
    )
(ROOT / "INDEX.md").write_text("\n".join(lines) + "\n")
print(
    f"Reviewed {len(METHODS)} methods across {len(set(m['domain'] for m in METHODS))} domains; source metadata for {len(REPOS)} repositories and {len(MODELS)} model cards."
)

Path("docs/showcase/33-source-snapshot.json").write_text(json.dumps(SNAPSHOT, indent=2) + "\n")
page = r"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RSLIB research methods</title><style>
*{box-sizing:border-box}body{margin:0;color:#233b50;background:#f3f5f7;font:14px/1.6 system-ui,sans-serif}header{background:white;border-bottom:1px solid #cdd7df;padding:16px 28px;display:flex;gap:25px;align-items:center;flex-wrap:wrap}header a{font-size:12px}a{color:#235d88}main{max-width:1560px;margin:auto;padding:25px}h1{font-size:25px;font-weight:600;margin:0 0 10px}h2{font-size:19px;margin:0 0 12px}h3{font-size:13px;margin:18px 0 5px}p{margin:7px 0}input,select,button{font:inherit;color:inherit}input,select{padding:8px;border:1px solid #aebfcc;border-radius:3px;background:white}.intro{max-width:1080px}.note{color:#596e80;font-size:12px}.filters{display:flex;gap:13px;flex-wrap:wrap;margin:22px 0 10px}.filters label{display:flex;flex-direction:column;font-size:11px;color:#4f667a;gap:5px}.filters input{min-width:260px}.filters select{max-width:270px}.workspace{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);gap:22px;align-items:start}.table-wrap{overflow:auto;max-height:750px;border:1px solid #cdd7df;border-radius:4px}table{border-collapse:collapse;width:100%;background:white;font-size:12px}th,td{padding:10px 12px;text-align:left;border-bottom:1px solid #e0e7ed;vertical-align:top}th{background:#eaf0f5;position:sticky;top:0;z-index:1;font-size:11px}td button{background:none;border:0;padding:0;text-align:left;color:#235d88;cursor:pointer;font-weight:600}tr.selected td{background:#eaf2f8}#detail{background:white;border:1px solid #cdd7df;border-radius:4px;padding:22px;overflow-wrap:anywhere}#detail p{font-size:13px}#detail code{font:11px/1.7 ui-monospace,monospace}#count{margin:8px 0 16px}footer{font-size:12px;padding:25px 0;color:#5c7285}.status{border-left:3px solid #8a9dad;padding-left:10px;color:#536b7d}button:focus-visible,a:focus-visible{outline:2px solid #23668b;outline-offset:3px}@media(max-width:1050px){.workspace{grid-template-columns:1fr}.table-wrap{max-height:410px}}@media(max-width:600px){main{padding:16px}.filters{flex-direction:column}.filters input,.filters select{width:100%;min-width:0;max-width:100%}header{padding:14px 16px;gap:14px}th,td{padding:8px;font-size:11px}#detail{padding:16px}}
</style><header><strong>RSLIB · Research methods</strong><a href="/workflows.html">Optical analysis</a><a href="./">Development captures</a><a href="https://shop.elsevier.com/books/advanced-remote-sensing/liang/978-0-12-815826-5">Advanced Remote Sensing · publisher</a></header><main><div class="intro"><h1>Methods, inputs and validation requirements</h1><p>A primary-source survey across quantitative retrieval, learned representations, image preparation and application-specific processing. Most entries are research candidates and have no installed RSLIB adapter.</p><p class="note">Checked 2026-10-17. A repository license does not establish model-weight or training-data rights. Hardware descriptions distinguish author specifications from local measurements. This inventory does not rank methods evaluated on different tasks.</p></div><div class="filters"><label>Search methods, inputs or targets<input id="search" type="search" placeholder="e.g. soil, uncertainty, cloud, LAI"></label><label>Domain<select id="domain"><option value="">All domains</option></select></label><label>Method type<select id="kind"><option value="">All types</option></select></label><label>Artifact evidence<select id="availability"><option value="">All evidence levels</option><option value="checkpoint_metadata_verified">Checkpoint metadata verified</option><option value="checkpoint_linked">Checkpoint linked, not pinned</option><option value="code_available">Code available</option><option value="published_product_reference">Published product reference</option><option value="method_or_product_reference">Method/protocol reference</option></select></label></div><p id="count" class="note" role="status"></p><div class="workspace"><div class="table-wrap"><table><thead><tr><th>Method</th><th>Domain</th><th>RSLIB status</th></tr></thead><tbody id="rows"></tbody></table></div><article id="detail"></article></div><footer><a href="32-research-inventory.json" download>Download reviewed inventory JSON</a> · <a href="33-source-snapshot.json" download>Repository and model-card metadata snapshot</a><p>Candidate entries are not an operational model selector. Model downloads and remote-code execution are not performed by this page.</p></footer></main><script id="inventory" type="application/json">__INVENTORY__</script><script>
const methods=JSON.parse(document.querySelector('#inventory').textContent).methods;
const $=id=>document.getElementById(id);let selected=methods[0].id;
for(const key of ['domain','kind'])for(const value of [...new Set(methods.map(m=>m[key]))].sort()){const option=document.createElement('option');option.value=value;option.textContent=value.replaceAll('_',' ');$(key).append(option)}
function detail(method){const box=$('detail');box.replaceChildren();const h=document.createElement('h2');h.textContent=method.name;box.append(h);const state=document.createElement('p');state.className='status';state.textContent='RSLIB: '+method.rslib_status.replaceAll('_',' ')+' · Evidence: '+method.availability.replaceAll('_',' ');box.append(state);
function paragraph(title,value){const h=document.createElement('h3');h.textContent=title;const p=document.createElement('p');p.textContent=value;box.append(h,p)}
paragraph('Target and units',method.target_and_units);paragraph('Required inputs',method.input_contract);paragraph('Evaluation required',method.evaluation_gate);paragraph('Hardware evidence',method.hardware);paragraph('Code license evidence',method.code_license);paragraph('License scope',method.license_note);if(method.notes)paragraph('Integration notes',method.notes);const source=document.createElement('a');source.href=method.source;source.textContent='Open primary source';source.target='_blank';source.rel='noopener';box.append(source);
if(method.checkpoint){const h=document.createElement('h3');h.textContent='Checkpoint evidence';const a=document.createElement('a');a.href=method.checkpoint.url;a.textContent=method.checkpoint.url;a.target='_blank';a.rel='noopener';const p=document.createElement('p');p.textContent='Model-card license: '+method.checkpoint.license;box.append(h,a,p);if(method.checkpoint.revision){const code=document.createElement('code');code.textContent='Inspected revision: '+method.checkpoint.revision;box.append(code)}}}
function filter(){const term=$('search').value.trim().toLowerCase();const shown=methods.filter(m=>(!$('domain').value||m.domain===$('domain').value)&&(!$('kind').value||m.kind===$('kind').value)&&(!$('availability').value||m.availability===$('availability').value)&&(!term||JSON.stringify(m).toLowerCase().includes(term)));$('count').textContent=shown.length+' matching methods. Select a method to inspect its input and validation contract.';if(!shown.some(m=>m.id===selected))selected=shown[0]?.id;$('rows').replaceChildren(...shown.map(m=>{const tr=document.createElement('tr');tr.className=m.id===selected?'selected':'';const name=document.createElement('td'),button=document.createElement('button');button.type='button';button.textContent=m.name;button.onclick=()=>{selected=m.id;filter()};name.append(button);const domain=document.createElement('td');domain.textContent=m.domain;const status=document.createElement('td');status.textContent=m.rslib_status.replaceAll('_',' ');tr.append(name,domain,status);return tr}));if(selected)detail(shown.find(m=>m.id===selected));else $('detail').textContent='No matching methods. Change the filters.'}
for(const id of ['search','domain','kind','availability'])$(id).addEventListener('input',filter);filter();
</script></html>"""
page = page.replace("__INVENTORY__", json.dumps(result, ensure_ascii=False).replace("<", "\\u003c"))
Path("docs/showcase/research.html").write_text(page)
