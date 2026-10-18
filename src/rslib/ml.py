"""Spatially grouped regression with an untouched test split and split conformal intervals."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def spatial_blocks(x_m, y_m, block_size_m: float = 1000) -> np.ndarray:
    """Coordinates must be in one metric projected CRS. Origin is fixed at (0, 0)."""
    x, y = np.broadcast_arrays(x_m, y_m)
    if (
        x.ndim != 1
        or not np.isfinite(x).all()
        or not np.isfinite(y).all()
        or not np.isfinite(block_size_m)
        or block_size_m <= 0
    ):
        raise ValueError("Supply finite 1D metric coordinates and positive block size")
    bx, by = np.floor(x / block_size_m).astype("int64"), np.floor(y / block_size_m).astype("int64")
    return np.array([f"{a}:{b}" for a, b in zip(bx, by, strict=True)])


@dataclass
class ConformalRegressor:
    estimator: object
    radius: float
    feature_names: list[str]
    report: dict

    def predict(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        x = np.asarray(x)
        if x.ndim != 2 or x.shape[1] != len(self.feature_names) or not np.isfinite(x).all():
            raise ValueError("Prediction features must be finite and match the training schema")
        mean = self.estimator.predict(x)
        return mean, mean - self.radius, mean + self.radius


def fit_grouped_conformal(
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    *,
    feature_names: list[str],
    alpha: float = 0.1,
    seed: int = 42,
    trees: int = 200,
) -> ConformalRegressor:
    """Train/calibrate/test groups never overlap. Calibration is never used for model fitting.

    Spatial blocking reduces leakage but is not buffered CV. Conformal marginal
    coverage requires exchangeability; spatial/temporal shift can break that assumption.
    Returned test coverage is empirical, not an accuracy or carbon-credit certificate.
    """
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    from sklearn.model_selection import GroupShuffleSplit

    x, y, groups = np.asarray(x), np.asarray(y), np.asarray(groups)
    if x.ndim != 2 or y.ndim != 1 or groups.ndim != 1 or len(x) != len(y) or len(y) != len(groups):
        raise ValueError("Expected aligned X[n,p], y[n], groups[n]")
    if len(feature_names) != x.shape[1] or len(set(feature_names)) != len(feature_names):
        raise ValueError("Feature names must be unique and match X columns")
    if not np.isfinite(x).all() or not np.isfinite(y).all() or np.unique(groups).size < 6:
        raise ValueError("Need finite training data and at least six spatial groups")
    if not 0.01 <= alpha <= 0.5 or not 10 <= trees <= 2000:
        raise ValueError("alpha must be in [.01,.5]; trees in [10,2000]")
    remaining, test = next(
        GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=seed).split(x, y, groups)
    )
    fit_rel, cal_rel = next(
        GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed + 1).split(
            x[remaining], y[remaining], groups[remaining]
        )
    )
    train, calibration = remaining[fit_rel], remaining[cal_rel]
    model = RandomForestRegressor(
        n_estimators=trees, min_samples_leaf=3, n_jobs=1, random_state=seed
    )
    model.fit(x[train], y[train])
    residuals = np.abs(y[calibration] - model.predict(x[calibration]))
    rank = math.ceil((len(residuals) + 1) * (1 - alpha))
    if rank > len(residuals):
        raise ValueError(
            "Calibration split is too small for requested alpha; collect more groups/samples"
        )
    radius = float(np.partition(residuals, rank - 1)[rank - 1])
    predicted = model.predict(x[test])
    test_groups = {
        name: sorted(str(v) for v in np.unique(groups[idx]))
        for name, idx in (("train", train), ("calibration", calibration), ("test", test))
    }
    report = {
        "method": "random-forest + grouped split conformal",
        "seed": seed,
        "alpha": alpha,
        "trees": trees,
        "feature_names": feature_names,
        "groups": test_groups,
        "samples": {"train": len(train), "calibration": len(calibration), "test": len(test)},
        "test": {
            "mae": float(mean_absolute_error(y[test], predicted)),
            "rmse": float(np.sqrt(mean_squared_error(y[test], predicted))),
            "r2": float(r2_score(y[test], predicted)) if len(test) > 1 else None,
            "interval_coverage": float(np.mean(np.abs(y[test] - predicted) <= radius)),
            "interval_width": 2 * radius,
        },
        "feature_importances": dict(
            zip(feature_names, model.feature_importances_.tolist(), strict=True)
        ),
        "limitations": "No buffered separation or domain-shift correction; intervals assume exchangeability. Supply measured labels with units and independently validate spatial/temporal transfer.",
    }
    return ConformalRegressor(model, radius, feature_names, report)
