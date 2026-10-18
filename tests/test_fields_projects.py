import csv
import io

import numpy as np
import pytest
import shapely
from affine import Affine
from fastapi.testclient import TestClient
from pydantic import ValidationError
from rasterio.warp import transform_geom

from rslib.api import create_app
from rslib.fields import FieldBoundary, cell_areas, field_series
from rslib.raster import Grid


def test_fractional_areas_and_hole_are_analytic_not_center_counts():
    grid = Grid("EPSG:32723", Affine(10, 0, 0, 0, -10, 20), 2, 2)
    # Covers 3/4 of each left cell and 1/4 of each right cell. A center
    # inclusion or all-touched rasterization cannot produce these weights.
    polygon = shapely.box(2.5, 0, 12.5, 20)
    _, areas = cell_areas(polygon, grid)
    np.testing.assert_allclose(areas, [[75, 25], [75, 25]], atol=1e-10)
    with_hole = shapely.Polygon(
        [(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)], [[(5, 5), (15, 5), (15, 15), (5, 15), (5, 5)]]
    )
    _, areas = cell_areas(with_hole, grid)
    np.testing.assert_allclose(areas, [[75, 75], [75, 75]])
    sliver = shapely.box(0, 0, 0.01, 20)
    _, areas = cell_areas(sliver, grid)
    assert areas.sum() == pytest.approx(0.2)


def test_area_means_missing_area_and_constant_observed_cohort():
    grid = Grid("EPSG:32723", Affine(10, 0, 500000, 0, -10, 7500020), 2, 2)
    polygon = shapely.box(500002.5, 7500000, 500012.5, 7500020)
    geometry = transform_geom(grid.crs, "EPSG:4326", polygon.__geo_interface__)
    field = FieldBoundary(id="a", name="Test field", geometry=geometry)
    values = np.array([[[1, 3], [5, 7]], [[2, 4], [np.nan, 8]]], dtype="float32")
    support = np.array([[[1, 1], [1, 1]], [[1, 2], [0, 1]]], dtype="uint8")
    result = field_series(
        [field],
        values,
        support,
        np.array(["2026-01-01", "2026-01-06"], dtype="datetime64[D]"),
        grid,
    )[0]
    assert result["area_m2"] == pytest.approx(200, abs=0.0001)
    first, second = result["timeline"]
    assert first["observed_mean"] == pytest.approx(3.5, abs=1e-5)
    assert second["observed_area_m2"] == pytest.approx(100, abs=1e-4)
    assert second["estimated_area_m2"] == pytest.approx(25, abs=1e-4)
    assert second["missing_area_m2"] == pytest.approx(75, abs=1e-4)
    assert second["observed_mean"] == pytest.approx(3.5, abs=1e-5)
    assert second["supported_mean"] == pytest.approx(3.6, abs=1e-5)
    # Same cells on both dates, regardless of the different valid populations.
    assert result["fixed_observed_area_m2"] == pytest.approx(100, abs=1e-4)
    assert first["fixed_observed_mean"] == pytest.approx(2.5, abs=1e-5)
    assert second["fixed_observed_mean"] == pytest.approx(3.5, abs=1e-5)


def test_invalid_boundary_is_rejected():
    for coordinates in [
        [],
        [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]],
        [[[0, 0], [1, 0], [1, 1], [0, 1]]],
    ]:
        with pytest.raises(ValidationError):
            FieldBoundary(
                id="bad", name="Invalid", geometry={"type": "Polygon", "coordinates": coordinates}
            )


