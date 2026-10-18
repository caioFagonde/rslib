import numpy as np
import pytest
from scipy.optimize import minimize

from rslib.spectral import bcy_sentinel_candidates, fcls, fit_pca, tasseled_cap, vca


def test_verified_run_spectral_exports_and_immutable_inputs(tmp_path):
    import hashlib
    import json

    import rasterio
    from typer.testing import CliRunner

    from rslib.cli import app
    from rslib.spectral_workflow import analyze_spectra
    from rslib.workflows import StackRequest, run_stack_workflow

    run = run_stack_workflow(StackRequest(), None, tmp_path)
    directory = tmp_path / "runs" / run["id"]
    before = (directory / "stack.npz").read_bytes()
    output = tmp_path / "spectral"
    cli = CliRunner().invoke(app, ["spectral-analysis", str(directory), str(output)])
    assert cli.exit_code == 0, cli.output
    report = json.loads((output / "report.json").read_text())
    assert report["synthetic"] and report["fcls"]["valid_cells"] > 0
    for artifact in report["outputs"]:
        assert (
            hashlib.sha256((output / artifact["path"]).read_bytes()).hexdigest()
            == artifact["sha256"]
        )
    with rasterio.open(output / "abundance.tif") as raster:
        values = raster.read()
        assert raster.crs.to_epsg() == 32723
        assert raster.descriptions == ("Endmember 1", "Endmember 2", "Endmember 3")
        keep = np.isfinite(values).all(axis=0)
        np.testing.assert_allclose(values[:, keep].sum(axis=0), 1, atol=2e-7)
        assert (~keep).any()
    assert (directory / "stack.npz").read_bytes() == before
    with pytest.raises(FileExistsError):
        analyze_spectra(directory, output)
    (directory / "stack.npz").write_bytes(before + b"tamper")
    with pytest.raises(ValueError, match="checksum"):
        analyze_spectra(directory, tmp_path / "tampered")
    assert not (tmp_path / "tampered").exists()


def simplex():
    endmembers = np.array(
        [[0.08, 0.15, 0.45, 0.26], [0.21, 0.32, 0.12, 0.38], [0.5, 0.19, 0.28, 0.14]]
    )
    abundance = np.vstack((np.eye(3), np.random.default_rng(45).dirichlet(np.ones(3), 200)))
    return endmembers, abundance, abundance @ endmembers, ("green", "red", "nir", "swir")


def test_pca_fit_reuse_inverse_and_nodata():
    _, _, spectra, bands = simplex()
    training = spectra.copy()
    training[9] = np.nan
    valid = np.ones(len(training), bool)
    valid[20] = False
    basis = fit_pca(training, bands=bands, components=4, valid=valid)
    scores = basis.transform(training, bands=bands, valid=valid)
    assert basis.fit_samples == len(training) - 2
    assert np.isnan(scores[[9, 20]]).all()
    keep = np.isfinite(scores).all(axis=1)
    np.testing.assert_allclose(scores[keep].mean(axis=0), 0, atol=1e-15)
    np.testing.assert_allclose(
        scores[keep] @ basis.loadings + basis.mean, training[keep], atol=1e-14
    )
    np.testing.assert_allclose(basis.loadings @ basis.loadings.T, np.eye(4), atol=1e-14)
    assert sum(basis.variance_fraction) == pytest.approx(1)
    assert basis.variance_fraction[:2].sum() == pytest.approx(1)
    assert np.all(basis.loadings[np.arange(4), np.argmax(abs(basis.loadings), axis=1)] >= 0)
    # Apply the same basis to a different date, without silently recentering it.
    np.testing.assert_allclose(
        basis.transform(spectra + 0.1, bands=bands), (spectra + 0.1 - basis.mean) @ basis.loadings.T
    )
    with pytest.raises(ValueError, match="order"):
        basis.transform(training, bands=bands[::-1])
    with pytest.raises(ValueError, match="variance"):
        fit_pca(np.ones((10, 4)), bands=bands)
    with pytest.raises(ValueError, match="integer"):
        fit_pca(training, bands=bands, components=True)


