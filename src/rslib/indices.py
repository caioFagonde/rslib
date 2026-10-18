"""Reflectance-domain indices. Inputs must already share a grid and physical units."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import binary_dilation

INDEX_BANDS = {
    "ndvi": ("nir", "red"),
    "ndmi": ("nir", "swir16"),
    "nbr": ("nir", "swir22"),
    "evi": ("nir", "red", "blue"),
    "rgb": ("red", "green", "blue"),
}


def ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    a, b = np.broadcast_arrays(
        np.asarray(numerator, dtype="float32"), np.asarray(denominator, dtype="float32")
    )
    return np.divide(
        a,
        b,
        out=np.full(a.shape, np.nan, dtype="float32"),
        where=np.isfinite(a) & np.isfinite(b) & (np.abs(b) > 1e-8),
    )


def spectral_index(name: str, bands: dict[str, np.ndarray]) -> np.ndarray:
    if name == "evi":
        n, r, b = (bands[k] for k in INDEX_BANDS[name])
        return 2.5 * ratio(n - r, n + 6 * r - 7.5 * b + 1)
    if name not in INDEX_BANDS or name == "rgb":
        raise ValueError(f"Unknown scalar index: {name}")
    a, b = (bands[k] for k in INDEX_BANDS[name])
    return ratio(a - b, a + b)


def sentinel_clear(scl: np.ndarray, buffer: int = 1) -> np.ndarray:
    """Conservative SCL clear classes: vegetation, bare soil, water (4, 5, 6).

    Excludes unclassified/dark pixels, shadows, clouds, cirrus, snow and nodata.
    Buffer is in output grid pixels, not meters. Never dilate with iterations=0.
    """
    if not isinstance(buffer, int) or not 0 <= buffer <= 64:
        raise ValueError("Cloud buffer must be an integer from 0 to 64")
    invalid = ~np.isin(scl, [4, 5, 6])
    if buffer:
        invalid = binary_dilation(invalid, iterations=buffer)
    return ~invalid


def landsat_clear(qa_pixel: np.ndarray, qa_radsat: np.ndarray | None = None) -> np.ndarray:
    """Collection 2 QA_PIXEL bits 0–5: fill, dilated cloud, cirrus, cloud, shadow, snow."""
    qa = np.asarray(qa_pixel, dtype="uint16")
    clear = (qa & 0b111111) == 0
    if qa_radsat is not None:
        clear &= qa_radsat == 0
    return clear


def summarize(values: np.ndarray) -> dict:
    v = np.asarray(values)
    finite = v[np.isfinite(v)]
    return {
        "valid_pixels": int(finite.size),
        "total_pixels": int(v.size),
        "valid_fraction": float(finite.size / v.size) if v.size else 0.0,
        "mean": float(finite.mean()) if finite.size else None,
        "std": float(finite.std()) if finite.size else None,
        "p05": float(np.quantile(finite, 0.05)) if finite.size else None,
        "median": float(np.median(finite)) if finite.size else None,
        "p95": float(np.quantile(finite, 0.95)) if finite.size else None,
    }


def best_pixel_composite(stack: np.ndarray, quality: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Select the highest-quality finite observation. Ties prefer the first date.

    stack: (time, y, x); quality: same shape, larger is better. Returns values and
    source indices (-1 where every observation is invalid). No median cloud mixing.
    """
    if stack.ndim != 3 or quality.shape != stack.shape or stack.shape[0] == 0:
        raise ValueError("Expected matching nonempty (time, y, x) arrays")
    valid = np.isfinite(stack) & np.isfinite(quality)
    source = np.argmax(np.where(valid, quality, -np.inf), axis=0)
    values = np.take_along_axis(stack, source[None], axis=0)[0].astype("float32")
    missing = ~valid.any(axis=0)
    values[missing], source[missing] = np.nan, -1
    return values, source
