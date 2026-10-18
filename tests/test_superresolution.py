from pathlib import Path

import numpy as np
import pytest
from rasterio.transform import array_bounds, from_origin

from rslib.raster import Grid
from rslib.superresolution import upscale_grid, verify_weights


def test_upscaled_grid_preserves_bounds_and_pixel_centers():
    grid = Grid("EPSG:32723", from_origin(400000, 7500000, 10, 10), 17, 19)
    result = upscale_grid(grid)
    assert result.transform.a == 2.5 and result.transform.e == -2.5
    np.testing.assert_equal(
        array_bounds(grid.height, grid.width, grid.transform),
        array_bounds(result.height, result.width, result.transform),
    )
    with pytest.raises(ValueError):
        upscale_grid(grid, 0)


def test_missing_or_modified_weights_are_rejected_without_execution(tmp_path: Path):
    with pytest.raises(ValueError, match="Missing"):
        verify_weights(tmp_path)
    (tmp_path / "model.safetensor").write_bytes(b"not a checkpoint")
    with pytest.raises(ValueError, match="SHA-256"):
        verify_weights(tmp_path)


def test_scaled_halo_tiles_match_whole_pointwise_model_and_restore_nodata():
    torch = pytest.importorskip("torch")
    from rslib.deep import predict_tiles

    class Upsample(torch.nn.Module):
        def forward(self, x):
            return torch.nn.functional.interpolate(x, scale_factor=4, mode="nearest") * 2

    model = Upsample().train()
    image = np.random.default_rng(8).random((4, 35, 47), dtype=np.float32)
    image[:, 13, 17] = np.nan
    result = predict_tiles(model, image, tile_size=32, halo=7, output_scale=4)
    expected = (image * 2).repeat(4, axis=1).repeat(4, axis=2)
    np.testing.assert_equal(result, expected)
    assert model.training


def test_model_shape_contract_and_training_mode_restored_on_failure():
    torch = pytest.importorskip("torch")
    from rslib.deep import predict_tiles

    model = torch.nn.Identity().train()
    with pytest.raises(ValueError, match="declared output scale"):
        predict_tiles(
            model, np.ones((4, 16, 16), dtype="float32"), tile_size=16, halo=2, output_scale=4
        )
    assert model.training
