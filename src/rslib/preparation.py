"""AOI window reads, native QA masking and area-weighted common-grid preparation."""

from __future__ import annotations

import math
import time

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.errors import RasterioIOError
from rasterio.features import geometry_mask
from rasterio.transform import array_bounds, from_origin
from rasterio.warp import reproject, transform_bounds, transform_geom
from rasterio.windows import Window, from_bounds
from scipy.ndimage import distance_transform_edt

from rslib.harmonization import SensorProfile, hls_clear, stack_asset
from rslib.indices import landsat_clear, sentinel_clear
from rslib.models import BBox
from rslib.raster import (
    Grid,
    asset_calibration,
    invalidate_planetary_asset,
    optical_calibration,
    public_asset_href,
    read_band,
    sign_planetary_asset,
)


def metric_grid(bbox: BBox, resolution: float = 30, crs: str | None = None) -> Grid:
    """Snap all pixel edges to a fixed metric lattice, independent of scene origins."""
    if not np.isfinite(resolution) or not 30 <= resolution <= 1000:
        raise ValueError("Common optical stacks require 30–1000 m resolution")
    if crs is None:
        center = (bbox.west + bbox.east) / 2
        zone = min(60, max(1, math.floor((center + 180) / 6) + 1))
        if bbox.south < -80 or bbox.north > 84 or bbox.east - bbox.west > 6:
            raise ValueError("Supply an appropriate projected metric CRS for polar or wide AOIs")
        crs = f"EPSG:{(32600 if (bbox.south + bbox.north) / 2 >= 0 else 32700) + zone}"
    projection = rasterio.crs.CRS.from_user_input(crs)
    if not projection.is_projected or projection.linear_units != "metre":
        raise ValueError("Stack CRS must be projected with metre units")
    w, s, e, n = transform_bounds("EPSG:4326", projection, *bbox.bounds, densify_pts=21)
    w, s, e, n = (
        math.floor(w / resolution) * resolution,
        math.floor(s / resolution) * resolution,
        math.ceil(e / resolution) * resolution,
        math.ceil(n / resolution) * resolution,
    )
    width, height = round((e - w) / resolution), round((n - s) / resolution)
    if width * height > 1_048_576:
        raise ValueError(
            f"AOI needs {width * height:,} pixels; increase resolution or split into tiles (limit 1,048,576)"
        )
    return Grid(projection.to_string(), from_origin(w, n, resolution, resolution), width, height)


def _href(asset: dict, provider: str) -> str:
    href = asset["href"]
    return (
        sign_planetary_asset(href) if provider == "planetary-computer" else public_asset_href(href)
    )


def aoi_mask(bbox: BBox, grid: Grid) -> np.ndarray:
    corners = [
        (bbox.west, bbox.south),
        (bbox.east, bbox.south),
        (bbox.east, bbox.north),
        (bbox.west, bbox.north),
        (bbox.west, bbox.south),
    ]
    ring = []
    for a, b in zip(corners[:-1], corners[1:], strict=True):
        ring.extend(
            [
                (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
                for f in np.linspace(0, 1, 33)[:-1]
            ]
        )
    ring.append(ring[0])
    geometry = transform_geom("EPSG:4326", grid.crs, {"type": "Polygon", "coordinates": [ring]})
    return geometry_mask(
        [geometry], out_shape=(grid.height, grid.width), transform=grid.transform, invert=True
    )


def _native_window(href: str, target: Grid, pad_m: float, *, zero_is_valid: bool = False):
    """Read native pixels over only the AOI + context; never resample before masking."""
    with rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        GDAL_HTTP_TIMEOUT="30",
        GDAL_HTTP_MAX_RETRY="2",
        GDAL_HTTP_RETRY_DELAY="0.5",
        GDAL_CACHEMAX=64,
    ):
        with rasterio.open(href) as src:
            if (
                not src.crs
                or not src.crs.is_projected
                or src.crs.linear_units != "metre"
                or src.transform.b
                or src.transform.d
            ):
                raise ValueError("Optical preparation requires native north-up metric rasters")
            bounds = transform_bounds(
                target.crs,
                src.crs,
                *array_bounds(target.height, target.width, target.transform),
                densify_pts=21,
            )
            window = from_bounds(*bounds, transform=src.transform)
            pad = math.ceil(pad_m / min(abs(src.transform.a), abs(src.transform.e))) + 2
            left, top = math.floor(window.col_off) - pad, math.floor(window.row_off) - pad
            right, bottom = (
                math.ceil(window.col_off + window.width) + pad,
                math.ceil(window.row_off + window.height) + pad,
            )
            if right <= 0 or bottom <= 0 or left >= src.width or top >= src.height:
                return None
            if (right - left) * (bottom - top) > 16_777_216:
                raise ValueError("Native read exceeds 16-million-pixel budget; tile the AOI")
            window = Window(left, top, right - left, bottom - top)
            if zero_is_valid and src.nodata == 0:
                values = src.read(
                    1, window=window, out_dtype="float32", boundless=True, fill_value=np.nan
                )
            else:
                values = src.read(
                    1,
                    window=window,
                    out_dtype="float32",
                    masked=True,
                    boundless=True,
                    fill_value=np.nan,
                ).filled(np.nan)
            return values, Grid(
                src.crs.to_string(), src.window_transform(window), right - left, bottom - top
            )


