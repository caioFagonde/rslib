"""One typed, cached path from multiple optical sensors to comparable observations."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zipfile import BadZipFile

import numpy as np
from affine import Affine

from rslib.cache import canonical_hash
from rslib.compositing import composite
from rslib.harmonization import COMMON_BANDS, bandpass_adjust, sensor_profile
from rslib.indices import INDEX_BANDS, spectral_index
from rslib.models import BBox
from rslib.preparation import aoi_mask, metric_grid, prepare_scene
from rslib.progress import Progress, notify
from rslib.raster import Grid
from rslib.timeseries import interpolate_gaps

STACK_VERSION = "rslib-stack/1"


@dataclass(frozen=True)
class Observation:
    item: dict
    provider: str


@dataclass(frozen=True)
class DailyStack:
    values: np.ndarray
    days: np.ndarray
    source_index: np.ndarray  # index in original OpticalStack observations
    observation_count: np.ndarray
    bands: tuple[str, ...]


@dataclass(frozen=True)
class RegularSeries:
    values: np.ndarray  # Q,Y,X scalar index
    days: np.ndarray
    support: np.ndarray  # 0 missing, 1 daily observed spectrum, 2 temporal estimate
    left_source: np.ndarray
    right_source: np.ndarray
    bracket_days: np.ndarray
    index: str


def _timestamp(item: dict) -> str:
    text = item.get("properties", {}).get("datetime")
    if not text:
        raise ValueError(f"Scene {item.get('id')} needs a single acquisition datetime")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Acquisition timestamps must include a UTC offset")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _save_npz(path: Path, **arrays) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            np.savez_compressed(file, **arrays)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _prune_cache(directory: Path, maximum_bytes: int) -> int:
    files = []
    for path in directory.glob("*.npz"):
        if not re.fullmatch(r"[0-9a-f]{64}\.npz", path.name):
            continue
        try:
            stat = path.stat()
            files.append((stat.st_mtime_ns, stat.st_size, path))
        except FileNotFoundError:
            continue
    total = sum(size for _, size, _ in files)
    evicted = 0
    for _, size, path in sorted(files):
        if total <= maximum_bytes:
            break
        try:
            path.unlink()
            total -= size
            evicted += 1
        except FileNotFoundError:
            total -= size
    return evicted


@dataclass(frozen=True)
class OpticalStack:
    values: np.ndarray
    quality: np.ndarray
    times: np.ndarray
    bands: tuple[str, ...]
    grid: Grid
    observations: tuple[dict, ...]
    processing: dict

    def analysis_mask(self) -> np.ndarray:
        bbox = self.processing.get("bbox")
        return (
            aoi_mask(BBox(**bbox), self.grid)
            if bbox
            else np.ones((self.grid.height, self.grid.width), dtype=bool)
        )

    def to_xarray(self):
        """Expose named bands, sensor coordinates and CRS to the xarray ecosystem.

        Requires the cube extra. This wraps an already prepared bounded stack;
        chunking the returned dataset does not make its acquisition lazy.
        """
        import rasterio
        import xarray as xr

        x = self.grid.transform.c + (np.arange(self.grid.width) + 0.5) * self.grid.transform.a
        y = self.grid.transform.f + (np.arange(self.grid.height) + 0.5) * self.grid.transform.e
        ds = xr.Dataset(
            {
                "reflectance": (
                    ("time", "band", "y", "x"),
                    self.values,
                    {"units": "1", "grid_mapping": "spatial_ref"},
                ),
                "clear_support": (
                    ("time", "y", "x"),
                    self.quality,
                    {"units": "1", "grid_mapping": "spatial_ref"},
                ),
                "aoi_mask": (("y", "x"), self.analysis_mask()),
            },
            coords={
                "time": self.times,
                "band": list(self.bands),
                "x": x,
                "y": y,
                "platform": ("time", [o.get("platform", "unknown") for o in self.observations]),
                "item_id": ("time", [o["id"] for o in self.observations]),
                "provider": ("time", [o.get("provider", "unknown") for o in self.observations]),
            },
            attrs={
                "processing": json.dumps(self.processing, allow_nan=False),
                "source_schema": STACK_VERSION,
            },
        )
        ds["spatial_ref"] = xr.DataArray(
            0,
            attrs={
                "crs_wkt": rasterio.crs.CRS.from_string(self.grid.crs).to_wkt(),
                "GeoTransform": " ".join(map(str, self.grid.transform.to_gdal())),
            },
        )
        ds.x.attrs.update(units="m", standard_name="projection_x_coordinate")
        ds.y.attrs.update(units="m", standard_name="projection_y_coordinate")
        return ds

    def daily(self) -> DailyStack:
        """UTC-day mosaics; best supported complete spectrum wins, first tie wins.

        Same-date tile overlap does not become an extra temporal observation.
        The original acquisition identity/time is retained in source_index.
        """
        dates = self.times.astype("datetime64[D]")
        days = np.unique(dates)
        images, sources, counts = [], [], []
        for day in days:
            selected = np.flatnonzero(dates == day)
            cube = self.values[selected]
            result = composite(cube, np.isfinite(cube).all(axis=1), quality=self.quality[selected])
            source = np.where(
                result.source_index >= 0, selected[np.maximum(result.source_index, 0)], -1
            )
            images.append(result.values)
            sources.append(source)
            counts.append(result.observation_count)
        return DailyStack(
            np.stack(images), days, np.stack(sources).astype("int32"), np.stack(counts), self.bands
        )

    def regular_series(
        self,
        *,
        index: str = "ndvi",
        step_days: int = 5,
        max_gap_days: float = 20,
        start: str | None = None,
        end: str | None = None,
    ) -> RegularSeries:
        """Daily observed spectra -> scalar index -> regular gap-limited timeline.

        Only exact observed UTC days are labeled observed. Other query dates are
        interpolated from actual bracketing clear days; no nearest-date relabeling,
        extrapolation or unsupported long-gap filling. All source indices refer to
        this stack's original observations, even after mosaicking and interpolation.
        """
        if index not in INDEX_BANDS or index == "rgb":
            raise ValueError("Select a scalar optical index")
        if any(b not in self.bands for b in INDEX_BANDS[index]):
            raise ValueError(f"Index {index} needs bands {INDEX_BANDS[index]}")
        if not isinstance(step_days, int) or not 1 <= step_days <= 365:
            raise ValueError("step_days must be 1–365")
        daily = self.daily()
        first = np.datetime64(start, "D") if start else daily.days[0]
        last = np.datetime64(end, "D") if end else daily.days[-1]
        if np.isnat(first) or np.isnat(last) or first > last:
            raise ValueError("Invalid regular time range")
        count = int((last - first) / np.timedelta64(1, "D")) // step_days + 1
        if count > 1024:
            raise ValueError("Regular timeline exceeds 1024 dates")
        queries = first + np.arange(count) * np.timedelta64(step_days, "D")
        union = np.union1d(daily.days, queries)
        shape = (len(union), self.grid.height, self.grid.width)
        if np.prod(shape) > 16_777_216:
            raise ValueError(
                "Temporal timeline exceeds 16-million samples; tile AOI or increase step"
            )
        values = spectral_index(
            index, {b: daily.values[:, self.bands.index(b)] for b in INDEX_BANDS[index]}
        )
        union_values = np.full(shape, np.nan, dtype="float32")
        positions = np.searchsorted(union, daily.days)
        union_values[positions] = values
        source = np.full(shape, -1, dtype="int32")
        source[positions] = daily.source_index
        filled = interpolate_gaps(union_values, union, max_gap_days=max_gap_days)
        q = np.searchsorted(union, queries)
        y, x = np.indices(shape[1:])
        left = source[np.maximum(filled.left_index[q], 0), y, x]
        right = source[np.maximum(filled.right_index[q], 0), y, x]
        supported = filled.provenance[q] > 0
        return RegularSeries(
            filled.values[q],
            queries,
            filled.provenance[q],
            np.where(supported, left, -1),
            np.where(supported, right, -1),
            filled.bracket_days[q],
            index,
        )

    def save(self, path: Path) -> None:
        """Portable, pickle-free stack; no signed asset tokens persisted."""
        metadata = {
            "schema": STACK_VERSION,
            "bands": self.bands,
            "grid": self.grid.metadata(),
            "observations": self.observations,
            "processing": self.processing,
        }
        _save_npz(
            path,
            values=self.values,
            quality=self.quality,
            times=self.times.astype("datetime64[us]").astype("int64"),
            metadata=np.array(json.dumps(metadata, allow_nan=False)),
        )

    @classmethod
    def load(cls, path: Path) -> OpticalStack:
        with np.load(path, allow_pickle=False) as archive:
            meta = json.loads(str(archive["metadata"]))
            if meta.get("schema") != STACK_VERSION:
                raise ValueError("Unsupported stack format")
            g = meta["grid"]
            grid = Grid(g["crs"], Affine(*g["transform"]), g["width"], g["height"])
            values, quality, times = (
                archive["values"],
                archive["quality"],
                archive["times"].astype("datetime64[us]"),
            )
        bands, records = tuple(meta["bands"]), tuple(meta["observations"])
        if (
            values.shape != (len(records), len(bands), grid.height, grid.width)
            or quality.shape != (len(records), grid.height, grid.width)
            or times.shape != (len(records),)
            or values.size > 33_554_432
        ):
            raise ValueError("Invalid stack shapes or sample budget")
        return cls(values, quality, times, bands, grid, records, meta["processing"])


def build_stack(
    observations: list[Observation],
    bbox: BBox,
    *,
    resolution: float = 30,
    crs: str | None = None,
    bands: tuple[str, ...] = COMMON_BANDS,
    harmonization: str = "bandpass",
    cloud_buffer_m: float = 60,
    min_clear_fraction: float = 0.9,
    cache_dir: Path | None = Path("data/cache/prepared"),
    cache_max_bytes: int = 2_147_483_648,
    refresh: bool = False,
    progress: Progress | None = None,
) -> OpticalStack:
    """Prepare, align, quality-mask and cache an optical multi-sensor AOI stack.

    Modes: bandpass (partial SR adjustment), hls (require preharmonized HLS only),
    none (common bands/grid and calibrated SR without spectral adjustment).
    Unsupported sensors/missing bands fail before acquisition; no silent drops.
    """
    if not observations or len(observations) > 32:
        raise ValueError("Provide 1–32 optical observations")
    if harmonization not in {"bandpass", "hls", "none"}:
        raise ValueError("harmonization must be bandpass, hls or none")
    if not isinstance(cache_max_bytes, int) or cache_max_bytes < 1:
        raise ValueError("Prepared cache budget must be a positive integer byte count")
    if not bands or len(set(bands)) != len(bands) or any(b not in COMMON_BANDS for b in bands):
        raise ValueError("Choose unique common optical bands")
    if (
        not np.isfinite(cloud_buffer_m)
        or not 0 <= cloud_buffer_m <= 1000
        or not np.isfinite(min_clear_fraction)
        or not 0 < min_clear_fraction <= 1
    ):
        raise ValueError("Invalid cloud buffer or clear support fraction")
    grid = metric_grid(bbox, resolution, crs)
    inside = aoi_mask(bbox, grid)
    if not inside.any():
        raise ValueError(
            "AOI contains no pixel centers at this resolution; enlarge it or use a finer grid"
        )
    selected = {}
    from rslib.harmonization import stack_asset

    for observation in observations:
        identity = (
            observation.provider,
            observation.item.get("collection"),
            observation.item.get("id"),
        )
        if not identity[1] or not identity[2]:
            raise ValueError("Each observation needs collection and item ID")
        if identity in selected:
            if selected[identity].item != observation.item:
                raise ValueError("Conflicting metadata for duplicate observation identity")
            continue
        profile = sensor_profile(observation.item)
        if harmonization == "hls" and not profile.already_harmonized:
            raise ValueError(
                "HLS mode requires upstream HLS L30/S30; ordinary L2 products are not HLS"
            )
        for band in bands:
            stack_asset(observation.item, band, profile)
        _timestamp(observation.item)
        selected[identity] = observation
    ordered = sorted(
        selected.values(),
        key=lambda o: (_timestamp(o.item), o.provider, o.item["collection"], o.item["id"]),
    )
    if len(ordered) * len(bands) * grid.height * grid.width > 33_554_432:
        raise ValueError(
            "Stack exceeds 32-million spectral samples; reduce scenes, increase resolution or tile AOI"
        )
    arrays, scores, times, records = [], [], [], []
    for scene_number, observation in enumerate(ordered, 1):
        item, provider = observation.item, observation.provider
        notify(
            progress,
            "preparing",
            f"Preparing {item['id']}",
            source_id=item["id"],
            scene=scene_number,
            scene_count=len(ordered),
        )
        profile = sensor_profile(item)
        parameters = {
            "schema": STACK_VERSION,
            "item": item,
            "provider": provider,
            "grid": grid.metadata(),
            "bbox": bbox.model_dump(),
            "bands": bands,
            "mode": harmonization,
            "cloud_buffer_m": float(cloud_buffer_m),
            "min_clear_fraction": float(min_clear_fraction),
        }
        key = canonical_hash(parameters)
        path = cache_dir / f"{key}.npz" if cache_dir else None
        hit = False
        if path and path.exists() and not refresh:
            try:
                with np.load(path, allow_pickle=False) as archive:
                    record = json.loads(str(archive["metadata"]))
                    values, quality = archive["values"], archive["quality"]
                hit = (
                    record["cache_key"] == key
                    and values.shape == (len(bands), grid.height, grid.width)
                    and quality.shape == (grid.height, grid.width)
                )
            except (ValueError, OSError, KeyError, BadZipFile, EOFError):
                hit = False
        if hit and path:
            try:
                os.utime(path, None)
            except FileNotFoundError:
                pass  # Another process can evict a file after it was loaded.
        if not hit:
            values, quality, inputs = prepare_scene(
                item,
                provider,
                profile,
                bands,
                grid,
                cloud_buffer_m=cloud_buffer_m,
                min_clear_fraction=min_clear_fraction,
            )
            values[:, ~inside], quality[~inside] = np.nan, 0
            adjustment = {"method": "none; calibrated SR on common grid"}
            if harmonization != "none":
                values, adjustment = bandpass_adjust(values, bands, profile)
            record = {
                "cache_key": key,
                "id": item["id"],
                "collection": item["collection"],
                "provider": provider,
                "datetime": _timestamp(item),
                "platform": profile.platform,
                "family": profile.family,
                "already_harmonized": profile.already_harmonized,
                "inputs": inputs,
                "adjustment": adjustment,
                "clear_fraction": float(np.isfinite(values[:, inside]).all(axis=0).mean()),
            }
            if path:
                _save_npz(
                    path,
                    values=values,
                    quality=quality,
                    metadata=np.array(json.dumps(record, allow_nan=False)),
                )
        record = {
            **record,
            "cache_hit": hit,
            "clear_fraction": float(np.isfinite(values[:, inside]).all(axis=0).mean()),
        }
        arrays.append(values)
        scores.append(quality)
        records.append(record)
        times.append(np.datetime64(record["datetime"].removesuffix("Z"), "us"))
        notify(
            progress,
            "prepared",
            f"Prepared {item['id']}",
            source_id=item["id"],
            cache_hit=hit,
            clear_fraction=record["clear_fraction"],
            scene=scene_number,
            scene_count=len(ordered),
        )
    evicted = _prune_cache(cache_dir, cache_max_bytes) if cache_dir else 0
    return OpticalStack(
        np.stack(arrays),
        np.stack(scores),
        np.array(times),
        bands,
        grid,
        tuple(records),
        {
            "harmonization": harmonization,
            "bbox": bbox.model_dump(),
            "aoi_pixels": int(inside.sum()),
            "cloud_buffer_m": cloud_buffer_m,
            "min_clear_fraction": min_clear_fraction,
            "resampling": "native QA first, GDAL area-weighted clear reflectance, support threshold, common complete spectrum",
            "nir": "Sentinel-2 B8A / Landsat OLI B05; broad B08 never substituted",
            "all_upstream_hls": all(r["already_harmonized"] for r in records),
            "cache_max_bytes": cache_max_bytes,
            "cache_evicted_files": evicted,
            "cache": "Prepared AOI/scene cache; immutable source assumption. Use refresh=True after upstream asset revisions.",
        },
    )
