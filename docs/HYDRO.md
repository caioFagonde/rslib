# Native Rust infiltration and slope engine

This is an independent implementation of public mathematical reference material. No installed TRIGRS model, external Fortran binary or legacy input deck is required. The primary reference is [Baum, Savage & Godt, USGS OFR 2008-1159](https://pubs.usgs.gov/of/2008/1159/), especially the wet-initial-condition formulation. The implementation does not claim complete legacy parity.

## Equation map

| Component | Implementation |
| --- | --- |
| Initial pressure | `ψ₀(Z) = (Z − d) β`; `β = cos²δ − I_background / Ks` |
| Vertical diffusivity | `D1 = D0 / cos²δ` |
| Integrated erfc | `ierfc(x) = exp(−x²)/√π − x erfc(x)`; a tail expansion reduces cancellation |
| Infinite basal boundary | `g(Z,t) = 2√(D1t) ierfc(Z / (2√(D1t)))`, zero for `t ≤ 0` |
| Finite basal depth L | Image sum at early time; equivalent Neumann eigenfunction expansion at `D1t/L² > 0.25` |
| Rain pulses | Sum `(I/Ks) × [g(t−start) − g(t−end)]` over ordered intervals |
| Pressure limit | Downward-flow cap `ψ ≤ Zβ`, with both raw and capped values retained |
| Factor of safety | `tanφ/tanδ + [c − ψγw tanφ] / [γs Z sinδ cosδ]` |

The finite late-time response is

`g = D1t/L + L/3 − Z + Z²/(2L) − (2L/π²) Σ cos(nπZ/L) exp(−n²π²D1t/L²) / n²`.

This is an equivalent expansion of the linear diffusion boundary-value problem. Tests compare both expansions around the switching point, check the depth-integrated response against `D1t`, and verify the deep-boundary limit. Evaluation series have explicit convergence tolerances and fail if convergence is not achieved.

## Inputs and outputs

[examples/storm.json](https://github.com/caioFagonde/rslib/blob/main/examples/storm.json) contains the complete SI-unit contract. Depth is vertical, not slope-normal. Conductivity is m/s; hydraulic diffusivity is m²/s; pressure head is m; cohesion is Pa; soil unit weight is N/m³; time is s. Rain intervals are nonoverlapping piecewise-constant surface fluxes. `D0` is not guessed from a pedotransfer water-retention estimate. The water unit weight is 9810 N/m³.

Cells may have different material properties and finite/infinite boundaries. Output depths and times must be strictly increasing. Each cell returns a profile plus the minimum FS and its sampled critical time/depth. Output contains raw head, capped head and a cap flag. The minimum is over requested samples, not a continuous optimization. FS is not arbitrarily clipped to 10 for display.

Optional routing accepts a square-cell metric DEM in row-major order, matching the cell array. Excess supply is transferred to the steepest strictly lower D8 neighbor in descending-elevation order, where it can infiltrate. Rates are capped at Ks. Input, infiltrated and exported excess volumes are tracked for each interval. Terminal excess includes outlets and unresolved pits; no water is silently lost, but no depression storage or travel time is modeled. Without routing, balance volumes assume independent 1 m² columns.

`cargo test --workspace` covers special-function reference values, initial/surface limits, finite/infinite agreement, finite-column conservation, pulse splitting, pressure limits, routing runon/mass balance and input rejection. The kernel is parallelized with Rayon; JSON ordering follows input cell order. Rust float64 calculations are retained through serialization.

## Boundaries and next validation gates

Implemented physics assumes wet or tension-saturated homogeneous isotropic columns. Upward initial flow, unsupported/degenerate slopes and invalid material data are rejected. Flat cells should be masked or handled by a separately defined screening policy; they are not assigned invented hazard values.

Remaining work is substantial: unsaturated Gardner/Richards response, capillary fringe and moving-water-table coupling; upward initial conditions; flat/depression routing; richer rainfall spatial forcing; continuous critical-depth search; benchmark cases transcribed independently from published analyses; comparison with public legacy reference outputs; convergence/sensitivity studies; and field validation.

Do not infer a calibrated hazard probability from FS or from a model-generated color layer. The [actual solver showcase](showcase/08-rust-physics.png) plots a hypothetical scenario and is reproducible from the adjacent input/result JSON files.
