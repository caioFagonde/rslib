from __future__ import annotations

import numpy as np
from rasterio.features import rasterize
from rasterio.transform import from_bounds

from rslib.models import BBox


def plan_coverage(
    features: list[dict],
    bbox: BBox,
    *,
    target: float = 0.98,
    max_scenes: int = 20,
    grid_size: int = 128,
) -> dict:
    """Deterministic greedy footprint set cover with scene-cloud quality weighting.

    Geometry coverage is sampled; scene cloud fraction is a ranking heuristic,
    never an AOI clear-pixel guarantee. Requires later pixel QA verification.
    """
    if (
        not 0 < target <= 1
        or not 1 <= grid_size <= 512
        or not 1 <= max_scenes <= 200
        or len(features) > 1000
    ):
        raise ValueError("Coverage planner budget or target is invalid")
    transform = from_bounds(*bbox.bounds, grid_size, grid_size)
    candidates = []
    for item in features:
        if not item.get("geometry"):
            continue
        mask = rasterize(
            [(item["geometry"], 1)],
            out_shape=(grid_size, grid_size),
            transform=transform,
            dtype="uint8",
        ).astype(bool)
        cloud = item.get("properties", {}).get("eo:cloud_cover")
        quality = (
            1 - float(cloud) / 100
            if isinstance(cloud, (int, float)) and np.isfinite(cloud) and 0 <= cloud <= 100
            else 0.5
        )
        candidates.append((item, mask, max(0.01, quality)))
    covered = np.zeros((grid_size, grid_size), dtype=bool)
    chosen = []
    while candidates and len(chosen) < max_scenes and covered.mean() < target:
        scores = [np.count_nonzero(mask & ~covered) * quality for _, mask, quality in candidates]
        best = int(np.argmax(scores))
        if scores[best] <= 0:
            break
        item, mask, quality = candidates.pop(best)
        gained = np.count_nonzero(mask & ~covered) / covered.size
        covered |= mask
        chosen.append(
            {
                "id": item["id"],
                "collection": item.get("collection"),
                "marginal_footprint_fraction": gained,
                "scene_quality_weight": quality,
            }
        )
    return {
        "selected": chosen,
        "sampled_footprint_coverage": float(covered.mean()),
        "target": target,
        "target_reached": bool(covered.mean() >= target),
        "grid_size": grid_size,
        "limitation": "Sampled geographic footprint coverage, not cloud-free coverage; no global-optimality or acquisition-cost guarantee",
    }
