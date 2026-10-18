"""Map previews reprojected to Web Mercator; analysis grids remain unchanged."""

from __future__ import annotations

import numpy as np
from PIL import Image
from rasterio.enums import Resampling
from rasterio.transform import array_bounds, from_bounds
from rasterio.warp import reproject, transform_bounds

from rslib.pipeline import colorize
from rslib.raster import Grid


class MapDisplay:
    def __init__(self, grid: Grid, directory):
        self.source, self.directory = grid, directory
        w, s, e, n = transform_bounds(
            grid.crs,
            "EPSG:3857",
            *array_bounds(grid.height, grid.width, grid.transform),
            densify_pts=21,
        )
        edge = min(1024, max(grid.width, grid.height))
        spacing = max((e - w) / edge, (n - s) / edge, 1)
        width, height = max(1, round((e - w) / spacing)), max(1, round((n - s) / spacing))
        self.grid = Grid("EPSG:3857", from_bounds(w, s, e, n, width, height), width, height)
        self.bounds = transform_bounds("EPSG:3857", "EPSG:4326", w, s, e, n)

    def save(self, name: str, values: np.ndarray, index: str, *, support=False):
        image = np.full((self.grid.height, self.grid.width), np.nan, dtype="float32")
        reproject(
            values.astype("float32"),
            image,
            src_transform=self.source.transform,
            src_crs=self.source.crs,
            dst_transform=self.grid.transform,
            dst_crs=self.grid.crs,
            src_nodata=np.nan,
            dst_nodata=np.nan,
            resampling=Resampling.nearest,
        )
        if support:
            palette = np.array(
                [[27, 43, 34, 220], [158, 211, 139, 245], [227, 182, 109, 245]], dtype="uint8"
            )
            rgba = palette[np.nan_to_num(image).astype("int32")]
            rgba[~np.isfinite(image), 3] = 0
        else:
            rgba = colorize(image, index)
        Image.fromarray(rgba).save(self.directory / name)

    def metadata(self):
        return {
            "bounds": list(self.bounds),
            "grid": self.grid.metadata(),
            "method": "Nearest-neighbor Web Mercator display reprojection; inspect original analysis cells",
        }