def test_project_restart_revision_and_field_exports(tmp_path):
    field = {
        "id": "west",
        "name": "Western area",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-44.659, -22.409],
                    [-44.65, -22.409],
                    [-44.65, -22.391],
                    [-44.659, -22.391],
                    [-44.659, -22.409],
                ]
            ],
        },
    }
    spec = {"name": "Itatiaia synthetic test", "recipe": {"demo": True, "fields": [field]}}
    with TestClient(create_app(tmp_path)) as client:
        response = client.post("/api/projects", json=spec)
        assert response.status_code == 200, response.text
        project = response.json()
        identifier = project["id"]
        response = client.post(f"/api/projects/{identifier}/runs", json={"revision": 1})
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["fields"][0]["area_m2"] > 1_000_000
        assert report["timings"]["total_seconds"] >= report["timings"]["processing_export_seconds"]
        assert client.get(report["timeline"][0]["map_image_url"]).status_code == 200
        rows = list(csv.DictReader(io.StringIO(client.get(report["fields_csv_url"]).text)))
        assert len(rows) == 10 and rows[0]["field_name"] == "Western area"
        assert (
            float(rows[0]["observed_area_m2"])
            == report["fields"][0]["timeline"][0]["observed_area_m2"]
        )
        response = client.get(f"/api/runs/{report['id']}/pixel?longitude=-44.655&latitude=-22.4")
        assert response.status_code == 200, response.text
        p = response.json()
        assert abs(p["longitude"] + 44.655) < 0.0003
        updated = client.post(
            f"/api/projects/{identifier}", json={**spec, "name": "Updated", "revision": 1}
        )
        assert updated.json()["revision"] == 2
        assert (
            client.post(f"/api/projects/{identifier}", json={**spec, "revision": 1}).status_code
            == 409
        )
        assert (
            client.post(f"/api/projects/{identifier}/runs", json={"revision": 1}).status_code == 409
        )
    # Open a fresh application against the same on-disk project database.
    with TestClient(create_app(tmp_path)) as client:
        restored = client.get(f"/api/projects/{identifier}").json()
        assert restored["name"] == "Updated" and restored["recipe"]["fields"] == [field]
        assert restored["runs"][0]["id"] == report["id"]
        assert restored["runs"][0]["recipe_revision"] == 1
        assert client.get("/api/projects").json()["projects"][0]["field_count"] == 1
        bad = {
            **field,
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
            },
        }
        assert (
            client.post(
                "/api/projects", json={"name": "Outside", "recipe": {"fields": [bad]}}
            ).status_code
            == 422
        )


def test_adaptive_acquisition_measures_support_and_stops_at_goal_or_budget(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        exhausted = client.post("/api/stack", json={"coverage_target": 1}).json()
        progress = exhausted["acquisition"]
        assert progress["stop_reason"] == "candidate_budget_exhausted"
        assert progress["steps"][0]["observations"] == 4
        assert exhausted["summary"]["observations"] == 8
        coverage = [s["supported_fraction"] for s in progress["steps"]]
        assert all(b >= a - 1e-9 for a, b in zip(coverage[:-1], coverage[1:], strict=True))
        assert coverage[-1] == pytest.approx(1 - exhausted["summary"]["unsupported_fraction"])
        assert exhausted["summary"]["cache_hits"] == 0
        assert progress["unread_candidates"] == 0
        assert "not met" in exhausted["coverage_notes"][0]
        met = client.post("/api/stack", json={"coverage_target": 0.01}).json()
        assert met["acquisition"]["stop_reason"] == "target_met"
        assert met["summary"]["observations"] == 4
        assert met["summary"]["cache_hits"] == 4
        assert met["acquisition"]["unread_candidates"] == 4
        assert len(met["acquisition"]["steps"]) == 1


def test_saved_project_cli_and_terminal_area_navigation(tmp_path):
    import asyncio

    from textual.widgets import DataTable, TabbedContent
    from typer.testing import CliRunner

    from rslib.cli import app as cli
    from rslib.projects import Projects, ProjectSpec
    from rslib.tui import Workbench

    field = {
        "id": "one",
        "name": "Monitoring area",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-44.659, -22.409],
                    [-44.651, -22.409],
                    [-44.651, -22.391],
                    [-44.659, -22.391],
                    [-44.659, -22.409],
                ]
            ],
        },
    }
    store = Projects(tmp_path / "projects.sqlite3")
    project = store.create(ProjectSpec(name="Terminal project", recipe={"fields": [field]}))
    runner = CliRunner()
    listed = runner.invoke(cli, ["project", "list", "--data", str(tmp_path)])
    assert listed.exit_code == 0 and "Terminal project" in listed.stdout
    result = runner.invoke(cli, ["project", "run", project["id"], "--data", str(tmp_path)])
    assert result.exit_code == 0, result.output

    async def exercise():
        app = Workbench(tmp_path, project_id=project["id"])
        async with app.run_test(size=(150, 48)):
            assert app.last_stack is not None
            app.action_fields()
            assert app.query_one("#area-table", DataTable).row_count == 1
            app.action_next_frame()
            assert app.stack_frame == 1
            assert app.query_one("#tabs", TabbedContent).active == "areas-tab"
            app.action_stack()
            await app.workers.wait_for_complete()
            assert app.last_stack["fields"][0]["name"] == "Monitoring area"
            assert app.project["revision"] == 2

    asyncio.run(exercise())
    assert len(store.get(project["id"])["runs"]) == 2
