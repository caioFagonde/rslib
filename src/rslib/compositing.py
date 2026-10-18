"""Observation-preserving multispectral compositing on caller-aligned grids."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Composite:
    values: np.ndarray  # C,H,W: one complete observed spectrum per output pixel
    source_index: np.ndarray  # H,W; -1 where missing
    observation_count: np.ndarray  # H,W; number of eligible complete spectra
    method: str


def composite(
    stack: np.ndarray,
    clear: np.ndarray,
    *,
    quality: np.ndarray | None = None,
    method: str = "quality",
    band_scale: np.ndarray | None = None,
) -> Composite:
    """TCYX cube and TYX clear mask, already calibrated and co-registered.

    Quality selection maximizes a caller-defined score. Spectral medoid minimizes
    the sum of L1 distances to eligible observed spectra; each band may be divided
    by a fixed positive scale. Both select one WHOLE spectrum and retain its date
    index. Ties select the first input observation. No cloud pixels are synthesized.
    Medoid is an O(T²CYX) bounded reference implementation, not a distributed cube.
    """
    values = np.asarray(stack, dtype="float32")
    clear = np.asarray(clear)
    if (
        values.ndim != 4
        or min(values.shape) < 1
        or clear.shape != (values.shape[0], *values.shape[2:])
    ):
        raise ValueError("Expected matching nonempty TCYX cube and TYX clear mask")
    if clear.dtype != np.bool_ or values.size > 33_554_432:
        raise ValueError("Clear mask must be boolean; cube budget is 32 million samples")
    if values.shape[0] > 65535:
        raise ValueError("Too many time steps")
    valid = clear & np.isfinite(values).all(axis=1)
    if method == "quality":
        if quality is None or np.shape(quality) != valid.shape:
            raise ValueError("Quality method needs a TYX score, larger is better")
        quality = np.asarray(quality, dtype="float32")
        valid &= np.isfinite(quality)
        scores = np.where(valid, quality, -np.inf)
        source = scores.argmax(axis=0)
    elif method == "medoid":
        if values.shape[0] ** 2 * np.prod(values.shape[1:]) > 200_000_000:
            raise ValueError("Medoid pair-distance budget exceeded; reduce time span or tile AOI")
        scales = (
            np.ones(values.shape[1], dtype="float32")
            if band_scale is None
            else np.asarray(band_scale, dtype="float32")
        )
        if (
            scales.shape != (values.shape[1],)
            or not np.isfinite(scales).all()
            or np.any(scales <= 0)
        ):
            raise ValueError("Need a positive finite scale per spectral band")
        normalized = np.where(valid[:, None], values / scales[None, :, None, None], 0)
        best = np.full(values.shape[2:], np.inf, dtype="float64")
        source = np.zeros(values.shape[2:], dtype="int64")
        for i in range(values.shape[0]):
            distances = np.abs(normalized - normalized[i]).sum(axis=1, dtype="float64")
            score = np.where(valid, distances, 0).sum(axis=0)
            take = valid[i] & (score < best)
            best[take], source[take] = score[take], i
    else:
        raise ValueError("Composite method must be quality or medoid")
    y, x = np.indices(values.shape[2:])
    result = values[source, :, y, x].transpose(2, 0, 1).copy()
    count = valid.sum(axis=0, dtype="uint16")
    result[:, count == 0] = np.nan
    source[count == 0] = -1
    return Composite(result, source.astype("int32"), count, method)
