# Scientific methods and interpretation

Every quantity must retain units, grid, missing-data behavior, source, and method. A visually convincing layer is not evidence of a validated estimate.

## Optical calibration and quality

Indices operate on physical reflectance. Calibration is `reflectance = raw × scale + offset`, after nodata has been identified. STAC raster metadata is used for supported collections. Earth Search's legacy `sentinel-2-l2a` has inconsistent offset metadata; analysis rejects it and discovery defaults to `sentinel-2-c1-l2a`. This was confirmed against a live scene during development and is documented in the [provider's collection notes](https://github.com/Element84/earth-search/blob/main/docs/collections/sentinel-2-l2a.md).

For Planetary Computer Sentinel-2 scenes missing explicit calibration, the processing baseline selects the L2A DN convention: scale 0.0001, offset -0.1 for baseline ≥04.00, zero for earlier baselines. Missing baseline information fails instead of assuming a calibration. Landsat C2 L2 surface reflectance uses its published [USGS scaling](https://www.usgs.gov/faqs/how-do-i-use-a-scale-factor-landsat-level-2-science-products), with explicit STAC calibration taking priority.

Sentinel SCL classes 4/5/6 are accepted; all others, including unknown, dark, shadow, cirrus and snow, are excluded. This is intentionally conservative. [Class definitions](https://docs.sentinel-hub.com/api/latest/data/sentinel-2-l2a/) distinguish scene-level cloud percentage from pixel labels. Landsat QA_PIXEL bits 0–5 and QA_RADSAT provide analogous exclusions. Zero in QA_RADSAT is a valid no-saturation value, even if an asset incorrectly marks zero as nodata.

All bands share a target grid and use nearest-neighbor sampling before masking. This avoids bilinear contamination of clear target pixels by cloudy neighboring source pixels. Preview statistics remain sampled estimates: coarse grids may miss small clouds, nonuniform geographic pixel areas are not area-weighted, and a fraction of valid samples is not full-resolution clear-area coverage. Metric-grid processing and native-resolution QA are needed for quantitative zonal products.

The footprint planner greedily selects marginal geometric coverage weighted by scene cloud cover. It is a bounded heuristic, not an optimal acquisition plan or proof of cloud-free coverage. Pixel QA should verify a proposed plan before production analysis.

## Soil, carbon and hydraulic estimates

[SoilGrids documentation](https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_01.html) defines the encoded units. RSLIB converts SOC from dg/kg to g/kg, bulk density from cg/cm³ to g/cm³, coarse fragments from per mille to volume fraction, and texture from g/kg to mass fraction. It retains the six supported depth intervals.

For a mineral-soil layer:

`stock [Mg C/ha] = SOC [g/kg] × bulk density [g/cm³] × thickness [cm] × 0.1 × (1 − coarse volume fraction)`.

Layer stocks can be summed over nonoverlapping depths. Repeated-date comparisons additionally require equivalent soil mass/depth and sampling comparability. Multiplication of carbon stock change by 44/12 gives a CO₂ mass equivalence; it does not establish actual emissions, additionality, permanence or a verified carbon credit.

`independent_stock_mc` is a reproducible demonstration of distribution propagation. It uses independent clipped-normal SOC and bulk-density inputs and fixed thickness/coarse fraction. It does not turn marginal SoilGrids prediction quantiles into a joint or spatial uncertainty model.

The pedotransfer implementation follows [Saxton & Rawls (2006)](https://doi.org/10.2136/sssaj2005.0117), unadjusted fine-earth equations for wilting point, field capacity, saturation and saturated conductivity. Sand/clay use fractions; organic matter uses percent. Conductivity is converted from mm/h to m/s. No default SOC-to-OM conversion is imposed. The function rejects unsupported/nonphysical inputs; density, salinity, gravel and domain-specific calibration are not implicitly supplied.

## Classical spectral transforms and mixture analysis

[The classical-algorithm guide](CLASSICAL_ALGORITHMS.md) specifies implemented numerical and calibration contracts. Covariance PCA fits only complete declared training spectra, records its mean/loadings/eigenvalues and reuses that basis on application data. It is neither noise-whitened MNF nor a physical-variable retrieval. Independently fitted date-specific components cannot be interpreted as the same time-series variable.

VCA follows Nascimento and Bioucas-Dias (2005), Algorithm 1, with an explicitly selected affine/projective branch and recorded random seed. No measured SNR is invented. A linear mixing model and pure pixels are assumptions; geometric extremes can also represent illumination, residual cloud, atmosphere or outliers. Projected and actually observed selected spectra are both retained. FCLS solves the unweighted nonnegative sum-to-one least-squares problem for a small affinely independent library, reports reconstruction residuals and checks a convex optimality gap. Numerical optimality does not establish correct endmembers or material abundances. Components remain numbered pending independent reference spectra/labels.

The shared observed-scene workflow uses only QA-valid acquired spectra from one verified source, retains AOI/nodata and writes separate COGs and a report without modifying the source run. The earlier standalone satellite figure is a saved exploratory fit. The operational browser/TUI now execute the same spectral pipeline through durable jobs. Neither execution nor a reconstruction residual establishes independently validated material fractions.

The bundled Baig 2014 tasseled-cap profile requires Landsat-8 OLI **TOA** reflectance and rejects the operational SR stack. Brightness/greenness/wetness are dimensionless transforms, not direct biomass or water-content measurements. SR and other-sensor profiles require verified original coefficient tables. The Sentinel-2 BCY threshold adaptation requires native L1C TOA green/red/SWIR inputs and a caller-selected SWIR threshold. It is distinct from original Landsat-MSS MSScvm, lacks shadow processing and cannot certify clear conditions; native QA remains the operational default. Cloud/shadow omissions and commission require independent labeled evaluation before a policy change.

## ML and deep inference

Regression uses disjoint groups for fitting, conformal calibration and final testing. The test split never fits the model or interval radius. Calibration uses the finite-sample residual order statistic. The report retains feature names, seeds, group identities and test MAE/RMSE/R²/coverage. Grouping reduces obvious spatial leakage but is not buffered validation; exchangeability and transfer performance require independent assessment. Supply measured targets with units, sampling methods and provenance.

Torch inference accepts caller-supplied CHW features and a model returning NCHW values at a declared integer scale. Halo tiles retain context and write each output pixel once; nodata expands with scale. The caller supplies verified band order, normalization, model card, training-domain assumptions and appropriate receptive-field halo. The optional SEN2SRLite adapter uses independently downloaded and verified pretrained weights. No pretrained land-cover model or benchmark accuracy is bundled.

## Compositing, reconstruction and super-resolution

The operational [optical stack recipe](OPERATIONS.md) uses a projected, snapped common grid and equivalent sensor bands, including S2 B8A for OLI-equivalent NIR. Cloud QA is applied to each native band before area-weighted aggregation. Native QA buffering is in metres, and partial source coverage is included in output support. This differs from the original single-scene preview path, which still uses bounded nearest-neighbor WGS84 sampling.

Platform-specific [NASA HLS V2 bandpass coefficients](https://hls.gsfc.nasa.gov/algorithms/) on ordinary surface reflectance constitute partial spectral adjustment. They do not reproduce full HLS atmospheric/BRDF/geolocation processing. Preharmonized HLS V2 inputs are accepted without a second correction. A common grid aligns georeferencing; it does not independently prove subpixel image registration. All requested bands must have usable support for a complete spectrum.

Daily mosaics are UTC-day products with original per-pixel source identities. Regular scalar-index queries distinguish exact observed days, temporally interpolated days and unsupported gaps, retaining both acquisition brackets. Support fractions describe AOI pixel centers and exclude grid padding. They are not confidence intervals, and interpolation does not establish the true timing of abrupt change.

Whole-spectrum compositing selects one complete clear observation for each pixel. Quality scores are caller-defined; the L1 spectral medoid minimizes aggregate distance to eligible observed spectra. A medoid may favor older land cover after abrupt change; it is not automatically the latest state. Source indices refer to the original input order, and observation counts exclude incomplete spectra or invalid scores.

Temporal interpolation uses actual acquisition spacing, fills only fully bracketed gaps within a specified whole-interval limit, retains observed float32 values and never extrapolates. Its support labels are not confidence intervals. Interpolation can smear disturbances and cloud QA errors. A reconstruction merge keeps complete clear spectra and labels supplied model fills separately; passing standard deviations does not establish calibrated uncertainty. These are core contracts/baselines, not installed diffusion cloud-removal models.

The optional SEN2SRLite model consumes calibrated R,G,B,NIR surface reflectance on a native 10 m grid. It supplies model-derived detail at nominal 2.5 m spacing; it does not create new sensor measurements. Halo stitching of tile-global Fourier corrections is approximate. The CLI checks metric grid spacing and records checkpoint/source hashes and grid transforms. Input QA and verified band order remain caller duties. Avoid deriving supposedly finer carbon or hazard estimates from visual sharpness; validate the complete downstream method against independent measurements.

The [reconstruction research survey](RECONSTRUCTION_RESEARCH.md) separates measured implementation, available author code and proposed research. [OpenSR-test](https://github.com/ESAOpenSR/opensr-test) and [AllClear](https://allclear.cs.cornell.edu/) offer relevant evaluation starting points. A small local speed measurement does not establish state-of-the-art accuracy or full-scene throughput.

## Terrain and slope

Terrain derivatives require metric pixel dimensions. A DEM must be reprojected before passing degree-based cells. Surface models, bare-earth terrain, vertical references, grid rotation, horizontal/vertical co-registration and soil-layer alignment are separate concerns.

Static slope screening and the Rust transient model are different methods. See [HYDRO.md](HYDRO.md) for implemented boundary conditions and the remaining unsaturated physics. Neither a coarse SoilGrids prediction nor a DEM determines all geotechnical inputs required by the model.
