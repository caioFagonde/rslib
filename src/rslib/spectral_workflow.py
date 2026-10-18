"""Reproducible observed-scene PCA → VCA → FCLS exports from a verified run."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import rasterio

from rslib import __version__
from rslib.progress import Progress, notify
from rslib.raster import write_cog
from rslib.spectral import fcls, fit_pca, vca
from rslib.spectral_artifacts import previews, write_report
from rslib.spectral_request import SpectralRequest
from rslib.validation import load_verified_run


def analyze_spectra(
    directory: Path,
    output: Path,
    *,
    source_index=0,
    endmembers=3,
    seed=0,
    components=3,
    projection="affine",
    expected_checksums=None,
    progress: Progress | None = None,
    resume=False,
):
    if output.exists():
        raise FileExistsError(
            "Choose a new spectral output directory; existing results are immutable"
        )
    notify(progress, "verifying", "Verifying pinned optical input checksums")
    stack, manifest, digests = load_verified_run(directory)
    if expected_checksums is not None and digests != expected_checksums:
        raise ValueError("Source run differs from the saved spectral input checksums")
    recipe = SpectralRequest(
        run_id=directory.name,
        source_index=source_index,
        endmembers=endmembers,
        components=components,
        projection=projection,
        seed=seed,
        input_checksums=digests,
    ).model_dump()
    if (
        isinstance(source_index, bool)
        or not isinstance(source_index, int)
        or not 0 <= source_index < len(stack.observations)
    ):
        raise ValueError("Choose a source index from this run's observation inventory")
    # A scene-specific fit avoids pooling incompatible date-specific bases and
    # avoids treating temporal interpolations as acquired training spectra.
    source = stack.observations[source_index]
    x = np.moveaxis(stack.values[source_index], 0, -1)
    valid = stack.analysis_mask() & (stack.quality[source_index] > 0)
    notify(progress, "pca", "Fitting covariance PCA to complete observed spectra")
    basis = fit_pca(x, bands=stack.bands, components=components, valid=valid)
    scores = basis.transform(x, bands=stack.bands, valid=valid)
    notify(progress, "vca", "Selecting geometric spectral endmembers")
    vertices = vca(
        x, bands=stack.bands, valid=valid, endmembers=endmembers, seed=seed, projection=projection
    )
    mixture = fcls(
        x,
        vertices.endmembers,
        bands=stack.bands,
        endmember_bands=stack.bands,
        valid=valid,
        progress=progress,
    )
    rows, cols = np.unravel_index(vertices.flat_indices, x.shape[:-1])
    report = {
        "schema_version": "rslib-spectral-analysis/1",
        "id": output.name,
        "run_id": directory.name,
        "recipe": recipe,
        "implementation": {
            "algorithm_contract": "rslib-spectral/1",
            "rslib": __version__,
            "python": platform.python_version(),
            "numpy": np.__version__,
            "rasterio": rasterio.__version__,
            "gdal": rasterio.__gdal_version__,
            "source_sha256": {
                name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                for name in (
                    "spectral.py",
                    "spectral_workflow.py",
                    "spectral_request.py",
                    "spectral_artifacts.py",
                    "raster.py",
                    "validation.py",
                )
            },
        },
        "parent": {
            k: manifest.get(k, [] if k in {"coverage_notes", "limitations", "fields"} else {})
            for k in ("request", "summary", "coverage_notes", "limitations", "fields")
        },
        "input_checksums": digests,
        "synthetic": manifest["synthetic"],
        "source_index": source_index,
        "source": source,
        "grid": stack.grid.metadata(),
        "pca": basis.metadata(),
        "vca": {
            "reference": "https://doi.org/10.1109/TGRS.2005.844293",
            "projection": projection,
            "projection_selection": "Explicit projection branch selected by caller; SNR not estimated",
            "seed": seed,
            "bands": list(stack.bands),
            "projected_endmembers": vertices.endmembers.tolist(),
            "observed_spectra": vertices.observed_spectra.tolist(),
            "cells": [{"row": int(r), "column": int(c)} for r, c in zip(rows, cols, strict=True)],
        },
        "fcls": {
            "method": "Unweighted fully constrained least squares; enumerate simplex faces with convex optimality certificate",
            "units": {
                "abundance": "1",
                "rmse": "reflectance (1)",
                "optimality_gap": "reflectance squared",
            },
            "valid_cells": int(np.isfinite(mixture.rmse).sum()),
            "rmse_median": float(np.nanmedian(mixture.rmse)),
            "rmse_p95": float(np.nanpercentile(mixture.rmse, 95)),
            "maximum_optimality_gap": float(np.nanmax(mixture.optimality_gap)),
            "maximum_sum_to_one_error": float(
                np.max(np.abs(mixture.abundance[np.isfinite(mixture.rmse)].sum(axis=-1) - 1))
            ),
        },
        "limitations": [
            "A scene-specific exploratory fit on QA-valid observed spectra; no independent material labels or held-out accuracy evaluation.",
            "VCA assumes linear mixtures and pure pixels. Extreme spectra may represent illumination, residual atmosphere/cloud or anomalies; endmembers are numbered, not assigned material names.",
            "FCLS fractions describe the selected geometric library. Small reconstruction residual and an optimization certificate do not validate physical material fractions.",
            "Reflectance is the run's prepared common-grid product, including any recorded bandpass transform. Residual misregistration, BRDF and atmospheric differences remain.",
            "PCA covariance eigenvectors describe variance, not noise removal or physical variables. Reuse a declared training basis for cross-date comparisons; no MNF/noise whitening is performed.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / f".{output.name}.staging"
    if staging.exists():
        if not resume:
            raise FileExistsError("An incomplete spectral export exists; resume the saved job")
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        notify(progress, "exporting", "Writing spectral COGs and preview products")
        common_tags = {
            "source_id": source["id"],
            "input_stack_sha256": digests["stack.npz"],
            "units": "1",
        }
        write_cog(
            staging / "pca.tif",
            np.moveaxis(scores, -1, 0),
            stack.grid,
            band_names=tuple(f"PC{i + 1}" for i in range(scores.shape[-1])),
            tags=common_tags,
        )
        write_cog(
            staging / "abundance.tif",
            np.moveaxis(mixture.abundance, -1, 0),
            stack.grid,
            band_names=tuple(f"Endmember {i + 1}" for i in range(endmembers)),
            tags=common_tags,
        )
        write_cog(
            staging / "reconstruction-rmse.tif",
            mixture.rmse,
            stack.grid,
            band_names=("FCLS reflectance RMSE",),
            tags=common_tags,
        )
        report["displays"] = previews(
            staging, x, scores, mixture.abundance, mixture.rmse, stack.bands
        )
        (staging / "request.json").write_text(
            json.dumps({"kind": "spectral", "spectral": recipe}, indent=2, allow_nan=False) + "\n"
        )
        report["outputs"] = [
            {"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(staging.iterdir())
            if p.is_file()
        ]
        write_report(staging, report)
        report["outputs"].append(
            {
                "path": "report.html",
                "sha256": hashlib.sha256((staging / "report.html").read_bytes()).hexdigest(),
            }
        )
        (staging / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        with ZipFile(staging / "bundle.zip", "w", compression=ZIP_DEFLATED) as bundle:
            for artifact in sorted(staging.iterdir()):
                if artifact.name != "bundle.zip":
                    bundle.write(artifact, artifact.name)
        notify(progress, "publishing", "Publishing complete spectral analysis and report")
        # All files become visible together. Do not replace existing nonempty output.
        os.rename(staging, output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return report


def load_spectral_report(directory: Path, *, expected_recipe=None) -> dict:
    report = json.loads((directory / "report.json").read_text())
    if (
        report.get("schema_version") != "rslib-spectral-analysis/1"
        or report.get("id") != directory.name
    ):
        raise ValueError("Invalid published spectral analysis")
    if expected_recipe is not None and report["recipe"] != expected_recipe:
        raise ValueError("Published analysis differs from the saved spectral recipe")
    for artifact in report["outputs"]:
        if Path(artifact["path"]).name != artifact["path"]:
            raise ValueError("Invalid spectral artifact path")
        with (directory / artifact["path"]).open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != artifact["sha256"]:
            raise ValueError("Spectral artifact checksum differs from the published report")
    return report


def inspect_spectra(directory: Path, data: Path, row: int, col: int) -> dict:
    from rasterio.windows import Window

    report = load_spectral_report(directory)
    if not 0 <= row < report["grid"]["height"] or not 0 <= col < report["grid"]["width"]:
        raise ValueError("Cell lies outside the spectral grid")
    stack, _, digests = load_verified_run(data / "runs" / report["run_id"])
    if digests != report["input_checksums"]:
        raise ValueError("Source run differs from the saved spectral input checksums")
    observed = stack.values[report["source_index"], :, row, col].astype(float)
    layers = {}
    for key, filename in [
        ("abundance", "abundance.tif"),
        ("scores", "pca.tif"),
        ("rmse", "reconstruction-rmse.tif"),
    ]:
        with rasterio.open(directory / filename) as dataset:
            layers[key] = dataset.read(window=Window(col, row, 1, 1))[:, 0, 0].astype(float)
    valid = bool(np.isfinite(layers["rmse"]).all())
    reconstructed = (
        layers["abundance"] @ np.asarray(report["vca"]["projected_endmembers"]) if valid else None
    )

    def finite(a):
        return [float(v) if np.isfinite(v) else None for v in a]

    x, y = stack.grid.transform * (col + 0.5, row + 0.5)
    return {
        "analysis_id": report["id"],
        "run_id": report["run_id"],
        "source_id": report["source"]["id"],
        "row": row,
        "col": col,
        "easting_m": x,
        "northing_m": y,
        "valid": valid,
        "bands": list(stack.bands),
        "observed": finite(observed) if valid else [None] * len(observed),
        "reconstructed": finite(reconstructed) if valid else [None] * len(observed),
        "abundance": finite(layers["abundance"]),
        "scores": finite(layers["scores"]),
        "rmse": float(layers["rmse"][0]) if valid else None,
        "units": "1",
    }
