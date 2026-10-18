"""Python bridge to our Rust kernel; no installed TRIGRS or legacy input decks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def kernel_path() -> Path:
    configured = os.environ.get("RSLIB_HYDRO_BIN")
    if configured:
        return Path(configured).resolve()
    found = shutil.which("rslib-hydro")
    if found:
        return Path(found)
    local = Path(__file__).resolve().parents[2] / "target" / "release" / "rslib-hydro"
    if local.is_file():
        return local
    raise RuntimeError(
        "Build the native kernel with cargo build --release -p rslib-hydro, or set RSLIB_HYDRO_BIN"
    )


def simulate(problem: dict, *, timeout: int = 120) -> dict:
    """SI-unit JSON boundary; Rayon owns native parallelism. Fails on unsupported physics."""
    completed = subprocess.run(
        [str(kernel_path())],
        input=json.dumps(problem, allow_nan=False),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env={**os.environ, "RAYON_NUM_THREADS": os.environ.get("RAYON_NUM_THREADS", "4")},
    )
    if completed.returncode:
        raise ValueError(completed.stderr.strip())
    return json.loads(completed.stdout)


def demo_problem() -> dict:
    """Hypothetical one-column storm, not inferred geotechnical properties."""
    return {
        "cells": [
            {
                "slope_deg": 32,
                "water_table_depth_m": 1.5,
                "conductivity_m_s": 1e-5,
                "diffusivity_m2_s": 1e-4,
                "background_flux_m_s": 0,
                "cohesion_pa": 1500,
                "friction_deg": 34,
                "unit_weight_n_m3": 19000,
                "boundary": {"kind": "finite", "depth_m": 3},
            }
        ],
        "rain": [{"start_s": 0, "end_s": 21600, "intensity_m_s": 5e-6}],
        "depths_m": [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3],
        "times_s": [0, 1800, 3600, 7200, 10800, 14400, 21600, 28800, 43200],
    }