@pytest.mark.parametrize("projection", ["affine", "projective"])
def test_vca_recovers_pure_vertices_with_missing_and_deterministic_seed(projection):
    endmembers, _, spectra, bands = simplex()
    spectra = np.vstack((np.full(4, np.nan), spectra))
    result = vca(spectra, bands=bands, projection=projection, seed=17)
    assert set(result.flat_indices) == {1, 2, 3}
    for i, index in enumerate(result.flat_indices):
        np.testing.assert_allclose(result.endmembers[i], endmembers[index - 1], atol=1e-14)
        np.testing.assert_allclose(result.observed_spectra[i], spectra[index], atol=1e-14)
    again = vca(spectra, bands=bands, projection=projection, seed=17)
    np.testing.assert_array_equal(result.flat_indices, again.flat_indices)
    with pytest.raises(ValueError, match="independent"):
        vca(np.ones((10, 4)), bands=bands)
    with pytest.raises(ValueError, match="projection"):
        vca(spectra, bands=bands, projection="auto")


def test_fcls_exact_mixtures_faces_outside_simplex_and_independent_optimizer():
    endmembers, abundance, spectra, bands = simplex()
    mixtures = np.vstack((spectra, [0.85, 0.01, 0.04, 0.02], [0.01, 0.8, 0.6, 0.5], [np.nan] * 4))
    result = fcls(mixtures, endmembers, bands=bands, endmember_bands=bands)
    np.testing.assert_allclose(result.abundance[: len(spectra)], abundance, atol=1e-12)
    assert np.max(result.rmse[: len(spectra)]) < 1e-13
    assert np.min(result.abundance[:-1]) >= 0
    np.testing.assert_allclose(result.abundance[:-1].sum(axis=1), 1, atol=1e-14)
    assert np.isnan(result.abundance[-1]).all() and np.isnan(result.rmse[-1])
    assert np.max(result.optimality_gap[:-1]) < 1e-12
    for i in (0, 10, len(spectra), len(spectra) + 1):
        y = mixtures[i]
        independent = minimize(
            lambda a, y=y: 0.5 * np.square(a @ endmembers - y).sum(),
            np.full(3, 1 / 3),
            jac=lambda a, y=y: (a @ endmembers - y) @ endmembers.T,
            method="SLSQP",
            bounds=[(0, 1)] * 3,
            constraints={"type": "eq", "fun": lambda a: a.sum() - 1, "jac": lambda a: np.ones(3)},
            options={"ftol": 1e-14, "maxiter": 200},
        )
        assert independent.success
        np.testing.assert_allclose(result.abundance[i], independent.x, atol=2e-6)
    with pytest.raises(ValueError, match="order"):
        fcls(spectra, endmembers, bands=bands, endmember_bands=bands[::-1])
    with pytest.raises(ValueError, match="independent"):
        fcls(spectra, endmembers * 0, bands=bands, endmember_bands=bands)


def test_tasseled_cap_published_coefficients_and_calibration_guard():
    bands = ("blue", "green", "red", "nir", "swir16", "swir22")
    result = tasseled_cap(
        np.eye(6), bands=bands, sensor="landsat-8-oli", radiometry="toa_reflectance"
    )
    np.testing.assert_allclose(result[0], [0.3029, -0.2941, 0.1511])
    np.testing.assert_allclose(result[5], [0.1872, -0.1608, -0.4559])
    np.testing.assert_allclose(result.sum(axis=0), [2.3099, -0.4414, -0.1502], atol=1e-12)
    with pytest.raises(ValueError, match="not SR"):
        tasseled_cap(
            np.eye(6), bands=bands, sensor="landsat-8-oli", radiometry="surface_reflectance"
        )
    with pytest.raises(ValueError, match="OLI"):
        tasseled_cap(np.eye(6), bands=bands, sensor="sentinel-2", radiometry="toa_reflectance")


def test_bcy_threshold_variant_boundaries_nodata_and_not_detected_is_not_clear():
    green = np.array([0.175, 0.18, 0.4, 0.3, 0.3, np.nan, -0.1])
    red = np.array([0.1, 0.1, 0.5, 0.2, 0.2, 0.1, 0.1])
    swir = np.array([0.3, 0.3, 0.3, 0.1, 0.15, 0.3, 0.3])
    result = bcy_sentinel_candidates(
        green, red, swir, radiometry="sentinel-2-l1c-toa_reflectance", swir_threshold=0.1
    )
    np.testing.assert_array_equal(result, [1, 2, 2, 1, 2, 0, 0])
    stricter = bcy_sentinel_candidates(
        green, red, swir, radiometry="sentinel-2-l1c-toa_reflectance", swir_threshold=0.2
    )
    assert stricter[4] == 1
    with pytest.raises(ValueError, match="TOA"):
        bcy_sentinel_candidates(
            green, red, swir, radiometry="surface_reflectance", swir_threshold=0.1
        )
