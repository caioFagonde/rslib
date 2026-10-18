import asyncio
import hashlib

import numpy as np
import rasterio
from fastapi.testclient import TestClient

from rslib.api import create_app
from rslib.stack import OpticalStack


def test_operational_recipe_exports_valid_cogs_support_and_reuses_preparation(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response = client.post("/api/stack", json={})
        assert response.status_code == 200, response.text
        report = response.json()
        summary = report["summary"]
        assert summary["observations"] == 8 and len(summary["platforms"]) == 5
        assert summary["filled_fraction"] > 0 and summary["observed_fraction"] > 0
        assert (
            abs(
                sum(
                    summary[k]
                    for k in ["filled_fraction", "observed_fraction", "unsupported_fraction"]
                )
                - 1
            )
            < 1e-7
        )
        directory = tmp_path / "runs" / report["id"]
        for name in ["stack_url", "series_url", "cog_url", "provenance_url", "manifest_url"]:
            assert client.get(report[name]).status_code == 200
        assert (
            client.get(report["timeline"][0]["support_url"]).headers["content-type"] == "image/png"
        )
        for output in report["outputs"]:
            assert (
                hashlib.sha256((directory / output["path"]).read_bytes()).hexdigest()
                == output["sha256"]
            )
        with rasterio.open(directory / "analysis.tif") as src:
            assert src.tags(ns="IMAGE_STRUCTURE")["LAYOUT"] == "COG"
            assert src.count == 10 and src.descriptions[0] == "ndvi:2026-06-01"
            assert src.crs.to_epsg() == 32723 and src.res == (30, 30)
        stack = OpticalStack.load(directory / "stack.npz")
        with rasterio.open(directory / "series-support.tif") as src:
            assert src.tags(ns="IMAGE_STRUCTURE")["LAYOUT"] == "COG"
            assert src.count == 40 and src.descriptions[10] == "left_source:2026-06-01"
        # Inspect real exported cells with each support state. The API must retain
        # the exact value and original source identities, including both brackets.
        with np.load(directory / "series.npz", allow_pickle=False) as series:
            for support in [0, 1, 2]:
                day, row, col = np.argwhere(
                    (series["support"] == support) & stack.analysis_mask()[None]
                )[0]
                response = client.get(
                    f"/api/runs/{report['id']}/pixel", params={"row": int(row), "col": int(col)}
                )
                assert response.status_code == 200, response.text
                pixel = response.json()
                assert pixel["units"] == "1" and pixel["index"] == "ndvi"
                assert -44.66 <= pixel["longitude"] <= -44.64
                assert -22.41 <= pixel["latitude"] <= -22.39
                sample = pixel["series"][day]
                assert sample["support"] == support
                if support == 0:
                    assert sample["value"] is None
                    assert sample["left_source"] is sample["right_source"] is None
                else:
                    assert sample["value"] == float(series["values"][day, row, col])
                    for side in ["left", "right"]:
                        source = int(series[f"{side}_source"][day, row, col])
                        assert (
                            sample[f"{side}_source"]["id"] == report["observations"][source]["id"]
                        )
                    assert sample["bracket_days"] == float(series["bracket_days"][day, row, col])
        for row, col in [(-1, 0), (stack.grid.height, 0), (0, stack.grid.width)]:
            assert (
                client.get(
                    f"/api/runs/{report['id']}/pixel", params={"row": row, "col": col}
                ).status_code
                == 422
            )
        outside = np.argwhere(~stack.analysis_mask())
        if len(outside):
            row, col = outside[0]
            assert (
                client.get(
                    f"/api/runs/{report['id']}/pixel", params={"row": int(row), "col": int(col)}
                ).status_code
                == 422
            )
        assert client.get("/api/runs/not-a-run/pixel?row=0&col=0").status_code == 404
        # Two native sensor grids and DN conventions resolve stable non-NIR bands
        # onto the same synthetic physical field, within resampling/quantization.
        a, b = stack.values[0], stack.values[1]
        clear = np.isfinite(a).all(axis=0) & np.isfinite(b).all(axis=0)
        assert clear.sum() > 1000
        for band in [0, 1, 2, 4, 5]:
            assert np.abs(a[band, clear] - b[band, clear]).mean() < 0.0003
        changed = client.post("/api/stack", json={"step_days": 10, "max_gap_days": 10}).json()
        assert changed["summary"]["cache_hits"] == 8 and changed["summary"]["regular_dates"] == 5
        assert client.post("/api/stack", json={"sensors": ["bad"]}).status_code == 422
        assert client.post("/api/stack", json={"datetime": "../.."}).status_code == 422
        assert client.post("/api/stack", json={"href": "file:///etc/passwd"}).status_code == 422


def test_terminal_recipe_and_date_support_navigation(tmp_path):
    from rslib.tui import Workbench

    async def exercise():
        app = Workbench(tmp_path)
        async with app.run_test(size=(150, 48)):
            app.action_stack()
            await app.workers.wait_for_complete()
            assert app.last_stack is not None, app.query_one("#status").render()
            assert app.last_stack["summary"]["observations"] == 8
            app.action_next_frame()
            assert app.stack_frame == 1
            app.action_support()
            assert app.stack_support
            app.action_previous_frame()
            assert app.stack_frame == 0
            assert app.query_one("#raster").image is not None

    asyncio.run(exercise())
