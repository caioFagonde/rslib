"""Near-coincident sensor agreement on native-QA-masked common-grid spectra.

This is an intercomparison, not calibration against ground truth. Temporal,
angular, atmospheric and registration differences remain in the residuals.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from rslib.indices import spectral_index
from rslib.stack import OpticalStack
from rslib.validation import load_verified_run


def _statistics(reference: np.ndarray, comparison: np.ndarray) -> dict:
    reference, comparison = reference.astype("float64"), comparison.astype("float64")
    error = comparison - reference
    centered_x, centered_y = reference - reference.mean(), comparison - comparison.mean()
    denominator = np.linalg.norm(centered_x) * np.linalg.norm(centered_y)
    return {
        "samples": int(error.size),
        "bias": float(error.mean()),
        "mae": float(np.abs(error).mean()),
        "rmse": float(np.sqrt(np.square(error).mean())),
        "median_difference": float(np.median(error)),
        "difference_p05": float(np.quantile(error, 0.05)),
        "difference_p95": float(np.quantile(error, 0.95)),
        "correlation": float(np.clip(np.dot(centered_x, centered_y) / denominator, -1, 1))
        if denominator > 1e-15
        else None,
    }


def _before_local_adjustment(values, bands, record):
    coefficients = record.get("adjustment", {}).get("coefficients")
    if not coefficients:
        return None
    try:
        slope = np.array([coefficients[b]["slope"] for b in bands], dtype="float64")
        offset = np.array([coefficients[b]["offset"] for b in bands], dtype="float64")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Incomplete recorded bandpass coefficients") from exc
    if not np.isfinite(slope).all() or not np.isfinite(offset).all() or np.any(slope <= 0):
        raise ValueError("Invalid recorded bandpass coefficients")
    return (values.astype("float64") - offset[:, None]) / slope[:, None]


def sensor_agreement(
    stack: OpticalStack, *, max_hours: float = 48, min_cells: int = 100, display_samples: int = 400
) -> dict:
    """Greedy closest-time, disjoint OLI/MSI pairs with measured clear overlap.

    All statistics use every common complete-spectrum cell whose center is in
    the requested AOI. Only scatter displays are subsampled. Before-adjustment
    spectra are recovered from recorded local affine coefficients; upstream HLS
    and unrecorded transforms cannot be undone and return no such comparison.
    """
    if not np.isfinite(max_hours) or not 0 < max_hours <= 168:
        raise ValueError("Pair separation must be positive and at most 168 hours")
    if not isinstance(min_cells, int) or not 1 <= min_cells <= 1_048_576:
        raise ValueError("Minimum common clear cells must be 1–1048576")
    if not isinstance(display_samples, int) or not 0 <= display_samples <= 1000:
        raise ValueError("Scatter sample count must be 0–1000")
    if "red" not in stack.bands or "nir" not in stack.bands:
        raise ValueError("Sensor agreement requires red and narrow NIR bands")
    reference = [
        i for i, o in enumerate(stack.observations) if o.get("family") in {"landsat-oli", "hls-l30"}
    ]
    comparison = [
        i for i, o in enumerate(stack.observations) if o.get("family") in {"sentinel-2", "hls-s30"}
    ]
    if not reference or not comparison:
        raise ValueError(
            "Sensor agreement requires both Landsat OLI and Sentinel-2 MSI observations"
        )
    candidates = []
    for left in reference:
        for right in comparison:
            separation = float(abs(stack.times[left] - stack.times[right]) / np.timedelta64(1, "h"))
            if separation <= max_hours:
                candidates.append((separation, left, right))
    candidates.sort(
        key=lambda p: (p[0], stack.observations[p[1]]["id"], stack.observations[p[2]]["id"])
    )
    inside, used, pairs, rejected = stack.analysis_mask(), set(), [], []
    total_cells = int(inside.sum())
    if not total_cells:
        raise ValueError("AOI has no common-grid cell centers")
    for separation, left, right in candidates:
        if left in used or right in used:
            continue
        a, b = stack.values[left], stack.values[right]
        common = inside & np.isfinite(a).all(axis=0) & np.isfinite(b).all(axis=0)
        count = int(common.sum())
        if count < min_cells:
            rejected.append(
                {
                    "reference_index": left,
                    "comparison_index": right,
                    "common_clear_cells": count,
                    "reason": "insufficient_common_clear_cells",
                }
            )
            continue
        used.update((left, right))
        a, b = a[:, common], b[:, common]
        before = _before_local_adjustment(b, stack.bands, stack.observations[right])
        sample = np.linspace(0, count - 1, min(display_samples, count), dtype=int)
        rows, cols = np.where(common)
        bands = []
        for k, band in enumerate(stack.bands):
            bands.append(
                {
                    "band": band,
                    "units": "1",
                    "current": _statistics(a[k], b[k]),
                    "before_local_bandpass": _statistics(a[k], before[k])
                    if before is not None
                    else None,
                    "scatter": {
                        "reference": a[k, sample].astype(float).tolist(),
                        "current": b[k, sample].astype(float).tolist(),
                        "before_local_bandpass": before[k, sample].tolist()
                        if before is not None
                        else None,
                    },
                }
            )
        ndvi_a = spectral_index("ndvi", {band: a[k] for k, band in enumerate(stack.bands)})
        ndvi_b = spectral_index("ndvi", {band: b[k] for k, band in enumerate(stack.bands)})
        finite_index = np.isfinite(ndvi_a) & np.isfinite(ndvi_b)
        norm = np.linalg.norm(a.astype("float64"), axis=0) * np.linalg.norm(
            b.astype("float64"), axis=0
        )
        spectral_valid = norm > 1e-15
        angles = np.rad2deg(
            np.arccos(
                np.clip(
                    np.sum(a.astype("float64") * b, axis=0)[spectral_valid] / norm[spectral_valid],
                    -1,
                    1,
                )
            )
        )

        def source(i):
            record = stack.observations[i]
            return {"index": i, **{k: record[k] for k in ["id", "platform", "datetime", "family"]}}

        pairs.append(
            {
                "reference": source(left),
                "comparison": source(right),
                "separation_hours": separation,
                "common_clear_cells": count,
                "common_clear_fraction": count / total_cells,
                "bands": bands,
                "ndvi": _statistics(ndvi_a[finite_index], ndvi_b[finite_index])
                if finite_index.any()
                else None,
                "spectral_angle": {
                    "units": "degrees",
                    "samples": int(angles.size),
                    "median": float(np.median(angles)) if angles.size else None,
                    "p95": float(np.quantile(angles, 0.95)) if angles.size else None,
                },
                "scatter_cells": {"rows": rows[sample].tolist(), "columns": cols[sample].tolist()},
                "before_local_bandpass_available": before is not None,
            }
        )
    return {
        "schema_version": "rslib-sensor-agreement/1",
        "max_hours": max_hours,
        "min_cells": min_cells,
        "grid": stack.grid.metadata(),
        "aoi_cells": total_cells,
        "pairs": pairs,
        "unpaired_source_indices": [i for i in reference + comparison if i not in used],
        "rejected_pairs": rejected,
        "pairing": "Greedy closest UTC timestamp within the separation limit, with common clear support; each source used at most once",
        "difference_sign": "Sentinel-2 MSI minus Landsat OLI",
        "scatter_sampling": "Deterministic equally spaced row-major common-clear cells; metrics use all common clear cells",
        "limitations": [
            "Agreement is not accuracy against ground truth. Real temporal change, BRDF, atmospheric correction, bandpass, point-spread function and registration differences all affect residuals.",
            "Only native-QA-clear complete spectra on the existing common grid are compared. Cloudy areas and other dates are not represented. Shared grids do not establish image-based coregistration.",
            "Before-local-bandpass values reverse only recorded affine coefficients on the same resampled, QA-masked cells, subject to floating-point rounding. They do not undo upstream HLS processing or reconstruct original native-grid pixels.",
            "Pixels are spatially correlated. Counts are paired cells, not independent replicates. No statistical significance, uncertainty calibration or automatic acceptance threshold is inferred.",
            "Closest-first disjoint matching is a bounded heuristic, not a globally optimal pairing. No scene is duplicated across accepted pairs, and insufficient clear overlap remains explicit.",
        ],
    }


def compare_run(directory: Path, *, max_hours: float = 48, min_cells: int = 100) -> dict:
    stack, report, digests = load_verified_run(directory)
    result = sensor_agreement(stack, max_hours=max_hours, min_cells=min_cells)
    return {
        **result,
        "run_id": report["id"],
        "synthetic": report["synthetic"],
        "input_sha256": digests,
    }
