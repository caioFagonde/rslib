import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.transform import from_bounds

from rslib.models import BBox
from rslib.surface import build_surface, terrarium_encode


def test_terrarium_preserves_negative_elevations_and_quantization():
    elevations = np.array([[-32768.0, -100.5, 0, 1024.125, 32767.9999]])
    encoded = terrarium_encode(elevations).astype("float64")
    decoded = encoded[..., 0] * 256 + encoded[..., 1] + encoded[..., 2] / 256 - 32768
    np.testing.assert_allclose(decoded, elevations, atol=1 / 256)
    with pytest.raises(ValueError):
        terrarium_encode(np.array([[np.nan]]))


def test_surface_mosaic_retains_nodata_in_cog_and_records_display_fill(tmp_path):
    path = tmp_path / "dem.tif"
    values = np.full((64, 64), 1200.0, dtype="float32")
    values[30, 30] = -9999
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=64,
        height=64,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_bounds(0, 0, 1, 1, 64, 64),
        nodata=-9999,
    ) as dst:
        dst.write(values, 1)
    item = {"id": "dem", "collection": "cop-dem-glo-30", "assets": {"data": {"href": str(path)}}}
    result = build_surface([item], BBox(west=0, south=0, east=1, north=1), tmp_path / "runs", 64)
    assert result["display_filled_pixels"] == 1
    directory = tmp_path / "runs" / result["id"]
    with rasterio.open(directory / "elevation.tif") as src:
        assert np.isnan(src.read(1)[30, 30])
    encoded = np.asarray(Image.open(directory / "elevation.png")).astype("float64")
    assert encoded[30, 30, 0] * 256 + encoded[30, 30, 1] + encoded[30, 30, 2] / 256 - 32768 == 1200


def test_surface_rejects_large_data_gaps(tmp_path):
    with pytest.raises(ValueError):
        build_surface([], BBox(west=0, south=0, east=1, north=1), tmp_path, 64)
