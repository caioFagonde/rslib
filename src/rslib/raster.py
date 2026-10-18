from __future__ import annotations

import math
import time
from collections import OrderedDict
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from threading import Lock
from urllib.parse import quote, urlsplit

import httpx
import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from rasterio.shutil import copy as rio_copy
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT

from rslib.models import BBox


def public_asset_href(href: str) -> str:
    """Use unsigned HTTPS for explicitly registered public S3 terrain buckets."""
    parsed = urlsplit(href)
    if parsed.scheme == "s3" and parsed.netloc in {"copernicus-dem-30m", "copernicus-dem-90m"}:
        return f"https://{parsed.netloc}.s3.eu-central-1.amazonaws.com{parsed.path}"
    return href


@dataclass(frozen=True)
class Grid:
    crs: str
    transform: Affine
    width: int
    height: int

    def __post_init__(self):
        if self.width < 1 or self.height < 1 or self.width * self.height > 16_777_216:
            raise ValueError("Grid must contain 1 to 16,777,216 pixels; tile larger jobs")

    @classmethod
    def preview(cls, bbox: BBox, size: int = 512) -> Grid:
        if not 1 <= size <= 4096:
            raise ValueError("Preview size must be between 1 and 4096")
        # Geographic grid keeps browser bitmap corners exact. Not an area-measurement grid.
        aspect = (bbox.east - bbox.west) / (bbox.north - bbox.south)
        width = size if aspect >= 1 else max(1, round(size * aspect))
        height = size if aspect <= 1 else max(1, round(size / aspect))
        return cls("EPSG:4326", from_bounds(*bbox.bounds, width, height), width, height)

    def metadata(self) -> dict:
        return {
            "crs": self.crs,
            "transform": list(self.transform)[:6],
            "width": self.width,
            "height": self.height,
        }


def read_band(
    href: str,
    grid: Grid,
    *,
    categorical: bool = False,
    zero_is_valid: bool = False,
    scale: float | None = None,
    offset: float | None = None,
    band: int = 1,
) -> np.ndarray:
    """GDAL range reads into a bounded target grid; nodata preserved before calibration.

    Call directly with trusted URLs/local files. The HTTP API only resolves catalog assets.
    Quantitative indices use nearest-neighbor resampling to avoid mixing cloudy source
    pixels into clear pixels before the independently sampled QA mask is applied.
    """
    with rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        GDAL_HTTP_TIMEOUT="30",
        GDAL_HTTP_MAX_RETRY="2",
        GDAL_HTTP_RETRY_DELAY="0.5",
        GDAL_CACHEMAX=128,
        VSI_CACHE=True,
        VSI_CACHE_SIZE=16_777_216,
    ):
        with rasterio.open(public_asset_href(href)) as src:
            if not src.crs:
                raise ValueError("Raster has no CRS")
            nodata_override = (
                {"src_nodata": float("nan")} if zero_is_valid and src.nodata == 0 else {}
            )
            with WarpedVRT(
                src,
                crs=grid.crs,
                transform=grid.transform,
                width=grid.width,
                height=grid.height,
                dtype="float32",
                nodata=float("nan"),
                resampling=Resampling.nearest,
                **nodata_override,
            ) as vrt:
                values = vrt.read(band, masked=True).filled(np.nan).astype("float32")
            if not categorical:
                factor = src.scales[band - 1] if scale is None else scale
                shift = src.offsets[band - 1] if offset is None else offset
                if not math.isfinite(factor) or not math.isfinite(shift):
                    raise ValueError("Invalid raster calibration")
                values = values * factor + shift
    return values


def write_cog(
    path: Path,
    values: np.ndarray,
    grid: Grid,
    *,
    categorical: bool = False,
    band_names: tuple[str, ...] | None = None,
    tags: dict[str, str] | None = None,
) -> None:
    """Write an internally tiled, compressed COG with appropriate overview resampling."""
    data = np.asarray(values, dtype="float32")
    if data.ndim == 2:
        data = data[None]
    if data.shape[1:] != (grid.height, grid.width):
        raise ValueError("Output array must match the target grid")
    if band_names is not None and len(band_names) != data.shape[0]:
        raise ValueError("Band names must match output band count")
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.io.MemoryFile() as mem:
        with mem.open(
            driver="GTiff",
            width=grid.width,
            height=grid.height,
            count=data.shape[0],
            dtype="float32",
            crs=grid.crs,
            transform=grid.transform,
            nodata=np.nan,
        ) as dst:
            dst.write(data)
            if band_names is not None:
                for i, name in enumerate(band_names, 1):
                    dst.set_band_description(i, name)
            if tags:
                dst.update_tags(**tags)
        with mem.open() as src:
            rio_copy(
                src,
                path,
                driver="COG",
                compress="DEFLATE",
                blocksize=256,
                overview_resampling="NEAREST" if categorical else "AVERAGE",
                num_threads="2",
            )


ALIASES = {
    "nir": ["nir", "B08", "B8", "nir08"],
    "red": ["red", "B04", "B4"],
    "green": ["green", "B03", "B3"],
    "blue": ["blue", "B02", "B2"],
    "swir16": ["swir16", "B11"],
    "swir22": ["swir22", "B12"],
    "scl": ["scl", "SCL"],
    "qa_pixel": ["qa_pixel", "QA_PIXEL"],
    "qa_radsat": ["qa_radsat", "QA_RADSAT"],
}


