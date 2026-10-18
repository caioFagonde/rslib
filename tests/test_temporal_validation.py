from dataclasses import replace

import numpy as np
import pytest
from affine import Affine
from fastapi.testclient import TestClient

from rslib.api import create_app
from rslib.raster import Grid
from rslib.stack import OpticalStack
from rslib.validation import validate_series


def analytic_stack(middle=0.2):
    # An exact linear NDVI ramp in acquisition time. A second sensor on the
    # held-out day has a deliberately conflicting value and lower quality.
    ndvi = np.array([0, middle, 0.95, 0.5], dtype="float32")
    values = np.broadcast_to(
        np.stack([(1 - ndvi) / 2, (1 + ndvi) / 2], axis=1)[:, :, None, None], (4, 2, 1, 2)
    ).copy()
    return OpticalStack(
        values,
        np.broadcast_to(np.array([1, 2, 1, 1], dtype="float32")[:, None, None], (4, 1, 2)),
        np.array(
            ["2026-01-01", "2026-01-03T10:00", "2026-01-03T12:00", "2026-01-06"],
            dtype="datetime64[us]",
        ),
        ("red", "nir"),
        Grid("EPSG:32723", Affine(30, 0, 500000, 0, -30, 7500000), 2, 1),
        tuple({"id": str(i), "platform": f"sensor-{i}"} for i in range(4)),
        {},
    )


def test_temporal_holdout_excludes_whole_day_and_counts_unscorable_edges():
    report = validate_series(analytic_stack(), max_gap_days=5)
    summary = report["summary"]
    assert summary["held_out_clear_cells"] == 6
    assert summary["scored_cells"] == 2
    assert summary["scored_fraction"] == pytest.approx(1 / 3)
    assert summary["linear"]["rmse"] == pytest.approx(0, abs=1e-7)
    assert summary["nearest"]["rmse"] == pytest.approx(0.2, abs=1e-7)
    assert report["folds"][1]["sources"] == ["1", "2"]
    assert report["folds"][0]["linear"]["rmse"] is None
    # A hidden test datum cannot affect its own prediction. Only its residual
    # changes when the withheld day is perturbed away from the linear ramp.
    changed = validate_series(analytic_stack(middle=0.8), max_gap_days=5)
    assert changed["summary"]["linear"]["bias"] == pytest.approx(-0.6, abs=1e-7)
    assert changed["summary"]["nearest"]["bias"] == pytest.approx(-0.8, abs=1e-7)


def test_gap_limit_null_metrics_and_invalid_requests():
    report = validate_series(analytic_stack(), max_gap_days=4.9)
    assert report["summary"]["scored_cells"] == 0
    assert report["summary"]["linear"]["rmse"] is None
    for gap in [0, np.nan, 91]:
        with pytest.raises(ValueError):
            validate_series(analytic_stack(), max_gap_days=gap)
    stack = analytic_stack()
    with pytest.raises(ValueError, match="three"):
        validate_series(
            replace(
                stack,
                values=stack.values[:2],
                quality=stack.quality[:2],
                times=stack.times[:2],
                observations=stack.observations[:2],
            )
        )


def test_validation_checks_input_hash_and_preserves_immutable_exports(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        report = client.post("/api/stack", json={}).json()
        manifest = tmp_path / "runs" / report["id"] / "manifest.json"
        before = manifest.read_bytes()
        response = client.get(f"/api/runs/{report['id']}/validation")
        assert response.status_code == 200, response.text
        validation = response.json()
        assert validation["synthetic"] is True
        assert validation["summary"]["scored_cells"] > 0
        assert manifest.read_bytes() == before
        stack = manifest.parent / "stack.npz"
        stack.write_bytes(stack.read_bytes() + b"changed")
        assert client.get(f"/api/runs/{report['id']}/validation").status_code == 422
