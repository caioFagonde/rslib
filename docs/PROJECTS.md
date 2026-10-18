# Optical monitoring projects

The optical workspace now supports named polygon areas, a geographic map, persisted recipes/run history, and area-weighted time series. Open `/workflows.html` after building the frontend and starting `uv run rslib serve`.

## Browser workflow

1. Create a project name and import a WGS84 GeoJSON FeatureCollection, Feature, Polygon or MultiPolygon. Feature IDs and `properties.name` identify the monitoring areas. Polygon holes are retained. You can also draw vertices on the map and choose **Finish polygon**. Imported live areas set the acquisition bounding box to their envelope; the synthetic fixture keeps its fixed Itatiaia extent.
2. Choose the dates, sensors, grid and QA parameters. **Scene budget / sensor** caps the candidate pool. With **Acquire toward a coverage goal**, preparation starts with up to two planned scenes per sensor/collection, measures actual support, then adds candidates while needed. The goal counts observed cells plus permitted temporal estimates over the requested AOI and query dates. It is not a field-specific coverage guarantee or a reconstruction-accuracy score.
3. **Save project**, then **Run preparation**. Subsequent runs save the visible recipe to a new revision before executing. The selected snapshot is checked at execution to prevent another session's update from silently changing the requested run. Revision conflicts return HTTP 409. A run records the recipe revision used, even if the project is edited while processing.
4. Click an area on the map, or choose it above the chart. Review observed, estimated and missing area for the selected date. **Observed area mean** excludes estimates. **Observed + estimated mean** includes them. **Fixed observed footprint** uses exactly the same cells observed on every requested date; it reports no curve when that common footprint is empty.
5. Switch the map to **Inspect cells** to read the original analysis cell at a geographic location. The server transforms the coordinates into the analysis grid. Source acquisition records remain available in the cell inspector. The map can display the selected index date, temporal support, or the latest-clear composite; opacity and the base map are separate controls.
6. Download the field CSV, boundaries, raster exports or manifest. Reopen the project from **Saved projects** and choose a saved run. Completed run references and recipes persist in `data/projects.sqlite3`; artifacts remain under `data/runs/<id>`. A server restart does not erase them. The browser and TUI use the [durable queue](JOBS.md), with progress, cancellation, retry and recovery of interrupted jobs. Retries keep the submitted recipe revision.

The acquisition loop records each measured support fraction, prepared observation count, unread candidate count and stop reason. It stops at `target_met` or `candidate_budget_exhausted`. Candidate choice uses missing-date proximity and scene-cloud metadata; native QA determines measured support after reading. Discovery remains bounded and selection is a heuristic. Failure to meet the goal is reported, with unsupported data left missing. Raising the interpolation bracket is not evidence of improved scientific accuracy.

## Area statistics

Field boundaries are validated for finite, closed 2D rings and valid topology. Duplicate IDs, self intersections, malformed holes and areas outside the requested acquisition bounding box are rejected. Limits: 32 areas, 5000 original vertices per area, bounded projection densification, and two million combined field-window cells.

Geometry is densified in longitude/latitude before projection to the analysis CRS. GEOS computes polygon intersections with individual grid cells, including holes and partial boundary cells. The [Shapely intersection API](https://shapely.readthedocs.io/en/stable/reference/shapely.intersection.html) supports the vectorized operations; intermediate batches are bounded. This is fractional-cell weighting, rather than center-inclusion or all-touched pixel counts.

Areas are **planar m² in the declared projected metre CRS**, with hectares shown as m² / 10,000. They are not ellipsoidal surface areas. Means assume that the index value is constant within each analysis cell; finer boundary weights do not create subpixel spectral observations. Missing area includes field portions without supported cells. Overlapping monitoring areas are evaluated independently and must not be summed as disjoint land areas.

The area CSV has one row per field/query date, including:

- field ID/name, index, dimensionless units, synthetic flag, area CRS and total area;
- observed, estimated and missing areas/fractions;
- observed-only mean, supported mean and fixed-observed-footprint mean;
- fixed observed footprint area, which is constant over the requested timeline.

The manifest retains the recipe and exact boundaries, source observations, QA/calibration details, acquisition steps and output checksums. `timings` separates catalog discovery, processing/export and workflow total. These clocks exclude API queueing, response transfer and browser rendering; source-read bytes, native-read phase times and peak RSS are not yet instrumented.

## Python and API

```python
from pathlib import Path
from rslib.workflows import StackRequest, prepare_optical

report = await prepare_optical(StackRequest(
    demo=False,
    bbox={"west": -44.66, "south": -22.41, "east": -44.64, "north": -22.39},
    datetime="2026-06-01/2026-07-16",
    max_scenes_per_sensor=12,
    coverage_target=0.8,
    fields=[{
        "id": "west", "name": "Western area",
        "geometry": {"type": "Polygon", "coordinates": [[
            [-44.659, -22.409], [-44.651, -22.409],
            [-44.651, -22.391], [-44.659, -22.391], [-44.659, -22.409]
        ]]},
    }],
), Path("data"))
print(report["acquisition"], report["fields"])
```

`POST /api/projects` accepts `{name, recipe}`. `GET /api/projects` lists up to 100 local projects; `GET /api/projects/{id}` includes up to 50 recent run references. `POST /api/projects/{id}` accepts `{name, recipe, revision}` for an optimistic update. `POST /api/projects/{id}/runs` requires `{revision}` and executes that saved snapshot synchronously. The browser and TUI instead submit a durable `POST /api/jobs` with `{project_id, revision}`; see [jobs](JOBS.md). Project metadata uses SQLite transactions and bound parameters; this is a local workspace, without multi-user access control or remote artifact sharing.

## Terminal

```bash
uv run rslib project list
uv run rslib project run PROJECT_ID
uv run rslib tui --project PROJECT_ID
# In the TUI: w runs the saved project; f opens area statistics;
# [ and ] change dates; g toggles temporal support on the raster.

uv run rslib stack --live --limit 12 --coverage-target 0.8 \
  --bbox=-44.66,-22.41,-44.64,-22.39 --areas fields.geojson
```

The TUI reopens a current completed run without acquisition. It retains the project's polygon boundaries, sensor/grid choices and coverage goal when executing visible date/index/QA edits. Browser and TUI revisions share the same conflict checks and history store. The standalone CLI `--areas` input is a WGS84 GeoJSON FeatureCollection.

## Validation

Analytic fixtures verify fractional boundary cells, holes, tiny slivers, area conservation, weighted means, changing support and the fixed observed cohort. API checks exercise project persistence across application restart, revision conflicts, map-coordinate inspection, GeoJSON/CSV artifacts and acquisition stopping. CLI and Textual tests execute and reopen the same saved project. These checks validate the declared arithmetic and behavior. Whole-date reconstruction holdouts are now available from the browser and CLI; the first satellite result and its limited scoring coverage are recorded in VALIDATION.md. Harmonization accuracy and general reconstruction performance remain unvalidated.

The live-run aggregation was also compared with [exactextract](https://isciences.github.io/exactextract/exactextract.html), using its separate fractional-coverage kernel on identical projected polygons and COG values. [Recorded differences](showcase/24-area-reference.json): maximum mean error 7.30 × 10⁻¹² and area error 0.000245 m² across 276 evaluations, including empty-statistic checks. This isolates aggregation agreement; it does not independently validate projection or the physical interpretation of input pixels.
