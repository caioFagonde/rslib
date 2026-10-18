import numpy as np
import pytest

from rslib.compositing import composite
from rslib.reconstruction import preserve_observations
from rslib.timeseries import interpolate_gaps


def test_quality_preserves_whole_spectrum_and_excludes_partial_spectra():
    cube = np.array([[[[1.0, 2.0]], [[10.0, 20.0]]], [[[3.0, 4.0]], [[30.0, np.nan]]]])
    clear = np.ones((2, 1, 2), bool)
    result = composite(cube, clear, quality=np.array([[[0.0, 0.0]], [[1.0, 1.0]]]))
    np.testing.assert_equal(result.values, [[[3.0, 2.0]], [[30.0, 20.0]]])
    assert result.source_index.tolist() == [[1, 0]]
    assert result.observation_count.tolist() == [[2, 1]]


def test_medoid_matches_independent_pairwise_objective_and_missing():
    rng = np.random.default_rng(9)
    cube = rng.random((5, 4, 2, 3), dtype=np.float32)
    clear = np.ones((5, 2, 3), bool)
    clear[:, 0, 0] = False
    clear[0, 1, 2] = False
    result = composite(cube, clear, method="medoid")
    for y, x in [(0, 1), (1, 2)]:
        candidates = np.flatnonzero(clear[:, y, x])
        distances = np.array(
            [
                sum(np.abs(cube[i, :, y, x] - cube[j, :, y, x]).sum() for j in candidates)
                for i in candidates
            ]
        )
        assert result.source_index[y, x] == candidates[distances.argmin()]
    assert result.source_index[0, 0] == -1 and np.isnan(result.values[:, 0, 0]).all()


def test_temporal_gap_uses_real_days_preserves_observations_and_limits_bracket():
    values = np.array(
        [[np.nan, 1.0], [0.0, 2.0], [np.nan, np.nan], [10.0, 4.0], [np.nan, 5.0]], dtype="float32"
    )
    times = np.array(
        ["2026-01-01", "2026-01-02", "2026-01-04", "2026-01-12", "2026-02-01"],
        dtype="datetime64[D]",
    )
    result = interpolate_gaps(values, times, max_gap_days=10)
    assert result.values[2, 0] == pytest.approx(2.0)
    assert result.values[2, 1] == pytest.approx(2.4)
    assert result.provenance[:, 0].tolist() == [0, 1, 2, 1, 0]
    assert result.left_index[2, 0] == 1 and result.right_index[2, 0] == 3
    assert result.bracket_days[2, 0] == 10
    np.testing.assert_equal(result.values[np.isfinite(values)], values[np.isfinite(values)])
    assert np.isnan(interpolate_gaps(values, times, max_gap_days=9).values[2]).all()
    with pytest.raises(ValueError, match="strictly increasing"):
        interpolate_gaps(values, times[::-1], max_gap_days=10)


def test_model_reconstruction_never_overwrites_observed_and_retains_unknown():
    observed = np.array([[[0.1, np.nan, np.nan]], [[0.2, np.nan, np.nan]]], dtype="float32")
    proposal = np.array([[[99.0, 0.3, np.nan]], [[99.0, 0.4, 0.5]]])
    result = preserve_observations(
        observed, np.array([[True, False, False]]), proposal, model_std=np.full_like(proposal, 0.05)
    )
    np.testing.assert_equal(result.values[:, 0, 0], observed[:, 0, 0])
    assert result.provenance.tolist() == [[1, 3, 0]]
    assert np.isnan(result.values[:, 0, 2]).all()
    assert np.isnan(result.model_std[:, 0, 0]).all()
    np.testing.assert_allclose(result.model_std[:, 0, 1], 0.05)


def test_temporal_chunks_preserve_global_support_at_chunk_boundaries():
    values = np.zeros((3, 1, 50000), dtype="float32")
    values[1] = np.nan
    values[2] = 10
    times = np.array(["2026-01-01", "2026-01-03", "2026-01-11"], dtype="datetime64[D]")
    result = interpolate_gaps(values, times, max_gap_days=10)
    np.testing.assert_equal(result.values[1], np.full((1, 50000), 2, dtype="float32"))
    assert (result.left_index[1] == 0).all() and (result.right_index[1] == 2).all()
    assert (result.provenance[1] == 2).all() and (result.bracket_days[1] == 10).all()
