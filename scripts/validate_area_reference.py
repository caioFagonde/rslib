"""Compare saved area results with exactextract's independent coverage kernel.

Run with: uv run --with exactextract==0.3.0 python scripts/validate_area_reference.py RUN_DIR
The comparison isolates fractional-cell aggregation on the SAME projected geometry
and raster values. It does not validate reflectance, harmonization or gap filling.
"""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from exactextract import exact_extract
from exactextract.feature import JSONFeatureSource
from exactextract.raster import NumPyRasterSource
from rasterio.transform import array_bounds

from rslib.fields import FieldBoundary, projected_field
from rslib.raster import Grid

parser = argparse.ArgumentParser()
parser.add_argument("run", type=Path)
parser.add_argument("--output", type=Path, default=Path("docs/showcase/24-area-reference.json"))
args = parser.parse_args()
report = json.loads((args.run / "manifest.json").read_text())
g = report["grid"]
grid = Grid(g["crs"], Affine(*g["transform"]), g["width"], g["height"])
w, s, e, n = array_bounds(grid.height, grid.width, grid.transform)
wkt = rasterio.crs.CRS.from_string(grid.crs).to_wkt()
with rasterio.open(args.run / "analysis.tif") as src:
    values = src.read()
with rasterio.open(args.run / "series-support.tif") as src:
    support = src.read(list(range(1, len(values) + 1)))
# Numerical agreement tolerances chosen before running the comparison. They are
# not application-level accuracy limits for satellite data or subpixel estimates.
mean_tolerance, area_tolerance_m2 = 1e-6, 0.25
comparisons = []
for field in report["request"]["fields"]:
    boundary = FieldBoundary(**field)
    geometry = projected_field(boundary, grid)
    polygon = {"type": "Feature", "properties": {}, "geometry": geometry.__geo_interface__}
    result = next(f for f in report["fields"] if f["id"] == boundary.id)
    fixed = ((support == 1) & np.isfinite(values)).all(axis=0)
    for i, day in enumerate(report["timeline"]):
        for mode, mask, mean_key, area_key in [
            ("observed", support[i] == 1, "observed_mean", "observed_area_m2"),
            ("supported", support[i] > 0, "supported_mean", None),
            ("fixed_observed", fixed, "fixed_observed_mean", None),
        ]:
            data = np.where(mask, values[i], np.nan)
            raster = NumPyRasterSource(
                data, xmin=w, ymin=s, xmax=e, ymax=n, nodata=np.nan, srs_wkt=wkt
            )
            reference = exact_extract(
                raster,
                JSONFeatureSource([polygon], srs_wkt=wkt),
                ["mean", "count"],
                max_cells_in_memory=1_000_000,
            )[0]["properties"]
            sample = result["timeline"][i]
            expected_mean = sample[mean_key]
            area = reference["count"] * abs(grid.transform.a * grid.transform.e)
            expected_area = (
                sample[area_key]
                if area_key
                else sample["observed_area_m2"] + sample["estimated_area_m2"]
                if mode == "supported"
                else result["fixed_observed_area_m2"]
            )
            area_error = abs(area - expected_area)
            if expected_mean is None:
                assert reference["count"] == 0 and (
                    reference["mean"] is None or not np.isfinite(reference["mean"])
                )
                mean_error = 0.0
            else:
                mean_error = abs(reference["mean"] - expected_mean)
                assert mean_error <= mean_tolerance, (boundary.id, day["day"], mode, mean_error)
            assert area_error <= area_tolerance_m2, (boundary.id, day["day"], mode, area_error)
            comparisons.append(
                {
                    "field": boundary.id,
                    "day": day["day"],
                    "statistic": mode,
                    "has_value": expected_mean is not None,
                    "absolute_mean_error": mean_error,
                    "absolute_area_error_m2": area_error,
                }
            )
evidence = {
    "kind": "Numerical agreement against an external fractional-coverage implementation",
    "run_id": report["id"],
    "synthetic": report["synthetic"],
    "crs": grid.crs,
    "exactextract_version": importlib.metadata.version("exactextract"),
    "shapely_version": importlib.metadata.version("shapely"),
    "mean_tolerance": mean_tolerance,
    "area_tolerance_m2": area_tolerance_m2,
    "maximum_mean_error": max(c["absolute_mean_error"] for c in comparisons),
    "maximum_area_error_m2": max(c["absolute_area_error_m2"] for c in comparisons),
    "statistic_evaluations": len(comparisons),
    "numeric_evaluations": sum(c["has_value"] for c in comparisons),
    "comparisons": comparisons,
    "inputs_sha256": {
        name: hashlib.sha256((args.run / name).read_bytes()).hexdigest()
        for name in ["manifest.json", "analysis.tif", "series-support.tif", "fields.geojson"]
    },
    "limits": "Same projected geometry and input cells; does not independently validate projection, physical within-cell homogeneity, source imagery, sensor harmonization or temporal interpolation accuracy.",
}
args.output.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n")
print(
    json.dumps(
        {k: v for k, v in evidence.items() if k not in ["comparisons", "inputs_sha256"]}, indent=2
    )
)
