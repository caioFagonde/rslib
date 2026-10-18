from __future__ import annotations

import numpy as np


def derivatives(dem_m: np.ndarray, pixel_width_m: float, pixel_height_m: float) -> dict:
    """Metric projected north-up DEM only. Gradients propagate missing data."""
    dem = np.asarray(dem_m, dtype="float64")
    if dem.ndim != 2 or min(dem.shape) < 3:
        raise ValueError("DEM must be a 2D array at least 3 × 3")
    if (
        not np.isfinite([pixel_width_m, pixel_height_m]).all()
        or min(pixel_width_m, pixel_height_m) <= 0
    ):
        raise ValueError("Pixel dimensions must be finite positive meters, not degrees")
    dy, dx = np.gradient(dem, pixel_height_m, pixel_width_m)
    slope = np.arctan(np.hypot(dx, dy))
    # Row direction is south; downslope compass bearing is atan2(-dx, dy).
    aspect = np.mod(np.degrees(np.arctan2(-dx, dy)), 360)
    aspect[np.hypot(dx, dy) < 1e-12] = np.nan
    azimuth, altitude = np.radians(315), np.radians(45)
    # East/north/up normal is (-dx, +dy, 1).
    illumination = (
        -dx * np.cos(altitude) * np.sin(azimuth)
        + dy * np.cos(altitude) * np.cos(azimuth)
        + np.sin(altitude)
    ) / np.sqrt(1 + dx * dx + dy * dy)
    return {
        "slope_deg": np.degrees(slope),
        "aspect_deg": aspect,
        "hillshade": np.clip(illumination, 0, 1),
    }


def infinite_slope(
    slope_deg, depth_m, cohesion_pa, friction_deg, unit_weight_n_m3, pressure_head_m=0.0
) -> np.ndarray:
    """Static infinite-slope screening; pressure head supplied externally. NOT TRIGRS.

    FS = [c + (γ z cos²β − γw ψ) tanφ] / [γ z sinβ cosβ].
    Vertical depth z, Pa, N/m³. No rainfall infiltration or transient hydrology.
    """
    vals = np.broadcast_arrays(
        *[
            np.asarray(v, dtype="float64")
            for v in (
                slope_deg,
                depth_m,
                cohesion_pa,
                friction_deg,
                unit_weight_n_m3,
                pressure_head_m,
            )
        ]
    )
    s, z, c, phi, gamma, head = vals
    if any(not np.isfinite(v).all() for v in vals) or np.any(
        (s <= 0) | (s >= 90) | (z <= 0) | (c < 0) | (phi < 0) | (phi >= 90) | (gamma <= 0)
    ):
        raise ValueError(
            "Invalid slope/material parameters; require 0 < slope < 90 and positive depth/unit weight"
        )
    beta, friction = np.radians(s), np.radians(phi)
    return (c + (gamma * z * np.cos(beta) ** 2 - 9810 * head) * np.tan(friction)) / (
        gamma * z * np.sin(beta) * np.cos(beta)
    )
