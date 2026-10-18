"""Irregular time-series interpolation with explicit support and gap limits."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TemporalResult:
    values: np.ndarray
    provenance: np.ndarray  # 0 missing, 1 observed, 2 temporal interpolation
    left_index: np.ndarray
    right_index: np.ndarray
    bracket_days: np.ndarray


def interpolate_gaps(
    values: np.ndarray, times: np.ndarray, *, max_gap_days: float
) -> TemporalResult:
    """Linearly fill interior NaNs in T... values using actual datetime64 spacing.

    The WHOLE bracketing interval must fit max_gap_days. No extrapolation. Clear
    observations are copied exactly; abrupt land-cover changes are not inferred.
    This is an auditable baseline, not a cloud-removal neural model or a calibrated
    uncertainty estimator. Cloud/shadow QA must already be represented as NaNs.
    """
    source = np.asarray(values, dtype="float32")
    dates = np.asarray(times)
    if source.ndim < 1 or source.shape[0] < 1 or source.size > 16_777_216:
        raise ValueError("Expected nonempty T... array within the 16-million sample budget")
    if dates.shape != (source.shape[0],) or dates.dtype.kind != "M" or np.isnat(dates).any():
        raise ValueError("Times must be a complete datetime64 vector matching time axis")
    if np.datetime_data(dates.dtype)[0] in {"Y", "M", "generic"}:
        raise ValueError("Acquisition timestamps require day or finer calendar precision")
    days = (dates - dates[0]) / np.timedelta64(1, "D")
    if np.any(np.diff(days) <= 0) or not np.isfinite(days).all():
        raise ValueError("Observation times must be strictly increasing")
    if not np.isfinite(max_gap_days) or max_gap_days <= 0:
        raise ValueError("max_gap_days must be positive and finite")
    shape = source.shape
    flat = source.reshape(shape[0], -1)
    output = flat.copy()
    labels = np.empty(flat.shape, dtype="uint8")
    left_output, right_output = (
        np.empty(flat.shape, dtype="int32"),
        np.empty(flat.shape, dtype="int32"),
    )
    gap_output = np.empty(flat.shape, dtype="float32")
    # Keep intermediate arrays bounded independently of AOI width. Returned
    # support/provenance arrays remain materialized within the sample budget.
    chunk_columns = max(1, 131072 // shape[0])
    for start in range(0, flat.shape[1], chunk_columns):
        stop = min(flat.shape[1], start + chunk_columns)
        block = flat[:, start:stop]
        observed = np.isfinite(block)
        idx = np.broadcast_to(np.arange(shape[0], dtype="int32")[:, None], block.shape)
        left = np.maximum.accumulate(np.where(observed, idx, -1), axis=0)
        right = np.minimum.accumulate(np.where(observed, idx, shape[0])[::-1], axis=0)[::-1]
        supported = (left >= 0) & (right < shape[0])
        left_safe, right_safe = np.clip(left, 0, shape[0] - 1), np.clip(right, 0, shape[0] - 1)
        gap = days[right_safe] - days[left_safe]
        fill = ~observed & supported & (gap <= max_gap_days) & (gap > 0)
        weight = np.divide(
            days[:, None] - days[left_safe], gap, out=np.zeros_like(gap), where=gap > 0
        )
        col = np.arange(block.shape[1])[None, :]
        values = np.where(observed, block, np.nan)
        interpolated = block[left_safe, col] * (1 - weight) + block[right_safe, col] * weight
        values[fill] = interpolated[fill]
        output[:, start:stop] = values
        available = observed | fill
        labels[:, start:stop] = np.where(observed, 1, np.where(fill, 2, 0))
        left_output[:, start:stop], right_output[:, start:stop] = (
            np.where(available, left, -1),
            np.where(available, right, -1),
        )
        gap_output[:, start:stop] = np.where(available, gap, np.nan)
    return TemporalResult(
        output.reshape(shape),
        labels.reshape(shape),
        left_output.reshape(shape),
        right_output.reshape(shape),
        gap_output.reshape(shape),
    )
