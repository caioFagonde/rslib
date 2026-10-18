"""Different native grids, five platforms, clouds and known synthetic spectral bias."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from rslib.harmonization import COEFFICIENTS, COMMON_BANDS
from rslib.models import BBox
from rslib.preparation import metric_grid
from rslib.stack import Observation

DEMO_BBOX = BBox(west=-44.66, south=-22.41, east=-44.64, north=-22.39)


def create_stack_demo(root: Path) -> list[Observation]:
    root.mkdir(parents=True, exist_ok=True)
    catalog = root / "items.json"
    if catalog.exists():
        existing = json.loads(catalog.read_text())
        if isinstance(existing, dict) and existing.get("schema") == 3:
            return [Observation(record["item"], "local") for record in existing["records"]]
    grid = metric_grid(DEMO_BBOX)
    x0, y0 = grid.transform.c - 180, grid.transform.f + 180
    width, height = grid.width * 30 + 360, grid.height * 30 + 360
    days = [0, 5, 10, 20, 25, 30, 40, 45]
    platforms = [
        "sentinel-2a",
        "landsat-8",
        "sentinel-2b",
        "sentinel-2c",
        "landsat-9",
        "sentinel-2a",
        "landsat-8",
        "landsat-9",
    ]
    records = []
    for number, (day, platform) in enumerate(zip(days, platforms, strict=True)):
        sentinel = platform.startswith("sentinel")
        directory = root / f"{platform}-{day:02d}"
        directory.mkdir(exist_ok=True)
        assets = {}
        for band in (*COMMON_BANDS, "qa"):
            resolution = (
                (20 if band in {"nir", "swir16", "swir22", "qa"} else 10) if sentinel else 30
            )
            # Deliberate half-pixel Landsat origin offset; all output aligns later.
            origin_x, origin_y = x0 + (0 if sentinel else 15), y0 + (0 if sentinel else 15)
            transform = from_origin(origin_x, origin_y, resolution, resolution)
            cols, rows = int(np.ceil(width / resolution)), int(np.ceil(height / resolution))
            y, x = np.mgrid[:rows, :cols]
            u = (origin_x + (x + 0.5) * resolution - x0) / width
            v = (y0 - (origin_y - (y + 0.5) * resolution)) / height
            cloud = (u - (0.15 + 0.095 * number)) ** 2 + (v - 0.5) ** 2 < 0.13**2
            cloud |= (u - 0.72) ** 2 + (v - (0.13 + 0.075 * number)) ** 2 < 0.085**2
            if band == "qa":
                values = np.where(cloud, 9 if sentinel else 1 << 3, 4 if sentinel else 0).astype(
                    "uint16"
                )
                key = "scl" if sentinel else "qa_pixel"
                scale, offset = 1, 0
            else:
                texture = 0.015 * np.sin(u * 35) + 0.012 * np.cos(v * 27)
                reflectance = {
                    "blue": 0.07 + texture / 2,
                    "green": 0.12 + texture,
                    "red": 0.14 + texture / 2,
                    "nir": 0.38 + 0.08 * np.sin(day / 45 * np.pi) + texture,
                    "swir16": 0.23 + texture,
                    "swir22": 0.17 + texture,
                }[band]
                if day >= 28:
                    disturbance = (u > 0.43) & (u < 0.68) & (v > 0.35) & (v < 0.72)
                    reflectance = np.where(
                        disturbance, reflectance * (0.65 if band == "nir" else 1.15), reflectance
                    )
                reflectance = np.where(cloud, 0.85, reflectance)
                if sentinel:
                    a, b = COEFFICIENTS[platform][COMMON_BANDS.index(band)]
                    reflectance = (reflectance - b) / a
                scale, offset = (0.0001, 0) if sentinel else (0.0000275, -0.2)
                values = np.rint((reflectance - offset) / scale).astype("uint16")
                key = "nir08" if band == "nir" and sentinel else band
            path = directory / f"{key}.tif"
            with rasterio.open(
                path,
                "w",
                driver="GTiff",
                width=cols,
                height=rows,
                count=1,
                dtype=values.dtype,
                crs=grid.crs,
                transform=transform,
            ) as dst:
                dst.write(values, 1)
            assets[key] = {
                "href": str(path.resolve()),
                "raster:bands": [{"scale": scale, "offset": offset}],
            }
            if band == "qa" and not sentinel:
                saturation = directory / "qa_radsat.tif"
                with rasterio.open(
                    saturation,
                    "w",
                    driver="GTiff",
                    width=cols,
                    height=rows,
                    count=1,
                    dtype="uint16",
                    crs=grid.crs,
                    transform=transform,
                    nodata=0,
                ) as dst:
                    dst.write(np.zeros((rows, cols), dtype="uint16"), 1)
                assets["qa_radsat"] = {"href": str(saturation.resolve())}
        date = str(np.datetime64("2026-06-01") + np.timedelta64(day, "D"))
        item = {
            "type": "Feature",
            "id": f"synthetic-{platform}-{day:02d}",
            "collection": "sentinel-2-c1-l2a" if sentinel else "landsat-c2-l2",
            "bbox": list(DEMO_BBOX.bounds),
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [DEMO_BBOX.west, DEMO_BBOX.south],
                        [DEMO_BBOX.east, DEMO_BBOX.south],
                        [DEMO_BBOX.east, DEMO_BBOX.north],
                        [DEMO_BBOX.west, DEMO_BBOX.north],
                        [DEMO_BBOX.west, DEMO_BBOX.south],
                    ]
                ],
            },
            "properties": {
                "platform": platform,
                "datetime": date + "T10:00:00Z",
                "eo:cloud_cover": 15,
            },
            "assets": assets,
        }
        records.append({"item": item, "provider": "local"})
    catalog.write_text(json.dumps({"schema": 3, "records": records}, indent=2) + "\n")
    return [Observation(r["item"], r["provider"]) for r in records]
