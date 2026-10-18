import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from rslib.harmonization import (
    COMMON_BANDS,
    bandpass_adjust,
    hls_clear,
    sensor_profile,
    stack_asset,
)
from rslib.models import BBox
from rslib.preparation import metric_grid, prepare_scene
from rslib.raster import Grid
from rslib.stack import Observation, OpticalStack, build_stack


def write(path, values, transform, *, nodata=None):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype=values.dtype,
        crs="EPSG:32723",
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(values, 1)


def test_platform_specific_bandpass_and_narrow_nir_contract():
    item = {
        "collection": "sentinel-2-c1-l2a",
        "properties": {"platform": "sentinel-2b"},
        "assets": {"nir": {"href": "broad"}, "nir08": {"href": "narrow"}},
    }
    profile = sensor_profile(item)
    assert stack_asset(item, "nir", profile)["href"] == "narrow"
    adjusted, meta = bandpass_adjust(
        np.full((6, 1, 1), 0.2, dtype="float32"), COMMON_BANDS, profile
    )
    np.testing.assert_allclose(
        adjusted[:, 0, 0], [0.19156, 0.2007, 0.19622, 0.19932, 0.1997, 0.19774], rtol=1e-6
    )
    assert "BRDF" in meta["limitations"]
    del item["assets"]["nir08"]
    with pytest.raises(ValueError, match="B8A"):
        stack_asset(item, "nir", profile)
    item["properties"]["platform"] = "unknown"
    with pytest.raises(ValueError, match="explicit platform"):
        sensor_profile(item)


def test_hls_not_adjusted_twice_and_quality_bits():
    profile = sensor_profile({"collection": "HLSS30.v2.0"})
    values = np.array([[[0.2, np.nan]]], dtype="float32")
    adjusted, _ = bandpass_adjust(values, ("red",), profile)
    np.testing.assert_equal(adjusted, values)
    qa = np.array([0, 32, 64, 128, 192, 2, 4, 8, 16, 255, np.nan])
    assert hls_clear(qa).tolist() == [
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    ]


def test_common_grid_is_snapped_metric_and_rejects_unbounded_aoi():
    bbox = BBox(west=-44.66, south=-22.41, east=-44.64, north=-22.39)
    grid = metric_grid(bbox)
    assert grid.crs == "EPSG:32723"
    assert grid.transform.c % 30 == 0 and grid.transform.f % 30 == 0
    with pytest.raises(ValueError, match="metre"):
        metric_grid(bbox, crs="EPSG:4326")
    with pytest.raises(ValueError, match="increase resolution"):
        metric_grid(BBox(west=-45, south=-24, east=-44, north=-22))


def test_cloud_pixels_are_excluded_before_area_aggregation(tmp_path):
    # One cloudy 10 m source pixel in a 30 m output cell. It must never bleed
    # into the average even if the caller deliberately accepts 8/9 clear support.
    transform = from_origin(500000, 7500000, 10, 10)
    reflectance = np.full((12, 12), 0.2, dtype="float32")
    reflectance[4, 4] = 10
    qa = np.full((12, 12), 4, dtype="uint8")
    qa[4, 4] = 9
    write(tmp_path / "red.tif", reflectance, transform)
    write(tmp_path / "qa.tif", qa, transform)
    item = {
        "id": "test",
        "collection": "sentinel-2-c1-l2a",
        "properties": {"platform": "sentinel-2a"},
        "assets": {
            "red": {"href": str(tmp_path / "red.tif"), "raster:bands": [{"scale": 1, "offset": 0}]},
            "scl": {"href": str(tmp_path / "qa.tif")},
        },
    }
    grid = Grid("EPSG:32723", from_origin(500030, 7499970, 30, 30), 1, 1)
    values, quality, _ = prepare_scene(
        item,
        "local",
        sensor_profile(item),
        ("red",),
        grid,
        cloud_buffer_m=0,
        min_clear_fraction=0.8,
    )
    # Output center is cloudy, conservative center rule rejects it. Move cloud
    # off center to test average support without weakening the center rule.
    assert np.isnan(values).all()
    qa[4, 4], qa[3, 3] = 4, 9
    reflectance[4, 4], reflectance[3, 3] = 0.2, 10
    write(tmp_path / "red.tif", reflectance, transform)
    write(tmp_path / "qa.tif", qa, transform)
    values, quality, _ = prepare_scene(
        item,
        "local",
        sensor_profile(item),
        ("red",),
        grid,
        cloud_buffer_m=0,
        min_clear_fraction=0.8,
    )
    assert values[0, 0, 0] == pytest.approx(0.2)
    assert quality[0, 0] == pytest.approx(8 / 9, abs=1e-6)
    values, _, _ = prepare_scene(
        item,
        "local",
        sensor_profile(item),
        ("red",),
        grid,
        cloud_buffer_m=0,
        min_clear_fraction=0.9,
    )
    assert np.isnan(values).all()


