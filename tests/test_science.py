import numpy as np
import pytest

from rslib.indices import (
    best_pixel_composite,
    landsat_clear,
    ratio,
    sentinel_clear,
    spectral_index,
    summarize,
)
from rslib.soil import (
    decode_soilgrids,
    independent_stock_mc,
    saxton_rawls,
    soc_stock,
    soilgrids_vrt,
    stock_change,
)
from rslib.terrain import derivatives, infinite_slope


def test_index_calculation_and_zero_denominator():
    bands = {"nir": np.array([0.6, 0, np.nan]), "red": np.array([0.2, 0, 0.1])}
    assert spectral_index("ndvi", bands)[0] == pytest.approx(0.5)
    assert np.isnan(spectral_index("ndvi", bands)[1:]).all()
    assert ratio(np.array([1.0]), np.array([0.0])).dtype == np.float32


def test_evi_requires_reflectance_units():
    bands = {"nir": np.array([0.6]), "red": np.array([0.2]), "blue": np.array([0.1])}
    assert spectral_index("evi", bands)[0] == pytest.approx(
        2.5 * 0.4 / (0.6 + 6 * 0.2 - 7.5 * 0.1 + 1)
    )


def test_conservative_scl_and_zero_buffer():
    labels = np.arange(12).reshape(3, 4)
    assert sentinel_clear(labels, 0).sum() == 3
    assert sentinel_clear(labels, 1).sum() == 0
    clear = np.full((7, 7), 4)
    clear[3, 3] = 9
    assert sentinel_clear(clear, 0).sum() == 48
    assert sentinel_clear(clear, 1).sum() == 44


def test_landsat_cloud_shadow_snow_saturation():
    qa = np.array([0, 1, 1 << 3, 1 << 4, 1 << 5, 1 << 7], dtype="uint16")
    assert landsat_clear(qa).tolist() == [True, False, False, False, False, True]
    assert not landsat_clear(np.array([0]), np.array([1]))[0]


def test_composite_retains_source_and_missing_pixels():
    data = np.array([[[1.0, np.nan, 3.0]], [[2.0, np.nan, 4.0]]])
    quality = np.array([[[0.2, 1.0, 0.8]], [[0.9, 1.0, 0.8]]])
    result, source = best_pixel_composite(data, quality)
    assert source.tolist() == [[1, -1, 0]]
    assert result[0, 0] == 2 and result[0, 2] == 3 and np.isnan(result[0, 1])
    assert summarize(result)["valid_fraction"] == pytest.approx(2 / 3)


def test_soilgrids_units_stock_and_coarse_fraction():
    soc = decode_soilgrids("soc", np.array([200, -32768]))
    density = decode_soilgrids("bdod", np.array([130]))
    coarse = decode_soilgrids("cfvo", np.array([100]))
    assert soc[0] == 20 and np.isnan(soc[1])
    assert density[0] == 1.3 and coarse[0] == 0.1
    # 20 g/kg × 1300 kg/m³ × 0.3 m × 10000 m²/ha /1000/1000 = 78 Mg/ha.
    assert soc_stock(20, 1.3, 30) == pytest.approx(78)
    assert soc_stock(soc[0], density[0], 30, coarse[0]) == pytest.approx(70.2)
    assert "soc_0-5cm_Q0.5.vrt" in soilgrids_vrt("soc", 0, 5, "Q0.5")
    with pytest.raises(ValueError):
        soc_stock(20, 130, 30)


def test_stock_change_sign_and_uncertainty_reproducibility():
    assert stock_change(50, 60, 2, 5)["potential_atmospheric_change_mg_co2"] == pytest.approx(
        -20 * 44 / 12
    )
    a = independent_stock_mc(20, 2, 1.3, 0.1, 30)
    assert a == independent_stock_mc(20, 2, 1.3, 0.1, 30)
    assert a["q05"] < a["median_mg_c_ha"] < a["q95"]


def test_saxton_rawls_loam_reference_and_input_units():
    result = saxton_rawls(0.4, 0.2, 2.5)
    # Table 1 arithmetic: theta33t=.27868, corrected by 1.283*t²-.374*t-.015.
    assert result["theta_33"] == pytest.approx(0.2796101649408, abs=1e-10)
    assert 0 < result["theta_1500"] < result["theta_33"] < result["theta_s"] < 1
    assert 1e-8 < result["ksat_m_s"] < 1e-4
    with pytest.raises(ValueError):
        saxton_rawls(40, 20, 2.5)
    with pytest.raises(ValueError):
        saxton_rawls(0.9, 0.3, 2.5)


def test_planar_terrain_slope_and_compass_aspect():
    y, x = np.mgrid[:5, :5]
    result = derivatives(x * 10.0, 10, 10)
    np.testing.assert_allclose(result["slope_deg"], 45)
    np.testing.assert_allclose(result["aspect_deg"], 270)
    result = derivatives(y * 10.0, 10, 10)
    np.testing.assert_allclose(result["aspect_deg"], 0)
    assert np.isnan(derivatives(np.zeros((5, 5)), 10, 10)["aspect_deg"]).all()


def test_dry_infinite_slope_closed_form_and_pressure_effect():
    dry = infinite_slope(30, 2, 0, 35, 19000, 0)
    assert dry == pytest.approx(np.tan(np.radians(35)) / np.tan(np.radians(30)))
    assert infinite_slope(30, 2, 0, 35, 19000, 1) < dry
