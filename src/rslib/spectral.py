"""Classical spectral transforms on physical reflectance, with missing data intact.

Spectra use a final band axis. Fit only on declared training observations; a fitted
PCA basis must be reused across dates. VCA identifies geometric extreme spectra,
not named materials. No transform here changes the acquisition QA mask.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np

from rslib.progress import Progress, notify


def _spectra(values, bands, valid=None):
    bands = tuple(bands)
    x = np.asarray(values, dtype="float64")
    if (
        x.ndim < 2
        or not 1 <= len(bands) <= 256
        or x.shape[-1] != len(bands)
        or len(set(bands)) != len(bands)
        or not all(isinstance(b, str) and b for b in bands)
    ):
        raise ValueError("Use unique named bands on the final array axis (1–256 bands)")
    if not 1 <= np.prod(x.shape[:-1]) <= 1_048_576 or x.size > 16_777_216:
        raise ValueError("Tile spectra into at most 1,048,576 cells and 16,777,216 values")
    keep = np.isfinite(x).all(axis=-1)
    if valid is not None:
        valid = np.asarray(valid)
        if valid.dtype != bool or valid.shape != keep.shape:
            raise ValueError("Validity must be a boolean array matching the non-band axes")
        keep &= valid
    return x, bands, keep


def _count(value, low, high, name):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, np.integer))
        or not low <= value <= high
    ):
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")


@dataclass(frozen=True)
class PCABasis:
    bands: tuple[str, ...]
    mean: np.ndarray
    loadings: np.ndarray  # components × bands; orthonormal, covariance PCA
    eigenvalues: np.ndarray
    variance_fraction: np.ndarray
    fit_samples: int

    def transform(self, values, *, bands, valid=None):
        x, names, keep = _spectra(values, bands, valid)
        if names != self.bands:
            raise ValueError("PCA application requires the fitted band names and order")
        scores = np.full((*x.shape[:-1], len(self.loadings)), np.nan)
        scores[keep] = (x[keep] - self.mean) @ self.loadings.T
        return scores

    def metadata(self):
        return {
            "method": "Centered covariance PCA; no per-band standardization or whitening",
            "bands": list(self.bands),
            "mean": self.mean.tolist(),
            "loadings": self.loadings.tolist(),
            "eigenvalues": self.eigenvalues.tolist(),
            "variance_fraction": self.variance_fraction.tolist(),
            "fit_samples": self.fit_samples,
            "units": "1 (reflectance scores); eigenvalues in reflectance squared",
            "sign_convention": "Largest absolute loading in each component is positive",
        }


def fit_pca(values, *, bands, components=3, valid=None) -> PCABasis:
    x, names, keep = _spectra(values, bands, valid)
    _count(components, 1, len(names), "Components")
    training = x[keep]
    if len(training) < max(2, components):
        raise ValueError("Not enough complete valid training spectra for PCA")
    mean = training.mean(axis=0)
    centered = training - mean
    eigenvalues, vectors = np.linalg.eigh(centered.T @ centered / (len(training) - 1))
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = np.maximum(eigenvalues[order], 0)
    if eigenvalues.sum() <= np.finfo(float).eps * max(1, np.square(mean).sum()):
        raise ValueError("PCA training spectra have no resolvable variance")
    loadings = vectors[:, order[:components]].T.copy()
    for row in loadings:
        if row[np.argmax(np.abs(row))] < 0:
            row *= -1
    arrays = (
        mean,
        loadings,
        eigenvalues[:components].copy(),
        eigenvalues[:components] / eigenvalues.sum(),
    )
    for array in arrays:
        array.setflags(write=False)
    return PCABasis(names, *arrays, len(training))


@dataclass(frozen=True)
class VCAResult:
    endmembers: np.ndarray  # projected spectra, endmember × band
    observed_spectra: np.ndarray
    flat_indices: np.ndarray  # indices in the original spatial/sample array
    projection: str
    seed: int
    bands: tuple[str, ...]


def vca(values, *, bands, endmembers=3, valid=None, projection="affine", seed=0) -> VCAResult:
    """Nascimento & Bioucas-Dias (2005), Algorithm 1, both projection branches.

    Caller chooses affine (p−1 centered PCA dimensions, no illumination rescaling)
    or projective (p uncentered dimensions and projective normalization). We do
    not invent an SNR estimate: the paper's branch threshold is 15+10 log10(p) dB.
    Pure pixels and a linear mixture are assumptions, not properties established
    by running this function. Returned endmembers are subspace-projected spectra.
    """
    x, names, keep = _spectra(values, bands, valid)
    _count(endmembers, 2, min(8, len(names)), "Endmembers")
    _count(seed, 0, 2**32 - 1, "Seed")
    if projection not in {"affine", "projective"}:
        raise ValueError("VCA projection must be affine or projective")
    training = x[keep]
    p = endmembers
    if len(training) < p or np.linalg.matrix_rank(training - training.mean(axis=0)) < p - 1:
        raise ValueError("VCA requires at least p affinely independent complete spectra")
    if projection == "affine":
        mean = training.mean(axis=0)
        _, _, vt = np.linalg.svd(training - mean, full_matrices=False)
        basis = vt[: p - 1]
        reduced = (training - mean) @ basis.T
        radius = np.linalg.norm(reduced, axis=1).max()
        projected = np.column_stack((reduced, np.full(len(training), radius)))
        reconstructed = reduced @ basis + mean
    else:
        _, singular, vt = np.linalg.svd(training, full_matrices=False)
        if singular[p - 1] <= singular[0] * 1e-12:
            raise ValueError("Projective VCA requires p independent uncentered dimensions")
        basis = vt[:p]
        reduced = training @ basis.T
        denominators = reduced @ reduced.mean(axis=0)
        if np.min(denominators) <= np.max(np.abs(denominators)) * 1e-12:
            raise ValueError(
                "Projective VCA needs strictly positive, well-resolved projection denominators"
            )
        projected = reduced / denominators[:, None]
        reconstructed = reduced @ basis
    rng = np.random.default_rng(seed)
    selected = []
    auxiliary = np.zeros((p, p))
    auxiliary[-1, 0] = 1
    for i in range(p):
        # Fixed seed and row-major tie choice make selection reproducible on a
        # fixed numeric backend. Retry the improbable near-parallel random draw.
        for _ in range(32):
            direction = rng.normal(size=p)
            direction -= auxiliary @ (np.linalg.pinv(auxiliary) @ direction)
            norm = np.linalg.norm(direction)
            if norm > 1e-10:
                break
        else:
            raise ValueError("VCA could not resolve an independent projection direction")
        index = int(np.argmax(np.abs(projected @ (direction / norm))))
        if index in selected:
            raise ValueError("VCA selected duplicate extremes; reduce the endmember count")
        selected.append(index)
        auxiliary[:, i] = projected[index]
    spectra = reconstructed[selected]
    if np.linalg.matrix_rank(spectra[1:] - spectra[0]) < p - 1:
        raise ValueError("VCA endmembers are affinely dependent")
    return VCAResult(
        spectra,
        training[selected].copy(),
        np.flatnonzero(keep)[selected],
        projection,
        int(seed),
        names,
    )


@dataclass(frozen=True)
class UnmixingResult:
    abundance: np.ndarray
    rmse: np.ndarray  # reflectance, over input bands
    optimality_gap: np.ndarray  # convex first-order gap, reflectance squared


def fcls(
    values, endmembers, *, bands, endmember_bands, valid=None, progress: Progress | None = None
) -> UnmixingResult:
    """Unweighted fully constrained least squares, 2–8 endmembers.

    Enumerates all simplex faces and solves each equality-constrained quadratic
    problem. This finds the nonnegative, sum-to-one least-squares solution, rather
    than normalizing an unconstrained/NNLS solution. Chunking bounds working RAM;
    the exponential face count deliberately limits small endmember libraries.
    """
    x, names, keep = _spectra(values, bands, valid)
    e = np.asarray(endmembers, dtype="float64")
    if tuple(endmember_bands) != names or e.ndim != 2 or e.shape[1] != len(names):
        raise ValueError("Endmember bands must match the spectra's names and order")
    _count(len(e), 2, min(8, len(names) + 1), "Endmembers")
    p = len(e)
    if not np.isfinite(e).all() or np.linalg.matrix_rank(e[1:] - e[0]) < p - 1:
        raise ValueError("Endmembers must be finite and affinely independent")
    abundance = np.full((*x.shape[:-1], p), np.nan)
    rmse = np.full(x.shape[:-1], np.nan)
    gap = np.full(x.shape[:-1], np.nan)
    training = x[keep]
    solved = np.empty((len(training), p))
    residual = np.empty(len(training))
    certificate = np.empty(len(training))
    faces = [face for k in range(1, p + 1) for face in combinations(range(p), k)]
    # Factor each small system once, not for each pixel or chunk.
    systems = []
    for face in faces:
        subset = e[list(face)]
        k = len(face)
        kkt = np.block([[subset @ subset.T, np.ones((k, 1))], [np.ones((1, k)), np.zeros((1, 1))]])
        if np.linalg.cond(kkt) > 1e12:
            raise ValueError("Endmember system is ill-conditioned; use a better-separated library")
        systems.append((face, subset, np.linalg.inv(kkt)))
    for start in range(0, len(training), 4096):
        notify(
            progress,
            "unmixing",
            "Solving constrained spectral fractions",
            completed_cells=start,
            total_cells=len(training),
        )
        chunk = training[start : start + 4096]
        best = np.full(len(chunk), np.inf)
        fractions = np.zeros((len(chunk), p))
        for face, subset, inverse in systems:
            candidate = np.column_stack((chunk @ subset.T, np.ones(len(chunk)))) @ inverse.T
            candidate = candidate[:, :-1]
            feasible = (candidate >= -1e-10).all(axis=1)
            # Only floating-point constraint roundoff is removed here.
            candidate = np.maximum(candidate, 0)
            candidate /= candidate.sum(axis=1, keepdims=True)
            error = np.square(candidate @ subset - chunk).sum(axis=1)
            improve = feasible & (error < best)
            fractions[improve] = 0
            fractions[np.ix_(improve, face)] = candidate[improve]
            best[improve] = error[improve]
        difference = fractions @ e - chunk
        gradient = difference @ e.T
        dual_gap = (fractions * gradient).sum(axis=1) - gradient.min(axis=1)
        if not np.isfinite(best).all() or np.max(dual_gap, initial=0) > 1e-8 * max(
            1, np.square(chunk).max(initial=0)
        ):
            raise ValueError("FCLS did not satisfy the convex optimality certificate")
        solved[start : start + len(chunk)] = fractions
        residual[start : start + len(chunk)] = np.sqrt(best / len(names))
        certificate[start : start + len(chunk)] = np.maximum(dual_gap, 0)
    abundance[keep], rmse[keep], gap[keep] = solved, residual, certificate
    notify(
        progress,
        "unmixing",
        "Constrained fractions complete",
        completed_cells=len(training),
        total_cells=len(training),
    )
    return UnmixingResult(abundance, rmse, gap)


OLI_TOA_BANDS = ("blue", "green", "red", "nir", "swir16", "swir22")
_BAIG_2014 = np.array(
    [
        [0.3029, 0.2786, 0.4733, 0.5599, 0.5080, 0.1872],
        [-0.2941, -0.2430, -0.5424, 0.7276, 0.0713, -0.1608],
        [0.1511, 0.1973, 0.3283, 0.3407, -0.7117, -0.4559],
    ]
)


def tasseled_cap(values, *, bands, sensor, radiometry, valid=None):
    """Baig et al. 2014 OLI TOA brightness/greenness/wetness (dimensionless).

    Coefficients: DOI 10.1080/2150704X.2014.915434, independently tabulated in
    NASA DEVELOP 20220005937, Table B1. This profile does not accept surface
    reflectance, MSI, OLI-2 or other legacy Landsat sensors.
    """
    if sensor != "landsat-8-oli" or radiometry != "toa_reflectance":
        raise ValueError("Baig 2014 profile requires Landsat-8 OLI TOA reflectance, not SR")
    x, names, keep = _spectra(values, bands, valid)
    if names != OLI_TOA_BANDS:
        raise ValueError(
            "Tasseled cap requires blue, green, red, nir, swir16, swir22 in that order"
        )
    result = np.full((*x.shape[:-1], 3), np.nan)
    result[keep] = x[keep] @ _BAIG_2014.T
    return result


def bcy_sentinel_candidates(green, red, swir16, *, radiometry, swir_threshold):
    """Sentinel Hub's S2 BCY adaptation; 0 unknown, 1 not detected, 2 cloud candidate.

    Original BCY/MSScvm (Braaten, Cohen, Yang 2015) targets Landsat MSS and has
    shadow processing. This threshold adaptation is not that complete algorithm.
    The published evalscript uses SWIR >0.1; its prose proposes >0.2. Require the
    caller to select this threshold. No shadows, cirrus or clear-sky guarantee.
    Source: custom-scripts.sentinel-hub.com/.../sentinel-2/cby_cloud_detection/
    """
    if radiometry != "sentinel-2-l1c-toa_reflectance":
        raise ValueError("BCY adaptation requires native Sentinel-2 L1C TOA reflectance")
    if not np.isfinite(swir_threshold) or not 0 <= swir_threshold <= 1:
        raise ValueError("Choose an explicit SWIR reflectance threshold between 0 and 1")
    green, red, swir = (np.asarray(a, dtype="float64") for a in (green, red, swir16))
    if green.shape != red.shape or green.shape != swir.shape or green.size > 1_048_576:
        raise ValueError("BCY bands must have equal shapes and at most 1,048,576 cells")
    valid = np.isfinite(green) & np.isfinite(red) & np.isfinite(swir) & (green + red > 0)
    candidate = (swir > swir_threshold) & (((green > 0.175) & (green > red)) | (green > 0.39))
    return np.where(valid, np.where(candidate, 2, 1), 0).astype("uint8")
