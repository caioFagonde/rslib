"""Unit-explicit mineral-soil calculations; local measurements remain essential."""

from __future__ import annotations

import numpy as np

# Stored SoilGrids values -> physical units used in this module.
SOILGRIDS_FACTORS = {
    "soc": (0.1, "g/kg"),
    "bdod": (0.01, "g/cm3"),
    "cfvo": (0.001, "volume fraction"),
    "sand": (0.001, "mass fraction"),
    "silt": (0.001, "mass fraction"),
    "clay": (0.001, "mass fraction"),
    "phh2o": (0.1, "pH"),
    "nitrogen": (0.01, "g/kg"),
}
DEPTHS_CM = ((0, 5), (5, 15), (15, 30), (30, 60), (60, 100), (100, 200))


def _range(name: str, value, low: float, high: float) -> np.ndarray:
    a = np.asarray(value, dtype="float64")
    if np.any(~np.isfinite(a) | (a < low) | (a > high)):
        raise ValueError(f"{name} must be finite and in [{low}, {high}]")
    return a


def decode_soilgrids(property: str, values: np.ndarray, *, nodata: float = -32768) -> np.ndarray:
    factor, _ = SOILGRIDS_FACTORS[property]
    values = np.asarray(values, dtype="float64")
    return np.where((values == nodata) | (values < 0), np.nan, values * factor)


def soilgrids_vrt(property: str, top_cm: int, bottom_cm: int, statistic: str = "mean") -> str:
    if property not in SOILGRIDS_FACTORS or (top_cm, bottom_cm) not in DEPTHS_CM:
        raise ValueError("Unknown SoilGrids property/depth")
    if statistic not in ("mean", "Q0.05", "Q0.5", "Q0.95"):
        raise ValueError("Unknown SoilGrids statistic")
    return f"https://files.isric.org/soilgrids/latest/data/{property}/{property}_{top_cm}-{bottom_cm}cm_{statistic}.vrt"


def soc_stock(soc_g_kg, bulk_density_g_cm3, thickness_cm, coarse_fraction=0.0) -> np.ndarray:
    """SOC stock in Mg C/ha = SOC[g/kg] × BD[g/cm³] × dz[cm] × 0.1 × (1-cf)."""
    c = _range("SOC g/kg", soc_g_kg, 0, 1000)
    bd = _range("bulk density g/cm3", bulk_density_g_cm3, 0.01, 3)
    dz = _range("thickness cm", thickness_cm, 0.001, 1000)
    cf = _range("coarse volume fraction", coarse_fraction, 0, 1)
    return c * bd * dz * 0.1 * (1 - cf)


def stock_change(
    initial_mg_c_ha: float, final_mg_c_ha: float, area_ha: float, years: float
) -> dict:
    """Positive stock gain implies negative potential atmospheric CO2 change.

    A stock difference alone is not an emissions inventory or verified credit.
    Equal soil mass, sampling depth, uncertainty and baseline comparability are external requirements.
    """
    _range("initial stock", initial_mg_c_ha, 0, 1e6)
    _range("final stock", final_mg_c_ha, 0, 1e6)
    _range("area ha", area_ha, 0.000001, 1e12)
    _range("years", years, 0.000001, 1e6)
    change = (final_mg_c_ha - initial_mg_c_ha) * area_ha
    return {
        "stock_change_mg_c": change,
        "potential_atmospheric_change_mg_co2": -change * 44 / 12,
        "annualized_potential_mg_co2": -change * 44 / 12 / years,
        "interpretation": "stock-change CO2 mass equivalent; not measured emissions or verified credits",
    }


def saxton_rawls(sand_fraction, clay_fraction, organic_matter_percent) -> dict[str, np.ndarray]:
    """Saxton & Rawls (2006), Table 1; unadjusted mineral fine earth.

    Sand/clay are fractions (0–1); OM is mass PERCENT (0–8). No assumed SOC→OM
    conversion. Conductivity is returned in m/s, converted from the paper's mm/h.
    Reject nonphysical predictions instead of clipping them into plausible outputs.
    DOI: 10.2136/sssaj2005.0117. No density, salinity or gravel adjustment is applied.
    """
    s = _range("sand fraction", sand_fraction, 0, 1)
    c = _range("clay fraction", clay_fraction, 0, 1)
    om = _range("organic matter percent", organic_matter_percent, 0, 8)
    if np.any(s + c > 1):
        raise ValueError("Sand + clay fractions cannot exceed one")
    t15 = (
        -0.024 * s
        + 0.487 * c
        + 0.006 * om
        + 0.005 * s * om
        - 0.013 * c * om
        + 0.068 * s * c
        + 0.031
    )
    wp = t15 + 0.14 * t15 - 0.02
    t33 = (
        -0.251 * s
        + 0.195 * c
        + 0.011 * om
        + 0.006 * s * om
        - 0.027 * c * om
        + 0.452 * s * c
        + 0.299
    )
    fc = t33 + 1.283 * t33**2 - 0.374 * t33 - 0.015
    ts33 = (
        0.278 * s + 0.034 * c + 0.022 * om - 0.018 * s * om - 0.027 * c * om - 0.584 * s * c + 0.078
    )
    saturation = fc + ts33 + 0.636 * ts33 - 0.107 - 0.097 * s + 0.043
    if np.any((wp <= 0) | (fc <= wp) | (saturation <= fc) | (saturation >= 1)):
        raise ValueError("Pedotransfer prediction is nonphysical/out of domain")
    pore_index = (np.log(fc) - np.log(wp)) / (np.log(1500) - np.log(33))
    ksat = 1930 * (saturation - fc) ** (3 - pore_index) / 3_600_000
    return {
        "theta_1500": wp,
        "theta_33": fc,
        "theta_s": saturation,
        "available_water_fraction": fc - wp,
        "ksat_m_s": ksat,
        "pore_size_index": pore_index,
    }


def independent_stock_mc(
    soc_mean: float,
    soc_sd: float,
    bd_mean: float,
    bd_sd: float,
    thickness_cm: float,
    coarse_fraction: float = 0,
    samples: int = 10_000,
    seed: int = 42,
) -> dict:
    """Illustrative independent truncated-normal propagation, not SoilGrids joint uncertainty.

    Input SDs must come from an explicit distribution assumption; marginal SoilGrids
    quantiles alone do not identify cross-property or spatial covariance.
    """
    soc_stock(soc_mean, bd_mean, thickness_cm, coarse_fraction)
    _range("SOC SD", soc_sd, 0, 1000)
    _range("BD SD", bd_sd, 0, 3)
    if not 100 <= samples <= 1_000_000:
        raise ValueError("samples must be between 100 and 1,000,000")
    rng = np.random.default_rng(seed)
    c = np.clip(rng.normal(soc_mean, soc_sd, samples), 0, 1000)
    bd = np.clip(rng.normal(bd_mean, bd_sd, samples), 0.01, 3)
    stocks = soc_stock(c, bd, thickness_cm, coarse_fraction)
    return {
        "median_mg_c_ha": float(np.median(stocks)),
        "q05": float(np.quantile(stocks, 0.05)),
        "q95": float(np.quantile(stocks, 0.95)),
        "seed": seed,
        "samples": samples,
        "assumption": "independent clipped normal SOC and bulk density; fixed thickness/coarse fraction; no spatial covariance",
    }
