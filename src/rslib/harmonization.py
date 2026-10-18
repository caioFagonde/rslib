"""Explicit sensor profiles and OLI-referenced spectral adjustment.

Coefficients: NASA HLS V2 algorithm table, retrieved 2026-10-16.
This operation alone does not reproduce HLS atmospheric correction or NBAR.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

COMMON_BANDS = ("blue", "green", "red", "nir", "swir16", "swir22")
REFERENCE = "https://hls.gsfc.nasa.gov/algorithms/"
COEFFICIENTS = {
    "sentinel-2a": (
        (0.9778, -0.0040),
        (1.0053, -0.0009),
        (0.9765, 0.0009),
        (0.9983, -0.0001),
        (0.9987, -0.0011),
        (1.0030, -0.0012),
    ),
    "sentinel-2b": (
        (0.9778, -0.0040),
        (1.0075, -0.0008),
        (0.9761, 0.0010),
        (0.9966, 0.0000),
        (1.0000, -0.0003),
        (0.9867, 0.0004),
    ),
    "sentinel-2c": (
        (0.9851, -0.0027),
        (1.0038, -0.0009),
        (0.9718, 0.0011),
        (0.9995, -0.0003),
        (0.9994, -0.0007),
        (0.9910, 0.0004),
    ),
}


@dataclass(frozen=True)
class SensorProfile:
    family: str
    platform: str
    already_harmonized: bool


def sensor_profile(item: dict) -> SensorProfile:
    collection = item.get("collection", "").lower()
    platform = str(item.get("properties", {}).get("platform", "")).lower().replace("_", "-")
    if collection.startswith("hlss30") or collection.startswith("hls-s30"):
        if not any(v in collection for v in ("v2", "002")):
            raise ValueError("HLS stacks require an explicitly versioned V2 collection")
        return SensorProfile("hls-s30", platform or "sentinel-2", True)
    if collection.startswith("hlsl30") or collection.startswith("hls-l30"):
        if not any(v in collection for v in ("v2", "002")):
            raise ValueError("HLS stacks require an explicitly versioned V2 collection")
        return SensorProfile("hls-l30", platform or "landsat-oli", True)
    if collection.startswith("sentinel-2"):
        if platform not in COEFFICIENTS:
            raise ValueError("Sentinel-2 stacks require explicit platform sentinel-2a/2b/2c")
        return SensorProfile("sentinel-2", platform, False)
    if "landsat-c2-l2" in collection:
        if platform not in {"landsat-8", "landsat-9"}:
            raise ValueError(
                "Common-band stacks support Landsat 8/9 OLI; older sensors need a separate profile"
            )
        return SensorProfile("landsat-oli", platform, False)
    raise ValueError(f"Unsupported optical stack collection: {collection}")


def stack_asset(item: dict, band: str, profile: SensorProfile) -> dict:
    """Resolve equivalent bands explicitly; never substitute broad B08 for B8A."""
    if band not in COMMON_BANDS and band not in {"scl", "qa_pixel", "qa_radsat", "fmask"}:
        raise ValueError(f"Unsupported stack band: {band}")
    assets = item.get("assets", {})
    if profile.family.startswith("hls-"):
        if band == "fmask":
            names = ["Fmask", "fmask", "FMASK"]
        elif band in COMMON_BANDS:
            suffixes = (
                ("02", "03", "04", "8A", "11", "12")
                if profile.family == "hls-s30"
                else ("02", "03", "04", "05", "06", "07")
            )
            suffix = suffixes[COMMON_BANDS.index(band)]
            names = [f"B{suffix}", f"B{suffix.lstrip('0')}", band]
        else:
            names = [band]
    elif profile.family == "sentinel-2" and band == "nir":
        names = ["B8A", "B08A", "nir08"]
    elif profile.family == "landsat-oli" and band in COMMON_BANDS:
        number = COMMON_BANDS.index(band) + 2
        names = [band, f"SR_B{number}", f"B{number:02d}", f"B{number}"]
        if band == "nir":
            names.insert(0, "nir08")
    else:
        from rslib.raster import ALIASES

        names = ALIASES.get(band, [band])
    for name in names:
        if name in assets:
            return {"key": name, **assets[name]}
    if profile.family == "sentinel-2" and band == "nir":
        raise ValueError("Comparable NIR requires Sentinel-2 B8A (narrow NIR), not B08")
    raise ValueError(f"Scene {item.get('id')} lacks required {band} asset ({', '.join(names)})")


def bandpass_adjust(
    values: np.ndarray, bands: tuple[str, ...], profile: SensorProfile
) -> tuple[np.ndarray, dict]:
    data = np.asarray(values, dtype="float32")
    if data.ndim != 3 or data.shape[0] != len(bands) or any(b not in COMMON_BANDS for b in bands):
        raise ValueError("Expected CYX reflectance with known common bands")
    if profile.already_harmonized:
        return data.copy(), {"method": "upstream HLS; no second adjustment", "reference": REFERENCE}
    if profile.family == "landsat-oli":
        return data.copy(), {"method": "OLI reference; identity bandpass", "reference": REFERENCE}
    coefficients = [COEFFICIENTS[profile.platform][COMMON_BANDS.index(b)] for b in bands]
    a, b = np.array(coefficients, dtype="float32").T
    return data * a[:, None, None] + b[:, None, None], {
        "method": "HLS V2 linear MSI-to-OLI bandpass coefficients applied to surface reflectance",
        "coefficients": {
            band: {"slope": float(c[0]), "offset": float(c[1])}
            for band, c in zip(bands, coefficients, strict=True)
        },
        "reference": REFERENCE,
        "limitations": "Spectral adjustment only. No BRDF normalization, common atmospheric reprocessing or image-based co-registration; not an HLS-equivalent product.",
    }


def hls_clear(fmask: np.ndarray) -> np.ndarray:
    """Conservative HLS V2: reject cloud/adjacency/shadow/snow/high aerosol/fill.

    Water (bit 5) remains valid. Cirrus bit 0 is reserved in V2; exclude if set.
    """
    values = np.asarray(fmask)
    valid = np.isfinite(values) & (values >= 0) & (values < 255) & (values == np.floor(values))
    bits = np.where(valid, values, 255).astype("uint8")
    return valid & ((bits & 0b11111) == 0) & ((bits >> 6) != 3)
