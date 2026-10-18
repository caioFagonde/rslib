"""Whole-date holdouts for temporal reconstruction, with a paired baseline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from rslib.indices import INDEX_BANDS, spectral_index
from rslib.stack import OpticalStack
from rslib.timeseries import interpolate_gaps


def _metrics(error: np.ndarray) -> dict:
    error = np.asarray(error, dtype="float64")
    return {
        "samples": int(error.size),
        "mae": float(np.abs(error).mean()) if error.size else None,
        "rmse": float(np.sqrt(np.square(error).mean())) if error.size else None,
        "bias": float(error.mean()) if error.size else None,
    }


def validate_series(stack: OpticalStack, *, index: str = "ndvi", max_gap_days: float = 20) -> dict:
    """Exclude every sensor on a held-out UTC day before predicting its values.

    Linear interpolation and nearest-bracket persistence are scored on exactly
    the same clear held-out cells. Both use only valid training observations;
    neither extrapolates or crosses a bracket longer than max_gap_days. The
    nearest baseline chooses the earlier observation on an equal-distance tie.
    """
    if index not in INDEX_BANDS or index == "rgb":
        raise ValueError("Choose a scalar optical index")
    if not np.isfinite(max_gap_days) or not 0 < max_gap_days <= 90:
        raise ValueError("Maximum bracket must be positive and at most 90 days")
    daily = stack.daily()
    if len(daily.days) < 3:
        raise ValueError("Temporal holdouts require at least three distinct acquisition days")
    values = spectral_index(
        index, {b: daily.values[:, stack.bands.index(b)] for b in INDEX_BANDS[index]}
    )
    inside = stack.analysis_mask()
    values[:, ~inside] = np.nan
    folds, linear_errors, nearest_errors = [], [], []
    y, x = np.indices(inside.shape)
    times = stack.times.astype("datetime64[D]")
    total_clear = 0
    for held, day in enumerate(daily.days):
        target = values[held]
        truth = np.isfinite(target)
        eligible = int(truth.sum())
        total_clear += eligible
        training = values.copy()
        training[held] = np.nan  # Remove the complete day, across every sensor.
        filled = interpolate_gaps(training, daily.days, max_gap_days=max_gap_days)
        scored = truth & (filled.provenance[held] == 2)
        left = np.maximum(filled.left_index[held], 0)
        right = np.maximum(filled.right_index[held], 0)
        before = (day - daily.days[left]) / np.timedelta64(1, "D")
        after = (daily.days[right] - day) / np.timedelta64(1, "D")
        nearest = values[np.where(before <= after, left, right), y, x]
        linear_error = filled.values[held][scored].astype("float64") - target[scored]
        nearest_error = nearest[scored].astype("float64") - target[scored]
        linear_errors.append(linear_error)
        nearest_errors.append(nearest_error)
        # No fold is dropped because it could not be reconstructed. Edge dates
        # and cloud gaps with no admissible training brackets stay in coverage.
        folds.append(
            {
                "day": str(day),
                "held_out_clear_cells": eligible,
                "scored_cells": int(scored.sum()),
                "scored_fraction": float(scored.sum() / eligible) if eligible else None,
                "linear": _metrics(linear_error),
                "nearest": _metrics(nearest_error),
                "median_bracket_days": float(np.median(filled.bracket_days[held][scored]))
                if scored.any()
                else None,
                "platforms": sorted(
                    {o["platform"] for i, o in enumerate(stack.observations) if times[i] == day}
                ),
                "sources": [o["id"] for i, o in enumerate(stack.observations) if times[i] == day],
            }
        )
    linear, nearest = (
        _metrics(np.concatenate(linear_errors)),
        _metrics(np.concatenate(nearest_errors)),
    )
    return {
        "schema_version": "rslib-temporal-validation/1",
        "index": index,
        "units": "1",
        "max_gap_days": max_gap_days,
        "acquisition_days": len(daily.days),
        "method": "Leave one complete UTC acquisition day out, across all sensors; reconstruct using remaining clear days",
        "baseline": "Nearest admissible bracket observation, tie to earlier; paired cells and identical bracket limit",
        "summary": {
            "held_out_clear_cells": total_clear,
            "scored_cells": linear["samples"],
            "scored_fraction": linear["samples"] / total_clear if total_clear else None,
            "scored_dates": sum(f["scored_cells"] > 0 for f in folds),
            "linear": linear,
            "nearest": nearest,
        },
        "folds": folds,
        "limitations": [
            "Clear satellite observations are the withheld reference, not independent ground truth. Residuals also include sensor, atmospheric and registration differences.",
            "Scoring excludes cells without admissible training brackets. Coverage includes every held-out clear cell, including edge dates; a low error on a small scored subset does not establish reliable gap filling.",
            "Whole-date exclusion prevents same-day sensor leakage. Cloud-free holdouts do not reproduce the distribution of genuinely cloud-obscured conditions.",
            "Neighboring pixels are correlated. Sample counts are cell-date comparisons, not independent replicates; no confidence interval or statistical superiority is claimed.",
            "This retrospective test uses observations before and after the held-out date. It does not validate causal forecasting, calibration, harmonization, or per-pixel uncertainty.",
        ],
    }


def verified_run_metadata(directory: Path) -> tuple[dict, dict]:
    manifest = directory / "manifest.json"
    report = json.loads(manifest.read_text())
    if report.get("schema_version") != "rslib-stack-workflow/1":
        raise ValueError("This run is not an optical stack")
    path = directory / "stack.npz"
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    recorded = next((o["sha256"] for o in report["outputs"] if o["path"] == "stack.npz"), None)
    if digest != recorded:
        raise ValueError("Stack checksum differs from the published run manifest")
    return (
        report,
        {
            "stack.npz": digest,
            "manifest.json": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        },
    )


def load_verified_run(directory: Path) -> tuple[OpticalStack, dict, dict]:
    report, digests = verified_run_metadata(directory)
    return OpticalStack.load(directory / "stack.npz"), report, digests


def validate_run(directory: Path) -> dict:
    stack, report, digests = load_verified_run(directory)
    result = validate_series(
        stack,
        index=report["request"]["index"],
        max_gap_days=report["request"]["max_gap_days"],
    )
    return {
        **result,
        "run_id": report["id"],
        "synthetic": report["synthetic"],
        "input_sha256": digests,
    }
