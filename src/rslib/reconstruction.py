"""Shared output contract for cloud removal and image inpainting adapters."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Reconstruction:
    values: np.ndarray
    provenance: np.ndarray  # 0 unsupported, 1 observed, 3 model-derived
    model_std: np.ndarray | None


def preserve_observations(
    observed: np.ndarray,
    clear: np.ndarray,
    prediction: np.ndarray,
    *,
    model_std: np.ndarray | None = None,
) -> Reconstruction:
    """Merge a CHW model prediction without overwriting complete clear spectra.

    A model must supply all bands to fill a pixel. Unsupported predictions remain
    NaN. Optional standard deviations are passed through, not asserted calibrated;
    NaN on observed pixels means observation uncertainty was not supplied.
    """
    values, proposal = (
        np.asarray(observed, dtype="float32"),
        np.asarray(prediction, dtype="float32"),
    )
    mask = np.asarray(clear)
    if (
        values.ndim != 3
        or min(values.shape) < 1
        or proposal.shape != values.shape
        or mask.shape != values.shape[1:]
        or mask.dtype != np.bool_
    ):
        raise ValueError("Expected matching CHW observations/predictions and boolean HW clear mask")
    if values.size > 33_554_432:
        raise ValueError("Reconstruction budget exceeded")
    keep = mask & np.isfinite(values).all(axis=0)
    fill = ~keep & np.isfinite(proposal).all(axis=0)
    output = np.full_like(values, np.nan)
    output[:, keep], output[:, fill] = values[:, keep], proposal[:, fill]
    uncertainty = None
    if model_std is not None:
        std = np.asarray(model_std, dtype="float32")
        if std.shape != values.shape or np.any(np.isfinite(std) & (std < 0)) or np.isinf(std).any():
            raise ValueError("Standard deviation must match CHW and be nonnegative or NaN")
        uncertainty = np.where(fill[None], std, np.nan)
    labels = np.where(keep, 1, np.where(fill, 3, 0)).astype("uint8")
    return Reconstruction(output, labels, uncertainty)
