"""Bounded elevation mosaics for direct, georeferenced browser terrain meshes."""

from __future__ import annotations

import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

from rslib.models import BBox
from rslib.raster import Grid, read_band, write_cog


def terrarium_encode(elevation_m: np.ndarray) -> np.ndarray:
    """Mapzen RGB encoding at 1/256 m; requires a finite display surface."""
    values = np.asarray(elevation_m, dtype="float64")
    if not np.isfinite(values).all() or np.any((values < -32768) | (values >= 32768)):
        raise ValueError("Terrain display requires finite elevations in [-32768,32768) m")
    fixed = np.clip(np.rint((values + 32768) * 256), 0, 16_777_215).astype("uint32")
    return np.stack([(fixed >> 16) & 255, (fixed >> 8) & 255, fixed & 255], axis=-1).astype("uint8")


def build_surface(items: list[dict], bbox: BBox, output_root: Path, size: int = 256) -> dict:
    if not items or len(items) > 8:
        raise ValueError("Need one to eight DEM tiles; reduce the AOI")
    grid = Grid.preview(bbox, size)
    for item in items:
        if item.get("collection") != "cop-dem-glo-30" or "data" not in item.get("assets", {}):
            raise ValueError("Terrain surface requires Copernicus GLO-30 data assets")
    with ThreadPoolExecutor(max_workers=2) as executor:
        arrays = list(
            executor.map(lambda item: read_band(item["assets"]["data"]["href"], grid), items)
        )
    values = np.full((grid.height, grid.width), np.nan, dtype="float32")
    for array in arrays:
        fill = ~np.isfinite(values) & np.isfinite(array)
        values[fill] = array[fill]
    valid = np.isfinite(values)
    coverage = float(valid.mean())
    if coverage < 0.98:
        raise ValueError(
            f"DEM coverage is only {coverage:.1%}; reduce the AOI or supply missing tiles"
        )
    display = values.copy()
    if not valid.all():
        # Rendering only. Original missing values remain missing in the exported DEM.
        nearest = distance_transform_edt(~valid, return_distances=False, return_indices=True)
        display[~valid] = values[tuple(nearest[:, ~valid])]
    run_id = uuid.uuid4().hex
    directory = output_root / run_id
    directory.mkdir(parents=True)
    Image.fromarray(terrarium_encode(display)).save(directory / "elevation.png")
    write_cog(directory / "elevation.tif", values, grid)
    report = {
        "id": run_id,
        "schema_version": "rslib-surface/1",
        "bbox": list(bbox.bounds),
        "grid": grid.metadata(),
        "source": "Copernicus DEM GLO-30",
        "vertical_reference": "EGM2008 orthometric height; digital surface model",
        "sources": [
            {"id": item["id"], "href": item["assets"]["data"]["href"].split("?")[0]}
            for item in items
        ],
        "source_valid_fraction": coverage,
        "display_filled_pixels": int((~valid).sum()),
        "rendering": "Nearest-filled small voids for display only; elevation.tif retains nodata. Geographic preview grid, not a metric terrain-analysis grid.",
        "elevation_url": f"/api/runs/{run_id}/elevation.png",
        "cog_url": f"/api/runs/{run_id}/elevation.tif",
        "manifest_url": f"/api/runs/{run_id}/manifest.json",
        "outputs": [
            {"path": p, "sha256": hashlib.sha256((directory / p).read_bytes()).hexdigest()}
            for p in ["elevation.png", "elevation.tif"]
        ],
    }
    (directory / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