def resolve_asset(item: dict, common_name: str) -> dict:
    assets = item.get("assets", {})
    for key in ALIASES.get(common_name, [common_name]):
        if key in assets:
            return {"key": key, **assets[key]}
    for key, asset in assets.items():
        for b in asset.get("eo:bands", asset.get("bands", [])):
            if b.get("common_name") == common_name:
                return {"key": key, **asset}
    raise ValueError(f"Scene has no {common_name} asset; available: {', '.join(assets)}")


def asset_calibration(asset: dict) -> tuple[float | None, float | None]:
    bands = asset.get("raster:bands", asset.get("bands", [{}]))
    info = bands[0] if bands else {}
    return info.get("scale", info.get("raster:scale")), info.get(
        "offset", info.get("raster:offset")
    )


def optical_calibration(item: dict, asset: dict, provider: str) -> tuple[float, float, str]:
    """Fail closed for unreliable collections rather than guessing from histograms."""
    collection = item.get("collection", "")
    if provider == "earth-search" and collection == "sentinel-2-l2a":
        raise ValueError(
            "Earth Search legacy sentinel-2-l2a has inconsistent offset metadata. Use sentinel-2-c1-l2a for calibrated analysis."
        )
    scale, offset = asset_calibration(asset)
    if scale is not None:
        return float(scale), float(offset or 0), "STAC raster metadata"
    if provider == "planetary-computer" and collection == "sentinel-2-l2a":
        baseline = item.get("properties", {}).get("s2:processing_baseline")
        if baseline is None:
            raise ValueError(
                "Sentinel-2 calibration requires a processing baseline when scale metadata is absent"
            )
        return (
            0.0001,
            -0.1 if float(baseline) >= 4 else 0,
            "Sentinel-2 L2A baseline rule for Planetary Computer raw DN",
        )
    if provider == "planetary-computer" and "landsat-c2-l2" in collection:
        return 0.0000275, -0.2, "USGS Landsat Collection 2 L2 surface-reflectance calibration"
    if provider == "demo":
        return 1, 0, "Synthetic physical-reflectance fixture"
    raise ValueError(
        "Optical asset has no explicit calibration; add verified STAC raster scale/offset metadata"
    )


_SAS_TOKENS: OrderedDict[str, tuple[str, float]] = OrderedDict()
_SAS_LOCK = Lock()


def _container_endpoint(href: str) -> str | None:
    parsed = urlsplit(href)
    host = parsed.hostname or ""
    suffix = ".blob.core.windows.net"
    container = parsed.path.lstrip("/").split("/", 1)[0]
    if parsed.scheme == "https" and host.endswith(suffix) and container:
        account = host.removesuffix(suffix)
        return (
            "https://planetarycomputer.microsoft.com/api/sas/v1/token/"
            f"{quote(account, safe='')}/{quote(container, safe='')}"
        )
    return None


def invalidate_planetary_asset(href: str) -> None:
    """A failed native read can request a fresh container token on its next attempt."""
    with _SAS_LOCK:
        _SAS_TOKENS.pop(_container_endpoint(href), None)


def _sign_request(requester, url: str, **kwargs) -> dict:
    for attempt in range(5):
        try:
            response = requester.get(url, **kwargs)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 4:
                retry = response.headers.get("Retry-After", "")
                try:
                    delay = float(retry)
                except ValueError:
                    try:
                        delay = parsedate_to_datetime(retry).timestamp() - time.time()
                    except (ValueError, TypeError):
                        delay = 2**attempt
                if delay > 30:
                    response.raise_for_status()  # Do not retry earlier than a long server cooldown.
                time.sleep(max(0, delay))
                continue
            response.raise_for_status()
            return response.json()
        except httpx.TransportError:
            if attempt == 4:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("Asset signing retry budget exhausted")


def sign_planetary_asset(href: str, *, client: httpx.Client | None = None) -> str:
    """Reuse an unexpired, in-memory container SAS across bands and worker threads.

    The documented public PC token endpoint scopes the token to account/container.
    Refresh one minute before expiry; never persist credentials in any cache/report.
    """
    with httpx.Client(timeout=20) if client is None else nullcontext(client) as requester:
        endpoint = _container_endpoint(href)
        if endpoint:
            with _SAS_LOCK:
                cached = _SAS_TOKENS.get(endpoint)
                if cached is None or cached[1] - time.time() < 60:
                    document = _sign_request(requester, endpoint)
                    token = document.get("token")
                    try:
                        expiry = datetime.fromisoformat(
                            document["msft:expiry"].replace("Z", "+00:00")
                        )
                    except (KeyError, ValueError, TypeError, AttributeError) as error:
                        raise httpx.DecodingError(
                            "Signing service returned no valid expiry"
                        ) from error
                    if expiry.tzinfo is None or expiry <= datetime.now(UTC):
                        raise httpx.DecodingError("Signing service returned an expired token")
                    if not isinstance(token, str) or not token or token.startswith("?"):
                        raise httpx.DecodingError("Signing service returned no SAS token")
                    cached = token, expiry.timestamp()
                    _SAS_TOKENS[endpoint] = cached
                    _SAS_TOKENS.move_to_end(endpoint)
                    while len(_SAS_TOKENS) > 128:
                        _SAS_TOKENS.popitem(last=False)
                return href + ("&" if "?" in href else "?") + cached[0]
        document = _sign_request(
            requester,
            "https://planetarycomputer.microsoft.com/api/sas/v1/sign",
            params={"href": href},
        )
        signed = document.get("href")
        if not isinstance(signed, str) or not signed.startswith("https://"):
            raise httpx.DecodingError("Signing service returned no HTTPS asset URL")
        return signed
