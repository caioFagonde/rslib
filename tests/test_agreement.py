from dataclasses import replace

import numpy as np
import pytest
from affine import Affine
from fastapi.testclient import TestClient

from rslib.agreement import sensor_agreement
from rslib.api import create_app
from rslib.raster import Grid
from rslib.stack import OpticalStack


def analytic_stack():
    bands = ("blue", "green", "red", "nir", "swir16", "swir22")
    image = np.arange(36, dtype="float32").reshape(6, 2, 3) / 100 + 0.1
    values = np.stack([image, image])
    values[1, :, 0, 0] = np.nan
    records = (
        {
            "id": "oli",
            "platform": "landsat-9",
            "family": "landsat-oli",
            "datetime": "2026-01-01T12:00:00Z",
            "adjustment": {"method": "identity"},
        },
        {
            "id": "msi",
            "platform": "sentinel-2b",
            "family": "sentinel-2",
            "datetime": "2026-01-02T13:00:00Z",
            "adjustment": {
                "coefficients": {band: {"slope": 1.1, "offset": -0.02} for band in bands}
            },
        },
    )
    return OpticalStack(
        values,
        np.ones((2, 2, 3), dtype="float32"),
        np.array(["2026-01-01T12:00", "2026-01-02T13:00"], dtype="datetime64[us]"),
        bands,
        Grid("EPSG:32723", Affine(30, 0, 500000, 0, -30, 7500000), 3, 2),
        records,
        {},
    )


def test_paired_metrics_reversible_transform_and_display_sampling():
    report = sensor_agreement(analytic_stack(), min_cells=1, display_samples=2)
    pair = report["pairs"][0]
    assert pair["separation_hours"] == 25
    assert pair["common_clear_cells"] == 5 and pair["common_clear_fraction"] == 5 / 6
    assert pair["spectral_angle"]["median"] == pytest.approx(0, abs=2e-6)
    assert pair["ndvi"]["rmse"] == 0
    for band in pair["bands"]:
        assert band["current"]["rmse"] == 0
        assert band["current"]["samples"] == 5
        assert band["current"]["correlation"] == pytest.approx(1)
        assert band["before_local_bandpass"]["rmse"] > 0
        assert len(band["scatter"]["reference"]) == 2
    assert pair["scatter_cells"] == {"rows": [0, 1], "columns": [1, 2]}
    changed = analytic_stack()
    changed.values[1, 0] += 0.02
    biased = sensor_agreement(changed, min_cells=1)["pairs"][0]["bands"][0]
    assert biased["current"]["bias"] == pytest.approx(0.02, abs=1e-7)
    assert biased["current"]["rmse"] == pytest.approx(0.02, abs=1e-7)


def test_pairing_is_disjoint_and_missing_support_is_explicit():
    stack = analytic_stack()
    empty = sensor_agreement(stack, min_cells=6)
    assert empty["pairs"] == []
    assert empty["rejected_pairs"][0]["common_clear_cells"] == 5
    assert len(sensor_agreement(stack, min_cells=1, max_hours=24)["unpaired_source_indices"]) == 2
    # Two possible comparison scenes cannot reuse the same reference scene.
    duplicate = replace(
        stack,
        values=np.concatenate([stack.values, stack.values[1:]]),
        quality=np.concatenate([stack.quality, stack.quality[1:]]),
        times=np.append(stack.times, np.datetime64("2026-01-02T14:00", "us")),
        observations=stack.observations + ({**stack.observations[1], "id": "later"},),
    )
    paired = sensor_agreement(duplicate, min_cells=1)
    assert len(paired["pairs"]) == 1
    assert paired["pairs"][0]["comparison"]["id"] == "msi"
    assert paired["unpaired_source_indices"] == [2]
    records = (
        {**stack.observations[0], "family": "hls-l30"},
        {**stack.observations[1], "family": "hls-s30", "adjustment": {"method": "upstream HLS"}},
    )
    pair = sensor_agreement(replace(stack, observations=records), min_cells=1)["pairs"][0]
    assert not pair["before_local_bandpass_available"]
    assert pair["bands"][0]["before_local_bandpass"] is None


def test_invalid_inputs_and_constant_spectra():
    stack = analytic_stack()
    for kwargs in [
        {"max_hours": np.nan},
        {"max_hours": 169},
        {"min_cells": 0},
        {"display_samples": 1001},
    ]:
        with pytest.raises(ValueError):
            sensor_agreement(stack, **kwargs)
    stack.values[:] = 0
    pair = sensor_agreement(stack, min_cells=1)["pairs"][0]
    assert pair["bands"][0]["current"]["correlation"] is None
    assert pair["spectral_angle"]["median"] is None
    assert pair["ndvi"] is None


def test_agreement_api_and_immutable_input_checksums(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        report = client.post("/api/stack", json={}).json()
        path = f"/api/runs/{report['id']}/agreement"
        result = client.get(path + "?max_hours=168")
        assert result.status_code == 200, result.text
        result = result.json()
        assert result["synthetic"] and len(result["pairs"]) > 0
        assert result["input_sha256"]["stack.npz"]
        assert client.get(path + "?max_hours=169").status_code == 422
        import asyncio

        from textual.widgets import DataTable

        from rslib.tui import Workbench

        async def terminal():
            app = Workbench(tmp_path)
            async with app.run_test(size=(170, 48)) as pilot:
                app.last_stack = report
                app.run_diagnostics("agreement")
                await app.workers.wait_for_complete()
                # Five-day fixture spacing gives no pair within 48 hours; the
                # terminal must retain that result instead of broadening it.
                assert app.query_one("#diagnostics-table", DataTable).row_count == 0
                app.run_diagnostics("validation")
                await app.workers.wait_for_complete()
                await pilot.pause(0.05)
                assert app.query_one("#diagnostics-table", DataTable).row_count == 8

        asyncio.run(terminal())
        stack = tmp_path / "runs" / report["id"] / "stack.npz"
        stack.write_bytes(stack.read_bytes() + b"corrupt")
        assert client.get(path).status_code == 422
