"""Fractional-cell polygon statistics on a declared projected analysis grid."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
import rasterio
import shapely
from pydantic import BaseModel, ConfigDict, Field, field_validator
from rasterio.warp import transform_geom
from rasterio.windows import Window, from_bounds
from shapely.geometry import shape

from rslib.models import BBox
from rslib.raster import Grid


class FieldBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(pattern=r"^[\w-]{1,80}$")
    name: str = Field(min_length=1, max_length=160)
    geometry: dict

    @field_validator("geometry")
    @classmethod
    def valid_geometry(cls, value):
        if value.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError("Fields require WGS84 Polygon or MultiPolygon geometry")
        polygons = value.get("coordinates", [])
        if value["type"] == "Polygon":
            polygons = [polygons]
        count = 0
        try:
            if not polygons:
                raise ValueError("Field has no polygon")
            for polygon in polygons:
                if not polygon:
                    raise ValueError("Field has no exterior ring")
                for ring in polygon:
                    count += len(ring)
                    points = np.asarray(ring, dtype="float64")
                    if (
                        points.ndim != 2
                        or points.shape[1] != 2
                        or len(points) < 4
                        or not np.isfinite(points).all()
                        or not np.array_equal(points[0], points[-1])
                        or (np.abs(points[:, 0]) > 180).any()
                        or (np.abs(points[:, 1]) > 85).any()
                    ):
                        raise ValueError(
                            "Rings need closed, finite 2D longitude/latitude coordinates"
                        )
            if count > 5000:
                raise ValueError("Field exceeds 5000 vertices; simplify the boundary")
            geometry = shape(value)
            if geometry.is_empty or geometry.area <= 0 or not geometry.is_valid:
                raise ValueError(f"Invalid field topology: {shapely.is_valid_reason(geometry)}")
            if geometry.bounds[2] - geometry.bounds[0] > 6:
                raise ValueError("Split fields spanning more than six longitude degrees")
        except (TypeError, KeyError, IndexError) as exc:
            raise ValueError("Malformed polygon coordinates") from exc
        return json.loads(shapely.to_geojson(geometry))


def validate_fields(fields: list[FieldBoundary], bbox: BBox) -> None:
    if len({f.id for f in fields}) != len(fields):
        raise ValueError("Field IDs must be unique")
    envelope = shapely.box(*bbox.bounds)
    for field in fields:
        if not envelope.covers(shape(field.geometry)):
            raise ValueError(f"Field {field.name} lies outside the acquisition bounding box")


def projected_field(field: FieldBoundary, grid: Grid):
    # Densify longitude/latitude segments before projection. GeoJSON edges are
    # linear in source coordinates; long edges curve in the target projection.
    source = shape(field.geometry)
    if source.length / 0.001 + shapely.get_num_coordinates(source) > 20000:
        raise ValueError("Field perimeter exceeds the projection densification budget")
    geographic = shapely.segmentize(source, max_segment_length=0.001)
    return shape(transform_geom("EPSG:4326", grid.crs, geographic.__geo_interface__))


def cell_areas(geometry, grid: Grid) -> tuple[Window, np.ndarray]:
    """Exact planar polygon/cell intersections, including holes and tiny slivers.

    Values later applied to these areas assume each analysis cell is constant.
    Areas are in the grid's projected m², not ellipsoidal surface area.
    """
    crs = rasterio.crs.CRS.from_user_input(grid.crs)
    if not crs.is_projected or crs.linear_units != "metre" or grid.transform.b or grid.transform.d:
        raise ValueError("Field statistics require an unrotated projected metre grid")
    if grid.transform.a <= 0 or grid.transform.e >= 0:
        raise ValueError("Field statistics require a north-up grid")
    raw = from_bounds(*geometry.bounds, transform=grid.transform)
    x0, y0 = max(0, math.floor(raw.col_off)), max(0, math.floor(raw.row_off))
    x1 = min(grid.width, math.ceil(raw.col_off + raw.width))
    y1 = min(grid.height, math.ceil(raw.row_off + raw.height))
    if x1 <= x0 or y1 <= y0:
        raise ValueError("Field does not intersect the analysis grid")
    if (x1 - x0) * (y1 - y0) > 1_048_576:
        raise ValueError("Field exceeds the common-grid intersection budget")
    rows, cols = np.indices((y1 - y0, x1 - x0))
    west = grid.transform.c + (cols.ravel() + x0) * grid.transform.a
    north = grid.transform.f + (rows.ravel() + y0) * grid.transform.e
    areas = np.empty(len(west), dtype="float64")
    for start in range(0, len(west), 65536):
        stop = start + 65536
        cells = shapely.box(
            west[start:stop],
            north[start:stop] + grid.transform.e,
            west[start:stop] + grid.transform.a,
            north[start:stop],
        )
        areas[start:stop] = shapely.area(shapely.intersection(cells, geometry))
    return Window(x0, y0, x1 - x0, y1 - y0), areas.reshape(rows.shape)


def _weighted_mean(values, weights, mask):
    area = float(weights[mask].sum())
    return float(np.dot(values[mask], weights[mask]) / area) if area > 0 else None


def field_series(
    fields: list[FieldBoundary],
    values: np.ndarray,
    support: np.ndarray,
    days: np.ndarray,
    grid: Grid,
) -> list[dict]:
    if values.shape != support.shape or values.shape != (len(days), grid.height, grid.width):
        raise ValueError("Field series arrays must match dates and grid")
    results = []
    intersections = 0
    for field in fields:
        geometry = projected_field(field, grid)
        window, weights = cell_areas(geometry, grid)
        intersections += weights.size
        if intersections > 2_097_152:
            raise ValueError("Combined field windows exceed two million cells; split the project")
        rows, cols = window.toslices()
        v, s = values[:, rows, cols], support[:, rows, cols]
        total = float(geometry.area)
        # A fixed cohort uses exactly the same observed cells on EVERY requested
        # date. If none survive, its mean is null rather than silently changing.
        fixed = ((s == 1) & np.isfinite(v)).all(axis=0)
        fixed_area = float(weights[fixed].sum())
        timeline = []
        for i, day in enumerate(days):
            observed = (s[i] == 1) & np.isfinite(v[i])
            estimated = (s[i] == 2) & np.isfinite(v[i])
            valid = observed | estimated
            observed_area, estimated_area = (
                float(weights[observed].sum()),
                float(weights[estimated].sum()),
            )

            timeline.append(
                {
                    "day": str(day),
                    "observed_mean": _weighted_mean(v[i], weights, observed),
                    "supported_mean": _weighted_mean(v[i], weights, valid),
                    "fixed_observed_mean": _weighted_mean(v[i], weights, fixed),
                    "observed_area_m2": observed_area,
                    "estimated_area_m2": estimated_area,
                    "missing_area_m2": max(0.0, total - observed_area - estimated_area),
                    "observed_fraction": observed_area / total,
                    "estimated_fraction": estimated_area / total,
                    "missing_fraction": max(0.0, 1 - (observed_area + estimated_area) / total),
                }
            )
        results.append(
            {
                "id": field.id,
                "name": field.name,
                "area_m2": total,
                "area_crs": grid.crs,
                "fixed_observed_area_m2": fixed_area,
                "fixed_observed_fraction": fixed_area / total,
                "timeline": timeline,
            }
        )
    return results


def export_fields(
    directory: Path, fields: list[FieldBoundary], results: list[dict], index: str, synthetic: bool
) -> None:
    with (directory / "fields.csv").open("w", newline="") as file:
        columns = [
            "field_id",
            "field_name",
            "index",
            "units",
            "synthetic",
            "area_crs",
            "field_area_m2",
            "fixed_observed_area_m2",
            "day",
            "observed_mean",
            "supported_mean",
            "fixed_observed_mean",
            "observed_area_m2",
            "estimated_area_m2",
            "missing_area_m2",
            "observed_fraction",
            "estimated_fraction",
            "missing_fraction",
        ]
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for result in results:
            for frame in result["timeline"]:
                writer.writerow(
                    {
                        "field_id": result["id"],
                        "field_name": result["name"],
                        "index": index,
                        "units": "1",
                        "synthetic": synthetic,
                        "area_crs": result["area_crs"],
                        "field_area_m2": result["area_m2"],
                        "fixed_observed_area_m2": result["fixed_observed_area_m2"],
                        **frame,
                    }
                )
    (directory / "fields.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": field.id,
                        "properties": {"name": field.name},
                        "geometry": field.geometry,
                    }
                    for field in fields
                ],
            },
            allow_nan=False,
        )
        + "\n"
    )
