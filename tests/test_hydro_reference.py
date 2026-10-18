"""An independent finite-volume diffusion benchmark, rather than a second image-series implementation."""

import numpy as np
import pytest
from scipy.sparse import bmat, csc_matrix, diags
from scipy.sparse.linalg import expm_multiply

from rslib.hydro import demo_problem, kernel_path, simulate


def test_rust_finite_boundary_against_finite_volume_diffusion():
    try:
        kernel_path()
    except RuntimeError:
        pytest.skip("Build the native kernel first")
    problem = demo_problem()
    cell = problem["cells"][0]
    cells = 120
    length = 3.0
    dz = length / cells
    depths = (np.arange(cells) + 0.5) * dz
    problem["depths_m"] = depths.tolist()
    problem["times_s"] = [0, 1800, 3600, 7200]
    problem["rain"] = [{"start_s": 0, "end_s": 3600, "intensity_m_s": 2e-6}]
    result = simulate(problem)["cells"][0]["samples"]
    d1 = cell["diffusivity_m2_s"] / np.cos(np.radians(cell["slope_deg"])) ** 2
    main = np.full(cells, -2.0)
    main[[0, -1]] = -1  # no flux at base; prescribed top flux enters as a source
    laplacian = (
        diags([np.ones(cells - 1), main, np.ones(cells - 1)], [-1, 0, 1], format="csc") * d1 / dz**2
    )
    source = np.zeros(cells)
    source[0] = d1 * (2e-6 / cell["conductivity_m_s"]) / dz

    def augmented(forcing):
        return bmat(
            [
                [laplacian, csc_matrix(forcing[:, None])],
                [csc_matrix((1, cells)), csc_matrix((1, 1))],
            ],
            format="csc",
        )

    vector = np.r_[np.zeros(cells), 1.0]
    beta = np.cos(np.radians(cell["slope_deg"])) ** 2
    previous = 0
    for t in problem["times_s"]:
        if t > previous:
            vector = expm_multiply(
                augmented(source if previous < 3600 else np.zeros(cells)) * (t - previous), vector
            )
        raw = np.array([s["raw_head_m"] for s in result if s["time_s"] == t])
        initial = (depths - cell["water_table_depth_m"]) * beta
        np.testing.assert_allclose(raw - initial, vector[:-1], atol=1.5e-4, rtol=2e-3)
        previous = t