def test_partial_scene_edge_does_not_claim_full_support(tmp_path):
    transform = from_origin(500010, 7500000, 10, 10)
    qa = np.full((9, 9), 4, dtype="uint8")
    write(tmp_path / "r.tif", np.full((9, 9), 0.2, dtype="float32"), transform)
    write(tmp_path / "q.tif", qa, transform)
    item = {
        "id": "edge",
        "collection": "sentinel-2-c1-l2a",
        "properties": {"platform": "sentinel-2a"},
        "assets": {
            "red": {"href": str(tmp_path / "r.tif"), "raster:bands": [{"scale": 1}]},
            "scl": {"href": str(tmp_path / "q.tif")},
        },
    }
    grid = Grid("EPSG:32723", from_origin(500000, 7500000, 30, 30), 1, 1)
    values, quality, _ = prepare_scene(
        item,
        "local",
        sensor_profile(item),
        ("red",),
        grid,
        cloud_buffer_m=0,
        min_clear_fraction=0.9,
    )
    assert np.isnan(values).all() and quality[0, 0] == 0


def test_daily_mosaic_regular_gaps_source_identity_and_round_trip(tmp_path):
    grid = Grid("EPSG:32723", from_origin(500000, 7500000, 30, 30), 2, 1)
    values = np.full((4, 2, 1, 2), np.nan, dtype="float32")
    values[0, :, 0, 0] = [0.2, 0.6]
    values[1, :, 0, 1] = [0.3, 0.5]
    values[2, :, 0, :] = [[0.2, 0.2], [0.6, 0.6]]
    values[3, :, 0, :] = [[0.4, 0.4], [0.4, 0.4]]
    records = tuple(
        {"id": str(i), "datetime": t}
        for i, t in enumerate(
            ["2026-01-01T01:00Z", "2026-01-01T02:00Z", "2026-01-11T01:00Z", "2026-02-10T01:00Z"]
        )
    )
    times = np.array([r["datetime"].removesuffix("Z") for r in records], dtype="datetime64[us]")
    stack = OpticalStack(
        values, np.ones((4, 1, 2), dtype="float32"), times, ("red", "nir"), grid, records, {}
    )
    daily = stack.daily()
    assert len(daily.days) == 3 and daily.source_index[0].tolist() == [[0, 1]]
    series = stack.regular_series(
        step_days=5, max_gap_days=15, start="2025-12-27", end="2026-02-15"
    )
    q = list(series.days).index(np.datetime64("2026-01-06"))
    assert series.support[q].tolist() == [[2, 2]]
    assert series.left_source[q].tolist() == [[0, 1]] and series.right_source[q].tolist() == [
        [2, 2]
    ]
    np.testing.assert_allclose(series.values[q, 0], [0.5, 0.375], atol=1e-6)
    assert series.support[0].sum() == 0 and series.support[-1].sum() == 0
    assert series.support[list(series.days).index(np.datetime64("2026-01-21"))].sum() == 0
    path = tmp_path / "stack.npz"
    stack.save(path)
    restored = OpticalStack.load(path)
    np.testing.assert_equal(restored.values, stack.values)
    np.testing.assert_equal(restored.times, stack.times)
    assert restored.grid == grid


def test_scene_cache_duplicate_identity_and_fail_before_loading(tmp_path, monkeypatch):
    import rslib.stack as module

    calls = []

    def prepare(item, provider, profile, bands, grid, **kwargs):
        calls.append(item["id"])
        return (
            np.full((len(bands), grid.height, grid.width), 0.2, dtype="float32"),
            np.ones((grid.height, grid.width), dtype="float32"),
            [],
        )

    monkeypatch.setattr(module, "prepare_scene", prepare)
    bbox = BBox(west=-44.66, south=-22.41, east=-44.64, north=-22.39)
    item = {
        "id": "S2",
        "collection": "sentinel-2-c1-l2a",
        "properties": {"platform": "sentinel-2b", "datetime": "2026-01-01T00:00:00Z"},
        "assets": {"red": {"href": "unused"}},
    }
    observation = Observation(item, "local")
    first = build_stack([observation, observation], bbox, bands=("red",), cache_dir=tmp_path)
    second = build_stack([observation], bbox, bands=("red",), cache_dir=tmp_path)
    assert calls == ["S2"] and len(first.observations) == 1 and second.observations[0]["cache_hit"]
    np.testing.assert_equal(first.values, second.values)
    # A damaged preparation file is disposable; rebuilding must recover the
    # same analytical values without letting the cache become a dependency.
    next(tmp_path.glob("*.npz")).write_bytes(b"corrupted preparation")
    recovered = build_stack([observation], bbox, bands=("red",), cache_dir=tmp_path)
    np.testing.assert_equal(recovered.values, first.values)
    assert calls == ["S2", "S2"] and not recovered.observations[0]["cache_hit"]
    evicted = build_stack(
        [observation], bbox, bands=("red",), cache_dir=tmp_path, cache_max_bytes=1
    )
    assert evicted.processing["cache_evicted_files"] == 1 and not list(tmp_path.glob("*.npz"))
    with pytest.raises(ValueError, match="HLS mode"):
        build_stack([observation], bbox, bands=("red",), harmonization="hls", cache_dir=tmp_path)
    with pytest.raises(ValueError, match="B8A"):
        build_stack([observation], bbox, bands=("nir",), cache_dir=tmp_path)


