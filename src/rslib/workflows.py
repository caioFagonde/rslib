"""Practical multi-sensor optical preparation, regular series and portable exports."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rslib.cache import ResponseCache
from rslib.display import MapDisplay
from rslib.fields import FieldBoundary, export_fields, field_series, validate_fields
from rslib.indices import summarize
from rslib.models import BBox, Search
from rslib.pipeline import colorize
from rslib.progress import Progress, notify
from rslib.raster import write_cog
from rslib.stac import client_for
from rslib.stack import Observation, _save_npz, build_stack
from rslib.stack_demo import DEMO_BBOX, create_stack_demo


class StackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)
    demo: bool = True
    bbox: BBox = DEMO_BBOX
    datetime: str = "2026-06-01/2026-07-16"
    sensors: list[Literal["sentinel-2", "landsat"]] = Field(
        default_factory=lambda: ["sentinel-2", "landsat"], min_length=1, max_length=2
    )
    max_scenes_per_sensor: int = Field(default=4, ge=1, le=12)
    max_cloud: float = Field(default=40, ge=0, le=100)
    resolution: float = Field(default=30, ge=30, le=1000)
    cloud_buffer_m: float = Field(default=60, ge=0, le=1000)
    min_clear_fraction: float = Field(default=0.9, gt=0, le=1)
    index: Literal["ndvi", "ndmi", "nbr", "evi"] = "ndvi"
    step_days: int = Field(default=5, ge=1, le=365)
    max_gap_days: float = Field(default=20, gt=0, le=90)
    refresh: bool = False
    fields: list[FieldBoundary] = Field(default_factory=list, max_length=32)
    coverage_target: float | None = Field(default=None, gt=0, le=1)

    @model_validator(mode="after")
    def field_bounds(self):
        validate_fields(self.fields, self.bbox)
        return self

    @field_validator("datetime")
    @classmethod
    def interval(cls, value):
        normalized = Search.valid_interval(value)
        if not normalized or len(normalized.split("/")) != 2 or ".." in normalized:
            raise ValueError("A finite start/end date interval is required")
        return normalized

    @field_validator("sensors")
    @classmethod
    def unique_sensors(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Choose each sensor once")
        return value


async def discover_observations(
    request: StackRequest, cache: ResponseCache | None = None
) -> tuple[list[Observation], list[dict]]:
    sources = {
        "sentinel-2": ("earth-search", "sentinel-2-c1-l2a"),
        "landsat": ("planetary-computer", "landsat-c2-l2"),
    }

    async def search(sensor):
        from rslib.acquisition import plan_stack_items

        provider, collection = sources[sensor]
        query = Search(
            provider=provider,
            collections=[collection],
            bbox=request.bbox,
            datetime=request.datetime,
            max_cloud=request.max_cloud,
            max_items=min(200, request.max_scenes_per_sensor * 4),
            max_pages=5,
        )
        result = await client_for(provider, cache).search(query)
        selected, planning = plan_stack_items(
            result["features"], request.bbox, request.datetime, request.max_scenes_per_sensor
        )
        items = [Observation(item, provider) for item in selected]
        return items, {"sensor": sensor, **result["rslib"], "acquisition_plan": planning}

    results = await asyncio.gather(*(search(sensor) for sensor in request.sensors))
    observations = [o for group, _ in results for o in group]
    if not observations:
        raise ValueError(
            "No matching optical scenes. Adjust dates/cloud limits; no synthetic fallback was used."
        )
    return observations, [report for _, report in results]


async def prepare_optical(
    request: StackRequest | None = None,
    data: Path = Path("data"),
    *,
    catalog_cache: ResponseCache | None = None,
    progress: Progress | None = None,
    inventory: dict | None = None,
    run_id: str | None = None,
    resume: bool = False,
) -> dict:
    """One recipe from catalog discovery through aligned stack and series exports.

    Async clients remain responsive while GDAL runs in a background thread. The
    default request is a labeled synthetic fixture; real acquisition is explicit.
    """
    started = time.perf_counter()
    request = request or StackRequest()
    data = Path(data).resolve()
    cache = catalog_cache or ResponseCache(data / "cache" / "stac.sqlite3")
    notify(
        progress,
        "discovering",
        "Reading saved scene inventory" if inventory else "Searching optical catalogs",
    )
    if inventory:
        observations = [Observation(**record) for record in inventory["observations"]]
        discovery = inventory["discovery"]
    else:
        observations, discovery = (
            (None, []) if request.demo else await discover_observations(request, cache)
        )
    return await asyncio.to_thread(
        run_stack_workflow,
        request,
        observations,
        data,
        discovery=discovery,
        workflow_started=started,
        discovery_seconds=time.perf_counter() - started,
        progress=progress,
        run_id=run_id,
        resume=resume,
    )


def run_stack_workflow(
    request: StackRequest,
    observations: list[Observation] | None,
    data: Path,
    *,
    discovery: list[dict] | None = None,
    workflow_started: float | None = None,
    discovery_seconds: float = 0,
    progress: Progress | None = None,
    run_id: str | None = None,
    resume: bool = False,
) -> dict:
    started = time.perf_counter()
    if request.demo and request.bbox != DEMO_BBOX:
        raise ValueError(
            "Synthetic fixture uses its labeled Itatiaia AOI; select live data for another area"
        )
    if request.demo and observations is None:
        observations = create_stack_demo(data / "stack-demo")
        start, end = request.datetime.split("/")
        beginning = np.datetime64(start.removesuffix("Z"), "us")
        ending = np.datetime64(end.removesuffix("Z"), "us")
        selected = []
        for sensor in request.sensors:
            group = [
                o
                for o in observations
                if (
                    "sentinel-2"
                    if o.item["properties"]["platform"].startswith("sentinel")
                    else "landsat"
                )
                == sensor
                and beginning
                <= np.datetime64(o.item["properties"]["datetime"].removesuffix("Z"), "us")
                <= ending
            ]
            indices = np.linspace(
                0, len(group) - 1, min(len(group), request.max_scenes_per_sensor), dtype=int
            )
            selected.extend(group[i] for i in indices)
        observations = selected
    if not observations:
        raise ValueError("Provide discovered observations for a live workflow")
    notify(
        progress,
        "inventory",
        f"Selected {len(observations)} candidate scenes",
        inventory={
            "observations": [{"item": o.item, "provider": o.provider} for o in observations],
            "discovery": discovery or [],
        },
    )
    stack, series, acquisition = acquire_to_coverage(
        request, observations, data, progress=progress, resume=resume
    )
    daily = stack.daily()
    inside = stack.analysis_mask()
    identifier = run_id or uuid.uuid4().hex
    if not re.fullmatch(r"[0-9a-f]{32}", identifier):
        raise ValueError("Invalid run identifier")
    # Only complete exports are public. A retry may discard unfinished exports,
    # while prepared scene caches and the pinned inventory remain reusable.
    directory = data / ".staging" / identifier
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    notify(progress, "exporting", "Computing area statistics and writing analysis exports")
    fields = field_series(request.fields, series.values, series.support, series.days, stack.grid)
    export_fields(directory, request.fields, fields, request.index, request.demo)
    display = MapDisplay(stack.grid, directory)
    stack.save(directory / "stack.npz")
    _save_npz(
        directory / "series.npz",
        values=series.values,
        days=series.days.astype("int64"),
        support=series.support,
        left_source=series.left_source,
        right_source=series.right_source,
        bracket_days=series.bracket_days,
        metadata=np.array(
            json.dumps(
                {
                    "index": request.index,
                    "date_unit": "days since 1970-01-01",
                    "grid": stack.grid.metadata(),
                    "support": {
                        "0": "unsupported",
                        "1": "observed UTC daily mosaic",
                        "2": "linear temporal estimate",
                    },
                }
            )
        ),
    )
    write_cog(
        directory / "analysis.tif",
        series.values,
        stack.grid,
        band_names=tuple(f"{request.index}:{day}" for day in series.days),
        tags={
            "SERIES_SUPPORT": "See series.npz: 0 unsupported, 1 observed, 2 interpolated",
            "SYNTHETIC": str(request.demo),
        },
    )
    # A tiled companion permits point inspection without decompressing the full
    # NPZ cube. Each group has one band per requested date, in the same order.
    write_cog(
        directory / "series-support.tif",
        np.concatenate(
            [series.support, series.left_source, series.right_source, series.bracket_days],
            dtype="float32",
        ),
        stack.grid,
        categorical=True,
        band_names=tuple(
            f"{field}:{day}"
            for field in ["support", "left_source", "right_source", "bracket_days"]
            for day in series.days
        ),
        tags={"SUPPORT_CODES": "0 missing, 1 observed, 2 linear estimate"},
    )
    # Use the last observed daily spectrum for the spectral composite/export.
    from rslib.compositing import composite

    quality = np.broadcast_to(
        np.arange(len(daily.days))[:, None, None], daily.source_index.shape
    ).astype("float32")
    latest = composite(daily.values, np.isfinite(daily.values).all(axis=1), quality=quality)
    write_cog(directory / "composite.tif", latest.values, stack.grid, band_names=stack.bands)
    y, x = np.indices(latest.source_index.shape)
    latest_source = daily.source_index[np.maximum(latest.source_index, 0), y, x].astype("float32")
    latest_source[latest.source_index < 0] = np.nan
    write_cog(
        directory / "provenance.tif",
        np.stack([latest_source, latest.observation_count]),
        stack.grid,
        categorical=True,
        band_names=("original_observation_index", "clear_daily_mosaic_count"),
    )
    from rslib.indices import INDEX_BANDS, spectral_index

    before = spectral_index(
        request.index,
        {b: daily.values[0, stack.bands.index(b)] for b in INDEX_BANDS[request.index]},
    )
    preview = spectral_index(
        request.index, {b: latest.values[stack.bands.index(b)] for b in INDEX_BANDS[request.index]}
    )
    Image.fromarray(colorize(before, request.index)).save(directory / "before.png")
    Image.fromarray(colorize(preview, request.index)).save(directory / "preview.png")
    display.save("map-composite.png", preview, request.index)
    support_colors = np.array([[27, 43, 34], [158, 211, 139], [227, 182, 109]], dtype="uint8")
    frames = []
    for i, day in enumerate(series.days):
        if i % 16 == 0:
            notify(
                progress,
                "exporting",
                "Writing dated map and support images",
                date=i + 1,
                date_count=len(series.days),
            )
        name = f"frame-{i:04d}.png"
        maskname = f"support-{i:04d}.png"
        Image.fromarray(colorize(series.values[i], request.index)).save(directory / name)
        Image.fromarray(support_colors[series.support[i]]).save(directory / maskname)
        display.save(f"map-{name}", series.values[i], request.index)
        display.save(f"map-{maskname}", series.support[i], request.index, support=True)
        counts = np.bincount(series.support[i][inside], minlength=3)
        frames.append(
            {
                "day": str(day),
                "image_url": f"/api/runs/{identifier}/{name}",
                "support_url": f"/api/runs/{identifier}/{maskname}",
                "map_image_url": f"/api/runs/{identifier}/map-{name}",
                "map_support_url": f"/api/runs/{identifier}/map-{maskname}",
                "observed_fraction": float(counts[1] / inside.sum()),
                "filled_fraction": float(counts[2] / inside.sum()),
                "statistics": summarize(series.values[i][inside]),
            }
        )
    report = {
        "schema_version": "rslib-stack-workflow/1",
        "id": identifier,
        "synthetic": request.demo,
        "request": request.model_dump(),
        "grid": stack.grid.metadata(),
        "bands": stack.bands,
        "observations": stack.observations,
        "processing": stack.processing,
        "discovery": discovery or [],
        "acquisition": acquisition,
        "summary": {
            "observations": len(stack.observations),
            "daily_mosaics": len(daily.days),
            "regular_dates": len(series.days),
            "platforms": sorted(set(r["platform"] for r in stack.observations)),
            "cache_hits": sum(r["cache_hit"] for r in stack.observations),
            "observed_fraction": float((series.support[:, inside] == 1).mean()),
            "filled_fraction": float((series.support[:, inside] == 2).mean()),
            "unsupported_fraction": float((series.support[:, inside] == 0).mean()),
        },
        "timeline": frames,
        "fields": fields,
        "display": {
            **display.metadata(),
            "composite_url": f"/api/runs/{identifier}/map-composite.png",
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "sampling": "Projected common grid; QA applied on native grids before area averaging. Bands matched by sensor. Output pixels are masked below the clear-support threshold.",
        "limitations": [
            "Bandpass adjustment on ordinary SR is partial harmonization; no BRDF normalization or common atmospheric reprocessing.",
            "Daily mosaics represent a UTC day, not a simultaneous multi-sensor exposure.",
            "Interpolation is allowed only between clear observations within max_gap_days, can smear change, and never extrapolates.",
            "Search limits/truncation are retained; these scenes do not guarantee complete temporal or AOI coverage.",
        ],
    }
    notes = []
    if acquisition["stop_reason"] == "candidate_budget_exhausted":
        notes.append(
            f"Coverage goal {request.coverage_target:.0%} was not met: "
            f"{acquisition['steps'][-1]['supported_fraction']:.1%} supported. "
            "All planned candidates within the scene budget were prepared; missing data remain explicit."
        )
    if not np.isfinite(series.values[:, inside]).any():
        notes.append(
            "No regular query date has support. View acquisition days with a 1-day interval, acquire more scenes, or review the maximum bracket gap; the raw stack remains available."
        )
    elif report["summary"]["unsupported_fraction"] > 0.5:
        notes.append(
            "More than half of the requested timeline is unsupported. Additional acquisition dates may improve coverage; long gaps were left missing."
        )
    for source in discovery or []:
        if not source.get("returned", 0):
            notes.append(
                f"No matching {source['sensor']} scenes were found; the stack contains only the available sensors."
            )
        if source.get("truncated"):
            notes.append(
                f"{source['sensor']} search reached its {source.get('stop_reason', 'result')} budget. Raise the scene limit or narrow the interval for more complete coverage."
            )
    report["coverage_notes"] = notes
    for key, name in [
        ("before_url", "before.png"),
        ("preview_url", "preview.png"),
        ("stack_url", "stack.npz"),
        ("series_url", "series.npz"),
        ("support_cog_url", "series-support.tif"),
        ("cog_url", "analysis.tif"),
        ("composite_url", "composite.tif"),
        ("provenance_url", "provenance.tif"),
        ("manifest_url", "manifest.json"),
        ("fields_csv_url", "fields.csv"),
        ("fields_geojson_url", "fields.geojson"),
    ]:
        report[key] = f"/api/runs/{identifier}/{name}"
    report["outputs"] = [
        {"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in sorted(directory.iterdir())
    ]
    report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    report["timings"] = {
        "catalog_seconds": round(discovery_seconds, 3),
        "processing_export_seconds": report["elapsed_seconds"],
        "total_seconds": round(time.perf_counter() - (workflow_started or started), 3),
    }
    (directory / "manifest.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    notify(progress, "publishing", "Publishing complete exports")
    destination = data / "runs" / identifier
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(directory, destination)
    return report


def acquire_to_coverage(
    request: StackRequest,
    observations: list[Observation],
    data: Path,
    *,
    progress: Progress | None = None,
    resume: bool = False,
):
    """Measure native-QA support before spending the remaining scene budget.

    Metadata/date proximity ranks unread candidates; measured support determines
    stopping. The target includes allowed linear estimates and uses AOI cell-date
    counts, not just scene footprints or scene-wide cloud percentages.
    """
    from rslib.acquisition import plan_stack_items

    options = {
        "resolution": request.resolution,
        "cloud_buffer_m": request.cloud_buffer_m,
        "min_clear_fraction": request.min_clear_fraction,
        "cache_dir": data / "cache" / "prepared",
        "progress": progress,
    }
    first, last = request.datetime.split("/")
    selected = list(observations)
    if request.coverage_target is not None:
        selected = []
        groups = {}
        for observation in observations:
            groups.setdefault((observation.provider, observation.item["collection"]), []).append(
                observation
            )
        for group in groups.values():
            items, _ = plan_stack_items(
                [o.item for o in group], request.bbox, request.datetime, min(2, len(group))
            )
            wanted = {item["id"] for item in items}
            selected.extend(o for o in group if o.item["id"] in wanted)
    identities = {(o.provider, o.item["collection"], o.item["id"]) for o in selected}
    remaining = [
        o
        for o in observations
        if (o.provider, o.item["collection"], o.item["id"]) not in identities
    ]
    refresh = request.refresh and not resume
    stack = build_stack(selected, request.bbox, **options, refresh=refresh)
    first_hits = {r["cache_key"]: r["cache_hit"] for r in stack.observations}
    steps = []
    while True:
        notify(
            progress,
            "evaluating",
            "Measuring observed, estimated and missing pixel dates",
            observations=len(stack.observations),
        )
        series = stack.regular_series(
            index=request.index,
            step_days=request.step_days,
            max_gap_days=request.max_gap_days,
            start=first[:10],
            end=last[:10],
        )
        inside = stack.analysis_mask()
        missing_by_day = (series.support[:, inside] == 0).mean(axis=1)
        supported = float(1 - missing_by_day.mean())
        steps.append(
            {
                "observations": len(stack.observations),
                "supported_fraction": supported,
                "observed_fraction": float((series.support[:, inside] == 1).mean()),
            }
        )
        notify(
            progress,
            "coverage",
            f"Measured support from {len(stack.observations)} scenes",
            **steps[-1],
        )
        if request.coverage_target is None:
            reason = "fixed_scene_budget"
            break
        if supported >= request.coverage_target:
            reason = "target_met"
            break
        if not remaining:
            reason = "candidate_budget_exhausted"
            break

        def priority(observation, days=series.days, missing=missing_by_day):
            timestamp = observation.item["properties"]["datetime"]
            day = np.datetime64(
                datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(UTC).date(), "D"
            )
            distance = np.abs((days - day) / np.timedelta64(1, "D"))
            proximity = np.maximum(0, 1 - distance / request.max_gap_days)
            cloud = observation.item["properties"].get("eo:cloud_cover", 100)
            cloud = float(cloud) if cloud is not None else 100
            score = float(np.dot(missing, proximity)) * (1 - min(100, max(0, cloud)) / 100)
            return (-score, observation.item["properties"]["datetime"], observation.item["id"])

        added = min(remaining, key=priority)
        remaining.remove(added)
        selected.append(added)
        # Prepare each added source once (including explicit refresh), then
        # assemble from the cache. Keep first-use cache facts in the final report.
        prepared = build_stack([added], request.bbox, **options, refresh=refresh)
        first_hits.update({r["cache_key"]: r["cache_hit"] for r in prepared.observations})
        stack = build_stack(selected, request.bbox, **options)
    stack = replace(
        stack,
        observations=tuple(
            {**r, "cache_hit": first_hits[r["cache_key"]]} for r in stack.observations
        ),
    )
    return (
        stack,
        series,
        {
            "target_supported_fraction": request.coverage_target,
            "stop_reason": reason,
            "prepared_observations": len(stack.observations),
            "unread_candidates": len(remaining),
            "steps": steps,
            "basis": "AOI cell-date support, including permitted linear estimates",
            "selection": "Initial date/footprint strata, then missing-date proximity weighted by scene cloud cover",
            "limitation": "Bounded discovered candidates; unread-source benefit is a metadata heuristic, not known pixel-clear coverage or an optimal plan",
        },
    )


def inspect_pixel(
    directory: Path,
    row: int | None = None,
    col: int | None = None,
    *,
    longitude: float | None = None,
    latitude: float | None = None,
) -> dict:
    """Read one common-grid cell and its temporal provenance from tiled exports.

    Coordinates refer to array cells (zero based), not an arbitrary point on the
    native sensor grid. Reading small COG windows avoids loading the full stack.
    """
    import rasterio
    from rasterio.warp import transform
    from rasterio.windows import Window

    report = json.loads((directory / "manifest.json").read_text())
    if report.get("schema_version") != "rslib-stack-workflow/1":
        raise ValueError("This run is not an optical stack")
    with rasterio.open(directory / "analysis.tif") as src:
        if longitude is not None or latitude is not None:
            if (
                row is not None
                or col is not None
                or longitude is None
                or latitude is None
                or not np.isfinite([longitude, latitude]).all()
            ):
                raise ValueError("Provide a row/column pair or a finite longitude/latitude pair")
            if not -180 <= longitude <= 180 or not -85 <= latitude <= 85:
                raise ValueError("Longitude/latitude outside supported range")
            px, py = transform("EPSG:4326", src.crs, [longitude], [latitude])
            row, col = src.index(px[0], py[0])
        if row is None or col is None:
            raise ValueError("Provide a row/column pair or a longitude/latitude pair")
        if not 0 <= row < src.height or not 0 <= col < src.width:
            raise ValueError("Cell lies outside the common grid")
        window = Window(col, row, 1, 1)
        values = src.read(window=window)[:, 0, 0]
        x, y = src.xy(row, col)
        lon, lat = transform(src.crs, "EPSG:4326", [x], [y])
    bbox = report["request"]["bbox"]
    if not (bbox["west"] <= lon[0] <= bbox["east"] and bbox["south"] <= lat[0] <= bbox["north"]):
        raise ValueError("Cell center lies outside the requested AOI")
    with rasterio.open(directory / "series-support.tif") as src:
        provenance = src.read(window=window)[:, 0, 0].reshape(4, len(values))
    observations = report["observations"]

    def source(value: float):
        index = int(value)
        if not 0 <= index < len(observations):
            return None
        record = observations[index]
        # Full per-band calibration/asset records remain in the manifest. Do not
        # repeat them twice per query date in an interactive point response.
        return {
            "index": index,
            **{
                key: record[key] for key in ["id", "platform", "datetime", "provider", "collection"]
            },
        }

    return {
        "run_id": report["id"],
        "row": row,
        "col": col,
        "longitude": lon[0],
        "latitude": lat[0],
        "x": x,
        "y": y,
        "crs": report["grid"]["crs"],
        "index": report["request"]["index"],
        "units": "1",
        "synthetic": report["synthetic"],
        "series": [
            {
                "day": frame["day"],
                "value": float(values[i]) if np.isfinite(values[i]) else None,
                "support": int(provenance[0, i]),
                "left_source": source(provenance[1, i]),
                "right_source": source(provenance[2, i]),
                "bracket_days": float(provenance[3, i]) if np.isfinite(provenance[3, i]) else None,
            }
            for i, frame in enumerate(report["timeline"])
        ],
    }
