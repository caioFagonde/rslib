import asyncio
import hashlib
import json

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_bounds

from rslib.api import create_app
from rslib.demo import create_demo
from rslib.models import AnalysisRequest
from rslib.pipeline import analyze_scene
from rslib.raster import Grid, optical_calibration, read_band


def test_warp_preserves_nodata_before_scale_offset(tmp_path):
    p = tmp_path / "band.tif"
    transform = from_bounds(0, 0, 2, 2, 2, 2)
    with rasterio.open(
        p,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="uint16",
        crs="EPSG:4326",
        transform=transform,
        nodata=0,
    ) as dst:
        dst.write(np.array([[0, 2000], [3000, 4000]], dtype="uint16"), 1)
    values = read_band(str(p), Grid("EPSG:4326", transform, 2, 2), scale=0.0001, offset=-0.1)
    assert np.isnan(values[0, 0])
    np.testing.assert_allclose(values[1], [0.2, 0.3], atol=1e-7)


def test_qa_zero_is_valid_and_missing_outside_footprint(tmp_path):
    p = tmp_path / "qa.tif"
    transform = from_bounds(0, 0, 2, 2, 2, 2)
    with rasterio.open(
        p,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="uint16",
        crs="EPSG:4326",
        transform=transform,
        nodata=0,
    ) as dst:
        dst.write(np.array([[0, 0], [0, 1]], dtype="uint16"), 1)
    grid = Grid("EPSG:4326", from_bounds(0, 0, 3, 3, 3, 3), 3, 3)
    data = read_band(str(p), grid, categorical=True, zero_is_valid=True)
    assert data[1, 0] == 0 and np.isnan(data[0, 0])


def test_calibration_refuses_ambiguous_legacy_and_records_provider_rules():
    a = {"raster:bands": [{"scale": 0.0001, "offset": -0.1}]}
    with pytest.raises(ValueError, match="inconsistent"):
        optical_calibration({"collection": "sentinel-2-l2a"}, a, "earth-search")
    assert optical_calibration({"collection": "sentinel-2-c1-l2a"}, a, "earth-search")[:2] == (
        0.0001,
        -0.1,
    )
    assert optical_calibration(
        {"collection": "sentinel-2-l2a", "properties": {"s2:processing_baseline": "05.12"}},
        {},
        "planetary-computer",
    )[:2] == (0.0001, -0.1)


def test_offline_pipeline_exports_valid_georeferencing_and_checksums(tmp_path):
    fixture = create_demo(tmp_path / "demo")
    result = analyze_scene(fixture["features"][0], AnalysisRequest(size=128), tmp_path / "runs")
    assert result["synthetic"] and 0 < result["statistics"]["valid_fraction"] < 1
    directory = tmp_path / "runs" / result["id"]
    for output in result["outputs"]:
        assert (
            hashlib.sha256((directory / output["path"]).read_bytes()).hexdigest()
            == output["sha256"]
        )
    with rasterio.open(directory / "analysis.tif") as src:
        assert src.crs.to_epsg() == 4326 and src.is_tiled
        assert src.tags(ns="IMAGE_STRUCTURE")["LAYOUT"] == "COG"
        assert src.bounds.left == pytest.approx(-44.75)
        assert np.isnan(src.read(1)).any()
    assert "SYNTHETIC DEMONSTRATION" in (directory / "report.html").read_text()
    assert (
        json.loads((directory / "manifest.json").read_text())["statistics"] == result["statistics"]
    )


def test_report_escapes_scene_metadata(tmp_path):
    fixture = create_demo(tmp_path / "demo")
    fixture["features"][0]["id"] = "<script>alert(1)</script>"
    result = analyze_scene(fixture["features"][0], AnalysisRequest(size=64), tmp_path / "runs")
    html = (tmp_path / "runs" / result["id"] / "report.html").read_text()
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_api_end_to_end_and_path_validation(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        fixture = client.get("/api/demo").json()
        assert fixture["features"][0]["assets"] == {}
        r = client.post("/api/analyze", json={"size": 64})
        assert r.status_code == 200, r.text
        result = r.json()
        assert client.get(result["preview_url"]).headers["content-type"] == "image/png"
        assert client.get(result["manifest_url"]).json()["id"] == result["id"]
        assert client.get("/api/runs/bad/manifest.json").status_code == 404
        assert client.get("/api/runs/" + result["id"] + "/secret.txt").status_code == 404
        assert client.post("/api/analyze", json={"size": 999999}).status_code == 422
        assert (
            client.post(
                "/api/analyze", json={"provider": "custom", "href": "file:///etc/passwd"}
            ).status_code
            == 422
        )
        assert client.post("/api/analyze", json={"item_id": "missing"}).status_code == 404


def test_rust_api_demo(tmp_path):
    from rslib.hydro import kernel_path

    try:
        kernel_path()
    except RuntimeError:
        pytest.skip("Native kernel not built")
    with TestClient(create_app(tmp_path)) as client:
        r = client.post("/api/hydro/demo", json={"rainfall_mm_h": 18})
        assert r.status_code == 200, r.text
        assert np.isfinite(r.json()["minimum_factor_of_safety"])
        assert client.post("/api/hydro/demo", json={"rainfall_mm_h": -1}).status_code == 422


def test_textual_offline_workflow(tmp_path):
    from rslib.tui import Workbench

    async def exercise():
        app = Workbench(tmp_path)
        async with app.run_test(size=(130, 42)) as pilot:
            await pilot.press("d")
            await app.workers.wait_for_complete()
            assert len(app.scenes) == 3
            await pilot.press("a")
            await app.workers.wait_for_complete()
            assert list((tmp_path / "runs").glob("*/manifest.json"))
            assert app.query_one("#raster").image is not None

    asyncio.run(exercise())
