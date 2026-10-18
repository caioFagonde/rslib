"""Curated classical-method records; sources inspected 2026-10-17.

These entries distinguish an established algorithm, an available implementation,
and our bounded implementation. They do not claim algorithmic novelty.
"""


def extend(add):
    def record(
        identifier, name, domain, target, inputs, source, gate, *, notes="", status="candidate"
    ):
        add(
            identifier,
            name,
            domain,
            "classical_algorithm",
            target,
            inputs,
            source,
            gate,
            hardware="CPU candidate; tile limits and solver cost depend on implementation",
            priority="daily_workflow",
            notes=notes,
            status=status,
        )

    record(
        "bcy-mss",
        "Braaten–Cohen–Yang / MSScvm (original MSS)",
        "Cloud masks and shadows",
        "Cloud/cloud-shadow classes, not recovered reflectance",
        "Landsat MSS four-band radiometry, solar geometry and DEM, following the original workflow",
        "https://github.com/jdbcode/MSScvm",
        "Reproduce original test/reference masks; independent cloud/shadow/snow labels with omission and commission",
        notes="Braaten, Cohen and Yang (2015), DOI 10.1016/j.rse.2015.08.006. The original MSS method is distinct from the Sentinel-2 threshold adaptation.",
    )
    record(
        "bcy-sentinel-adaptation",
        "BCY Sentinel-2 threshold adaptation",
        "Cloud masks and shadows",
        "Unknown / not detected / cloud candidate labels",
        "Native Sentinel-2 L1C TOA B03, B04 and B11 physical reflectance; explicit SWIR threshold",
        "https://custom-scripts.sentinel-hub.com/custom-scripts/sentinel-2/cby_cloud_detection/",
        "Snow, thin/cirrus cloud and bright-surface test sets; compare native QA and independent labels",
        notes="Evalscript SWIR threshold 0.1 differs from prose 0.2. RSLIB requires an explicit choice and rejects SR; no shadow processing or clear-sky certification. Equation implemented with attribution; the visualization script is not copied.",
        status="library_primitive_not_default_qa",
    )
    record(
        "fmask",
        "Fmask / Python Fmask",
        "Cloud masks and shadows",
        "Cloud, shadow, snow and clear masks",
        "Sensor/product-specific visible/NIR/SWIR, geometry, optional thermal/parallax inputs; declare implementation/version",
        "https://www.pythonfmask.org/en/latest/",
        "Independent scene-level and pixel cloud/shadow evaluation; native resolution, buffers and adjacency sensitivity",
        notes="Python Fmask is a specific implementation; do not assume it implements every later Fmask release or all sensors identically.",
    )
    record(
        "tasseled-cap-baig",
        "Tasseled cap: Baig 2014 OLI TOA",
        "Spectral transforms",
        "Brightness, greenness, wetness; dimensionless transforms",
        "Landsat-8 OLI calibrated TOA blue/green/red/NIR/SWIR1/SWIR2; exact band order",
        "https://doi.org/10.1080/2150704X.2014.915434",
        "Published coefficient vectors, nodata and band/radiometry guards; independent application validation",
        notes="Coefficient table cross-checked in NASA DEVELOP report 20220005937, Table B1. Existing RSLIB SR stacks are rejected by this profile. Wetness is not volumetric soil moisture.",
        status="library_primitive_toa_only",
    )
    record(
        "tasseled-cap-sr-2022",
        "Tasseled cap: Zhai et al. 2022 OLI SR/TOA",
        "Spectral transforms",
        "Processing-level-specific brightness, greenness and wetness",
        "Explicit Landsat-8 OLI SR or TOA profile, five- or six-band choice and coefficients verified from the original table",
        "https://doi.org/10.1016/j.rse.2022.112992",
        "Verify coefficient tables, sensor/product assumptions, spatial/seasonal transfer and comparison with reference transforms",
        notes="Publisher abstract inspected; full coefficient table not verified here. No invented or borrowed TM coefficients are bundled as OLI SR.",
    )
    record(
        "tasseled-cap-oli89-2026",
        "Harmonized OLI 8/9 SR tasseled cap (Wang et al. 2026)",
        "Spectral transforms",
        "OLI/OLI-2 SR transform components from underfly-derived coefficients",
        "Original published surface-reflectance coefficient profile and sensor/product conventions",
        "https://doi.org/10.1016/j.srs.2025.100353",
        "Obtain and verify full original tables and reproduce near-coincident underfly comparisons",
        notes="2026 Science of Remote Sensing publication; DOI contains 2025. Discovery/reference entry only, no bundled coefficients or local accuracy claim.",
    )
    record(
        "covariance-pca",
        "Centered covariance PCA",
        "Spectral transforms",
        "Component scores, loadings and explained variance; not material labels",
        "Complete QA-valid reflectance spectra, explicit band order and declared training population",
        "https://www.spectralpython.net/algorithms.html#principal-components",
        "Orthonormality, inverse reconstruction, masked training and reuse of the same basis across dates",
        notes="RSLIB uses unstandardized covariance PCA, deterministic sign orientation and immutable fitted arrays. Equal eigenvalues permit nonunique rotations. No per-date hidden refitting.",
        status="library_browser_tui_cli_observed_scene",
    )
    record(
        "mnf",
        "Minimum Noise Fraction / noise-adjusted PCA",
        "Spectral transforms",
        "Noise-whitened components and signal/noise ordering",
        "Calibrated spectral data and a defensible positive-definite noise covariance estimate",
        "https://www.spectralpython.net/class_func_glossary.html#mnf",
        "Known correlated-noise fixtures, noise-covariance sensitivity and retained spectral signal",
        notes="MNF is distinct from ordinary PCA. Spatial-difference noise estimates can mistake texture for noise; declare estimator and regularization.",
    )
    record(
        "ica-maf",
        "ICA and Maximum Autocorrelation Factors",
        "Spectral transforms",
        "Independent or spatially autocorrelated components with transform metadata",
        "Supported sample distribution, masks and declared spatial lag; exact whitening/normalization",
        "https://www.orfeo-toolbox.org/CookBook/Applications/app_DimensionalityReduction.html",
        "Convergence/restarts, lag sensitivity and independent task performance; do not assume abundance fractions are independent",
    )
    record(
        "vca",
        "Vertex Component Analysis (VCA)",
        "Spectral unmixing",
        "Geometric endmember spectra and selected source cells",
        "Linear mixing and pure-pixel assumptions, number of endmembers, projection branch and random seed",
        "https://www.orfeo-toolbox.org/CookBook/Applications/app_VertexComponentAnalysis.html",
        "Original Nascimento/Bioucas-Dias 2005 equations, pure-simplex recovery, both projection branches, degeneracy and independent spectral references",
        notes="RSLIB implements both Algorithm 1 branches, explicitly chosen without an invented SNR. Endmembers remain numbered and source-located; pure-material identity is unverified.",
        status="library_browser_tui_cli_observed_scene",
    )
    record(
        "fcls",
        "Fully constrained least squares (FCLS)",
        "Spectral unmixing",
        "Nonnegative sum-to-one fractions plus reflectance reconstruction residual",
        "Matched-band endmember library, physical spectra and explicit linear mixture model",
        "https://pysptools.sourceforge.io/abundance_maps.html",
        "Exact mixtures, boundary/outside-simplex cases, independent convex optimizer and optimality certificate",
        notes="RSLIB enumerates simplex faces for 2–8 endmembers, bounds chunk RAM and checks a convex first-order gap. It does not normalize NNLS and label that FCLS. Large libraries need a different solver.",
        status="library_browser_tui_cli_observed_scene",
    )
    for identifier, name, detail in [
        (
            "ppi",
            "Pixel Purity Index / FIPPI",
            "Random projection extrema; declare skewer budget and seed",
        ),
        ("nfindr", "N-FINDR", "Maximum-volume simplex search; declare initialization and restarts"),
        (
            "atgp",
            "Automatic Target Generation Process",
            "Sequential orthogonal-subspace endmember selection",
        ),
    ]:
        record(
            identifier,
            name,
            "Spectral unmixing",
            "Candidate endmembers and their source cells",
            "Complete spectra, dimensionality choice, pure-pixel assumptions and declared endmember count",
            "https://pysptools.sourceforge.io/eea.html",
            "Synthetic pure/mixed cases, initialization sensitivity, independent material references and VCA comparison",
            notes=detail,
        )
    record(
        "virtual-dimensionality",
        "HFC Virtual Dimensionality / ELM",
        "Spectral unmixing",
        "Estimated signal-source count, conditional on noise/model assumptions",
        "Spectral covariance/correlation, false-alarm setting and valid sample population",
        "https://www.orfeo-toolbox.org/CookBook/Applications/app_EndmemberNumberEstimation.html",
        "Known-source/noise cases and count stability across masks and sample sizes; never infer material identity from rank alone",
    )
    for identifier, name, target, contract in [
        (
            "spectral-angle",
            "Spectral Angle Mapper (SAM)",
            "Angle to reference spectra in radians/degrees",
            "Nonzero vectors with matched sensor responses; explicit angle units",
        ),
        (
            "spectral-divergence",
            "Spectral Information Divergence (SID)",
            "Dimensionless spectral divergence",
            "Positive normalized spectra and explicit zero/negative-value handling",
        ),
    ]:
        record(
            identifier,
            name,
            "Spectral detection",
            target,
            contract,
            "https://pysptools.sourceforge.io/classification.html",
            "Matched spectral-library and unknown-class tests; angle/divergence thresholds calibrated on independent data",
        )
    for identifier, name, detail in [
        (
            "rx",
            "RX anomaly detection",
            "Background Mahalanobis distance; anomaly is not a named target",
        ),
        (
            "matched-filter",
            "Covariance-weighted matched filter",
            "Reference-target response; not automatically an abundance fraction",
        ),
        (
            "ace",
            "Adaptive Coherence Estimator (ACE)",
            "Covariance-normalized target similarity; not a physical concentration",
        ),
    ]:
        record(
            identifier,
            name,
            "Spectral detection",
            detail,
            "Declared background/target spectra, covariance population, regularization and local/global windows",
            "https://www.spectralpython.net/algorithms.html#target-detectors",
            "Target-absent false alarms, spatial holdouts, contaminated-background tests and covariance conditioning",
        )
    record(
        "continuum-removal",
        "Continuum removal and absorption-feature extraction",
        "Imaging spectroscopy",
        "Continuum-normalized depths, positions and widths with wavelength units",
        "Wavelength-calibrated contiguous spectra, bad-band/atmospheric masks and a defined continuum interval",
        "https://pysptools.sourceforge.io/spectro.html",
        "Known absorption features and laboratory spectra convolved with sensor response; interval/noise sensitivity",
    )
    record(
        "haralick",
        "Haralick gray-level co-occurrence textures",
        "Spatial features",
        "Texture measures with declared quantization, direction and spatial support",
        "Single-channel raster, nodata-aware windows, physical pixel size, gray-level bins and offsets",
        "https://www.orfeo-toolbox.org/CookBook/Applications/app_HaralickTextureExtraction.html",
        "Hand-computed co-occurrence fixtures; quantization/resolution sensitivity and independent classification gains",
    )
    record(
        "mad",
        "Multivariate Alteration Detection (MAD)",
        "Change detection",
        "Canonical change variates, correlations and transform statistics",
        "Two exactly aligned multispectral dates, complete paired validity and conditioned covariance",
        "https://www.orfeo-toolbox.org/CookBook/Applications/app_MultivariateAlterationDetector.html",
        "Author reference-code comparison, unchanged controls, known changes and registration/atmosphere sensitivity",
    )
    record(
        "irmad",
        "Iteratively reweighted MAD (IR-MAD)",
        "Change detection",
        "Iteratively weighted change statistics and candidate invariant pixels",
        "Paired aligned data, robust covariance, convergence limits and explicit no-change weighting model",
        "https://www2.imm.dtu.dk/~aa/software.html",
        "Author-code comparison, conditioning/convergence, change prevalence and no-change probability calibration",
        notes="IR-MAD can support relative radiometric normalization; it does not replace atmospheric/BRDF correction or establish unchanged ground conditions.",
    )
    record(
        "landtrendr",
        "LandTrendr spectral-temporal segmentation",
        "Change detection",
        "Piecewise temporal trajectories and disturbance/recovery segments",
        "Long annual quality composites, index orientation and explicit segmentation/model-selection settings",
        "https://github.com/eMapR/LT-GEE",
        "Reference trajectories and independent disturbance timing/magnitude; short six-date stacks are not a valid substitute",
    )
    record(
        "phenology-smoothing",
        "Seasonal curves, phenometrics and temporal smoothing",
        "Agriculture and phenology",
        "Smoothed trajectories, seasonal timing and amplitudes with day/value units",
        "Actual timestamps, QA weights, sufficient seasonal sampling and declared interpolation/smoothing policy",
        "https://docs.digitalearthafrica.org/en/latest/sandbox/notebooks/Tools/gen/deafrica_tools.temporal.html",
        "Withheld dates/seasons, abrupt-change retention, edge effects and explicit observation versus estimated support",
        notes="Family entry, not an assertion that every smoother is equivalent or bundled. Whittaker, HANTS, Savitzky–Golay, LOESS and state-space methods require separate irregular-time and missing-data contracts.",
    )
    record(
        "response-resampling",
        "Spectral-response-aware band resampling",
        "Harmonization",
        "Reflectance on supported destination spectral responses, with unavailable bands missing",
        "Source/destination wavelengths, bandwidth or full response curves, physical reflectance and coverage masks",
        "https://www.spectralpython.net/algorithms.html#band-resampling",
        "Analytic response integrals and measured reference spectra; never synthesize an uncovered wavelength as an observation",
    )
    record(
        "torchgeo-transforms",
        "TorchGeo indices and EO model integrations",
        "Reusable EO software",
        "Band-aware indices/transforms and supported model/dataset interfaces",
        "Version-specific band order, physical calibration, tensor axes and exact model preprocessing",
        "https://docs.torchgeo.org/en/stable/api/transforms.html",
        "Parity with documented transforms, masks and model signatures; adapter-specific sensor/time contracts",
        notes="Stable 0.10.1 docs inspected: many normalized-difference indices plus EVI/SAVI. PCA appears as an example of supplied RandomGrayscale weights, not a fitted PCA implementation. The reviewed transform page does not document tasseled cap or VCA. Model docs include Presto, Tessera, Copernicus-FM, DOFA and others; reuse supported adapters after contract checks.",
    )