def test_date_stratified_acquisition_avoids_redundant_overlap():
    from rslib.acquisition import plan_stack_items

    bbox = BBox(west=-1, south=-1, east=1, north=1)
    polygon = {"type": "Polygon", "coordinates": [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]]}
    items = [
        {
            "id": f"{day}-{i}",
            "collection": "s2",
            "geometry": polygon,
            "properties": {"datetime": f"2026-01-{day:02d}T10:00:00Z", "eo:cloud_cover": i + 10},
        }
        for day in [2, 12, 22, 28]
        for i in [0, 1]
    ]
    selected, report = plan_stack_items(items, bbox, "2026-01-01/2026-01-31", 3)
    assert len(selected) == 3 and len(report["selected_days"]) == 3
    assert report["selected_days"] == ["2026-01-02", "2026-01-12", "2026-01-22"]
    assert all(item["id"].endswith("-0") for item in selected)


def test_acquisition_keeps_both_tiles_when_one_day_needs_them():
    from rslib.acquisition import plan_stack_items

    bbox = BBox(west=-1, south=-1, east=1, north=1)
    items = []
    for i, (w, e) in enumerate([(-1, 0), (0, 1)]):
        items.append(
            {
                "id": str(i),
                "collection": "s2",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[w, -1], [e, -1], [e, 1], [w, 1], [w, -1]]],
                },
                "properties": {"datetime": "2026-01-02T10:00:00Z", "eo:cloud_cover": 0},
            }
        )
    selected, report = plan_stack_items(items, bbox, "2026-01-01/2026-01-31", 2)
    assert len(selected) == 2 and report["selected_days"] == ["2026-01-02"]


def test_xarray_interoperability_preserves_grid_sources_and_days(tmp_path):
    pytest.importorskip("xarray")
    grid = Grid("EPSG:32723", from_origin(500000, 7500000, 30, 30), 2, 1)
    times = np.array(["2026-01-01"], dtype="datetime64[D]")
    stack = OpticalStack(
        np.ones((1, 1, 1, 2), dtype="float32"),
        np.ones((1, 1, 2), dtype="float32"),
        times,
        ("red",),
        grid,
        ({"id": "test", "platform": "landsat-8", "provider": "local"},),
        {},
    )
    dataset = stack.to_xarray()
    assert dataset.reflectance.dims == ("time", "band", "y", "x")
    np.testing.assert_equal(dataset.x.values, [500015, 500045])
    np.testing.assert_equal(dataset.y.values, [7499985])
    assert (
        dataset.platform.values.tolist() == ["landsat-8"]
        and dataset.reflectance.attrs["grid_mapping"] == "spatial_ref"
    )
    stack.save(tmp_path / "days.npz")
    np.testing.assert_equal(
        OpticalStack.load(tmp_path / "days.npz").times, times.astype("datetime64[us]")
    )


def test_signing_retries_transient_responses_but_not_denied_access(monkeypatch):
    import httpx

    from rslib.raster import sign_planetary_asset

    monkeypatch.setattr("rslib.raster.time.sleep", lambda _: None)
    statuses = iter([503, 429, 200])
    calls = []

    def respond(request):
        calls.append(request)
        status = next(statuses)
        return httpx.Response(
            status, json={"href": "https://example.test/signed"}, headers={"Retry-After": "0"}
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert (
            sign_planetary_asset("https://example.test/source", client=client)
            == "https://example.test/signed"
        )
    assert len(calls) == 3
    denied = []

    def forbidden(request):
        denied.append(request)
        return httpx.Response(403)

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            sign_planetary_asset("https://example.test/source", client=client)
    assert len(denied) == 1


def test_native_retry_resolves_fresh_asset_credentials(monkeypatch):
    from rasterio.errors import RasterioIOError

    import rslib.preparation as module

    seen = []
    signed = iter(["https://example.test/first", "https://example.test/fresh"])
    monkeypatch.setattr(module, "_href", lambda *_: next(signed))
    monkeypatch.setattr(module.time, "sleep", lambda _: None)

    def read(href, *args, **kwargs):
        seen.append(href)
        if len(seen) == 1:
            raise RasterioIOError("temporary source failure")
        return "prepared"

    monkeypatch.setattr(module, "_native_window", read)
    grid = Grid("EPSG:32723", from_origin(500000, 7500000, 30, 30), 1, 1)
    assert (
        module._read_native_asset({"href": "unused"}, "planetary-computer", grid, 120) == "prepared"
    )
    assert seen == ["https://example.test/first", "https://example.test/fresh"]
