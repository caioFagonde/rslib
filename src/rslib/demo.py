from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds

from rslib.models import BBox

DEMO_BBOX = BBox(west=-44.75, south=-22.5, east=-44.55, north=-22.3)
_lock = threading.Lock()


def create_demo(directory: Path) -> dict:
    """Deterministic synthetic multispectral fixture, explicitly marked on every scene."""
    with _lock:
        directory.mkdir(parents=True, exist_ok=True)
        y, x = np.mgrid[0:256, 0:256] / 255
        rng = np.random.default_rng(42)
        relief = np.sin(x * 13 + np.cos(y * 7)) * 0.18 + np.cos(y * 15 - x * 4) * 0.14
        vegetation = np.clip(0.5 + relief + 0.12 * rng.normal(size=x.shape), 0.03, 0.95)
        field = (x > 0.17) & (x < 0.52) & (y > 0.26) & (y < 0.71)
        vegetation[field] *= 0.6
        water = np.abs(x - (0.7 + 0.07 * np.sin(y * 10))) < 0.018
        scl = np.where(water, 6, np.where(vegetation > 0.4, 4, 5)).astype("uint8")
        cloud = ((x - 0.3) ** 2 / 0.018 + (y - 0.18) ** 2 / 0.008 < 1) | (
            (x - 0.85) ** 2 / 0.008 + (y - 0.8) ** 2 / 0.015 < 1
        )
        scl[cloud] = 9
        scl[:3], scl[-3:], scl[:, :3], scl[:, -3:] = 0, 0, 0, 0
        values = {
            "red": 0.22 - 0.16 * vegetation,
            "green": 0.12 + 0.06 * vegetation,
            "blue": 0.08 + 0.04 * (1 - vegetation),
            "nir": 0.12 + 0.43 * vegetation,
            "swir16": 0.3 - 0.17 * vegetation,
            "swir22": 0.27 - 0.16 * vegetation,
            "scl": scl,
            "dem": 900 + 1200 * (y + 0.3 * np.sin(x * 7)) + 180 * np.sin(x * 20 + y * 9),
        }
        features = []
        transform = from_bounds(*DEMO_BBOX.bounds, 256, 256)
        assets = {}
        for name, data in values.items():
            path = directory / f"{name}.tif"
            if not path.exists():
                arr = data.astype("uint8" if name == "scl" else "float32")
                if name not in ("scl", "dem"):
                    arr[cloud], arr[water], arr[scl == 0] = 0.8, 0.02, 0
                with rasterio.open(
                    path,
                    "w",
                    driver="GTiff",
                    width=256,
                    height=256,
                    count=1,
                    dtype=arr.dtype,
                    crs="EPSG:4326",
                    transform=transform,
                    nodata=0 if name != "dem" else -9999,
                    tiled=True,
                    compress="deflate",
                ) as dst:
                    dst.write(arr, 1)
            assets[name] = {
                "href": str(path.resolve()),
                "type": "image/tiff; application=geotiff",
                "roles": ["data"],
                "raster:bands": [{"scale": 1, "offset": 0}],
            }
        w, s, e, n = DEMO_BBOX.bounds
        for date in ["2026-07-18", "2026-07-08", "2026-06-28"]:
            features.append(
                {
                    "type": "Feature",
                    "stac_version": "1.0.0",
                    "id": f"demo-{date}",
                    "collection": "rslib-demo",
                    "bbox": list(DEMO_BBOX.bounds),
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
                    },
                    "properties": {
                        "datetime": f"{date}T13:00:00Z",
                        "eo:cloud_cover": float(np.mean(cloud) * 100),
                        "rslib:synthetic": True,
                        "rslib:note": "Same synthetic raster under three fixture timestamps; not a measured time series",
                    },
                    "assets": assets,
                    "links": [],
                    "license": "CC0-1.0",
                }
            )
        return {
            "type": "FeatureCollection",
            "features": features,
            "links": [],
            "rslib": {
                "provider": "demo",
                "synthetic": True,
                "returned": len(features),
                "truncated": False,
                "note": "Synthetic fixture near Itatiaia; not satellite observations",
            },
        }
