import numpy as np
import pytest

from rslib.ml import fit_grouped_conformal, spatial_blocks


def test_spatial_groups_are_stable_and_never_leak():
    pytest.importorskip("sklearn")
    rng = np.random.default_rng(2)
    x = rng.normal(size=(300, 3))
    y = 2 * x[:, 0] + rng.normal(size=300) * 0.1
    groups = np.repeat(np.arange(30), 10)
    result = fit_grouped_conformal(x, y, groups, feature_names=["red", "nir", "dem"], trees=30)
    sets = {k: set(v) for k, v in result.report["groups"].items()}
    assert not sets["train"] & sets["calibration"]
    assert not sets["train"] & sets["test"]
    assert not sets["test"] & sets["calibration"]
    mean, low, high = result.predict(x[:3])
    assert np.all(low <= mean) and np.all(high >= mean)
    assert 0 <= result.report["test"]["interval_coverage"] <= 1
    assert spatial_blocks(np.array([-1, 1, 999, 1001]), np.zeros(4)).tolist() == [
        "-1:0",
        "0:0",
        "0:0",
        "1:0",
    ]


def test_model_requires_spatial_groups_and_feature_schema():
    pytest.importorskip("sklearn")
    with pytest.raises(ValueError):
        fit_grouped_conformal(np.ones((10, 2)), np.ones(10), np.ones(10), feature_names=["a", "b"])


def test_tiled_inference_context_missing_data_and_training_state():
    torch = pytest.importorskip("torch")
    from rslib.deep import predict_tiles

    model = torch.nn.Conv2d(2, 1, 3, padding=1, bias=False)
    with torch.no_grad():
        model.weight.fill_(1 / 18)
    image = np.random.default_rng(42).normal(size=(2, 33, 39)).astype("float32")
    result = predict_tiles(model, image, tile_size=16, halo=2)
    with torch.inference_mode():
        expected = model(torch.from_numpy(image)[None])[0].numpy()
    # Different edge padding is explicit; all interior seams must match full-image inference.
    np.testing.assert_allclose(result[:, 1:-1, 1:-1], expected[:, 1:-1, 1:-1], atol=1e-6)
    assert model.training
    image[:, 5, 6] = np.nan
    assert np.isnan(predict_tiles(model, image, tile_size=16, halo=2)[:, 5, 6]).all()