def _read_native_asset(
    asset: dict, provider: str, grid: Grid, pad_m: float, *, zero_is_valid: bool = False
):
    for attempt in range(2):
        try:
            return _native_window(_href(asset, provider), grid, pad_m, zero_is_valid=zero_is_valid)
        except RasterioIOError:
            if attempt:
                raise
            # A retry resolves a fresh short-lived token as well as reopening GDAL.
            if provider == "planetary-computer":
                invalidate_planetary_asset(asset["href"])
            time.sleep(0.25)


def _warp(
    values: np.ndarray, source: Grid, target: Grid, method: Resampling, *, nodata=np.nan
) -> np.ndarray:
    destination = np.full((target.height, target.width), np.nan, dtype="float32")
    reproject(
        values,
        destination,
        src_transform=source.transform,
        src_crs=source.crs,
        dst_transform=target.transform,
        dst_crs=target.crs,
        src_nodata=nodata,
        dst_nodata=np.nan,
        resampling=method,
        num_threads=2,
    )
    return destination


def prepare_scene(
    item: dict,
    provider: str,
    profile: SensorProfile,
    bands: tuple[str, ...],
    grid: Grid,
    *,
    cloud_buffer_m: float = 60,
    min_clear_fraction: float = 0.9,
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """Mask on each native band grid, then GDAL area-average clear reflectance.

    Coverage is warped separately with zero-valued invalid source samples retained.
    Reject under-supported target cells instead of letting a tiny clear fragment
    represent an entire output pixel. Native read padding covers the QA buffer.
    """
    qa_name = (
        "fmask"
        if profile.already_harmonized
        else "scl"
        if profile.family == "sentinel-2"
        else "qa_pixel"
    )
    qa_asset = stack_asset(item, qa_name, profile)
    qa_native = _read_native_asset(
        qa_asset,
        provider,
        grid,
        cloud_buffer_m + 120,
        zero_is_valid=qa_name in {"fmask", "qa_pixel"},
    )
    empty = np.full((len(bands), grid.height, grid.width), np.nan, dtype="float32")
    if qa_native is None:
        return empty, np.zeros(empty.shape[1:], dtype="float32"), []
    qa, qa_grid = qa_native
    if qa_name == "scl":
        clear = sentinel_clear(qa, 0)
    elif qa_name == "fmask":
        clear = hls_clear(qa)
    else:
        saturation = read_band(
            _href(stack_asset(item, "qa_radsat", profile), provider),
            qa_grid,
            categorical=True,
            zero_is_valid=True,
        )
        clear = (
            np.isfinite(qa)
            & np.isfinite(saturation)
            & landsat_clear(np.nan_to_num(qa), np.nan_to_num(saturation))
        )
    if cloud_buffer_m:
        # Pad false outside the QA array so scene edges also receive context handling.
        distance = distance_transform_edt(
            np.pad(clear, 1, constant_values=False),
            sampling=(abs(qa_grid.transform.e), abs(qa_grid.transform.a)),
        )[1:-1, 1:-1]
        clear &= distance > cloud_buffer_m
    result, coverage, provenance = [], [], []
    for band in bands:
        asset = stack_asset(item, band, profile)
        native = _read_native_asset(asset, provider, grid, cloud_buffer_m + 120)
        if native is None:
            result.append(np.full(empty.shape[1:], np.nan, dtype="float32"))
            coverage.append(np.zeros(empty.shape[1:], dtype="float32"))
            continue
        values, native_grid = native
        native_scale = max(abs(native_grid.transform.a), abs(native_grid.transform.e))
        if native_scale > grid.transform.a * 1.01:
            raise ValueError(
                "Target resolution would upsample a native band; choose a coarser grid"
            )
        scale, offset = asset_calibration(asset)
        if profile.already_harmonized:
            scale, offset, policy = (
                float(scale) if scale is not None else 0.0001,
                float(offset or 0),
                "HLS V2 surface reflectance (explicit metadata or published 0.0001 scale)",
            )
        else:
            scale, offset, policy = optical_calibration(item, asset, provider)
        if not np.isfinite(scale) or scale <= 0 or not np.isfinite(offset):
            raise ValueError(
                "Reflectance calibration requires positive finite scale and finite offset"
            )
        mask = _warp(clear.astype("float32"), qa_grid, native_grid, Resampling.nearest, nodata=None)
        valid = (mask == 1) & np.isfinite(values)
        calibrated = values * scale + offset
        prepared = _warp(
            np.where(valid, calibrated, np.nan).astype("float32"),
            native_grid,
            grid,
            Resampling.average,
        )
        fraction = np.nan_to_num(
            _warp(valid.astype("float32"), native_grid, grid, Resampling.average, nodata=None)
        )
        # Conservative center support prevents GDAL's partial source-edge overlap
        # normalization from turning a fringe sliver into an apparently full cell.
        center = _warp(valid.astype("float32"), native_grid, grid, Resampling.nearest, nodata=None)
        fraction = np.where(center == 1, fraction, 0)
        prepared[fraction < min_clear_fraction] = np.nan
        result.append(prepared)
        coverage.append(fraction)
        from rslib.pipeline import sanitized_href

        provenance.append(
            {
                "band": band,
                "asset": asset["key"],
                "href": sanitized_href(asset["href"]),
                "calibration": {"scale": scale, "offset": offset, "policy": policy},
                "native_resolution_m": native_scale,
            }
        )
    output = np.stack(result)
    quality = np.minimum.reduce(coverage)
    common = np.isfinite(output).all(axis=0)
    output[:, ~common] = np.nan
    quality[~common] = 0
    return output, quality, provenance
