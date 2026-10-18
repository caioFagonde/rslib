"""Render actual baseline computations over an explicitly synthetic temporal cube."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from rslib.compositing import composite
from rslib.indices import spectral_index
from rslib.timeseries import interpolate_gaps

root = Path("docs/showcase")
days = np.array([0, 5, 10, 20, 25, 40, 45, 55, 65])
times = np.datetime64("2026-06-01") + days.astype("timedelta64[D]")
y, x = np.mgrid[:128, :128]
cube, masks = [], []
for i, day in enumerate(days):
    growth = 0.16 + 0.08 * np.sin(day / 65 * np.pi)
    texture = 0.03 * np.sin(x / 8) + 0.02 * np.cos(y / 9)
    red = 0.12 + 0.015 * np.sin(x / 11) + 0.01 * np.cos(y / 13)
    nir = 0.3 + growth + texture
    # Known synthetic disturbance introduced after day 35. No trained model used.
    disturbed = (x > 60) & (x < 100) & (y > 45) & (y < 95) & (day > 35)
    nir = np.where(disturbed, 0.18, nir)
    clear = ((x - (15 + i * 12)) ** 2 + (y - 70) ** 2) > 28**2
    clear &= ~(((x - 100) ** 2 + (y - (15 + i * 8)) ** 2) < 18**2)
    masks.append(clear)
    cube.append(np.stack([red, 0.13 + texture, 0.07 + texture / 2, nir]))
cube, clear = np.array(cube, dtype="float32"), np.array(masks)
quality = np.broadcast_to(days[:, None, None], clear.shape).astype("float32")
quality_result = composite(cube, clear, quality=quality)
medoid_result = composite(cube, clear, method="medoid")
ndvi = spectral_index("ndvi", {"red": cube[:, 0], "nir": cube[:, 3]})
masked = np.where(clear, ndvi, np.nan)
series = interpolate_gaps(masked, times, max_gap_days=40)

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "text.color": "#dcebd5",
        "axes.labelcolor": "#a6c29b",
        "axes.titlecolor": "#dcebd5",
        "xtick.color": "#9eb797",
        "ytick.color": "#9eb797",
    }
)
fig = plt.figure(figsize=(16, 10), facecolor="#102018")
grid = fig.add_gridspec(
    2, 3, left=0.045, right=0.96, bottom=0.12, top=0.83, hspace=0.32, wspace=0.2
)
panels = [
    (masked[4], "Single observation / QA-masked NDVI", "YlGn", (-0.1, 0.85)),
    (
        spectral_index("ndvi", {"red": quality_result.values[0], "nir": quality_result.values[3]}),
        "Latest-clear whole-spectrum composite",
        "YlGn",
        (-0.1, 0.85),
    ),
    (
        spectral_index("ndvi", {"red": medoid_result.values[0], "nir": medoid_result.values[3]}),
        "Observed spectral medoid / L1 distance",
        "YlGn",
        (-0.1, 0.85),
    ),
    (quality_result.source_index, "Composite source date / input index", "viridis", (0, 8)),
    (quality_result.observation_count, "Eligible complete spectra / count", "cividis", (0, 9)),
]
for n, (image, title, cmap, limits) in enumerate(panels):
    ax = fig.add_subplot(grid[n // 3, n % 3])
    ax.set_facecolor("#213829")
    im = ax.imshow(image, cmap=cmap, vmin=limits[0], vmax=limits[1])
    ax.set_title(title, fontsize=11)
    ax.set_axis_off()
    fig.colorbar(im, ax=ax, shrink=0.7, pad=0.02)
ax = fig.add_subplot(grid[1, 2])
ax.set_facecolor("#172a1e")
row, col = 92, 76
ax.plot(days, ndvi[:, row, col], color="#7b9980", ls="--", label="Known synthetic truth")
ax.plot(
    days, series.values[:, row, col], color="#e5c58c", lw=1.4, label="Gap-limited linear baseline"
)
ax.scatter(days, masked[:, row, col], color="#cbefad", s=40, zorder=3, label="Clear observations")
ax.set_title("Actual irregular acquisition spacing", fontsize=11)
ax.set_xlabel("Days since synthetic start")
ax.set_ylabel("NDVI")
ax.legend(fontsize=7, facecolor="#172a1e", labelcolor="#c8dcbe", edgecolor="#3e5941")
for spine in ax.spines.values():
    spine.set_color("#3e5941")
fig.suptitle(
    "RSLIB / OBSERVATION-PRESERVING TEMPORAL ANALYSIS", x=0.045, y=0.97, ha="left", fontsize=21
)
fig.text(
    0.045,
    0.90,
    "COMPUTED BASELINES · SYNTHETIC MULTISPECTRAL SEQUENCE · NO SATELLITE OBSERVATIONS",
    fontsize=12,
    color="#e7c595",
)
fig.text(
    0.045,
    0.07,
    "Every composite pixel keeps one complete measured spectrum and its source index. Missing or unbracketed dates remain unsupported.",
    fontsize=11,
    color="#b3cda7",
)
fig.text(
    0.045,
    0.03,
    "The synthetic disturbance shows a limitation: medoids can select older land cover, and interpolation can smear abrupt changes. Neither is a learned cloud-removal model.",
    fontsize=10,
    color="#e7c595",
)
fig.savefig(root / "10-temporal-baselines.png", dpi=150, facecolor=fig.get_facecolor())
(root / "10-temporal-evidence.json").write_text(
    json.dumps(
        {
            "kind": "actual computations over synthetic data",
            "seed": "deterministic analytical fields",
            "shape_tcyx": list(cube.shape),
            "times": [str(d) for d in times],
            "algorithms": [
                "latest-clear quality composite",
                "L1 spectral medoid",
                "gap-limited linear interpolation",
            ],
            "max_gap_days": 40,
            "composite_supported_fraction": float((quality_result.source_index >= 0).mean()),
            "input_clear_fraction": float(clear.mean()),
            "interpolated_samples": int((series.provenance == 2).sum()),
            "limitations": "Synthetic benchmark only. No cloud-removal weights or calibrated uncertainty; abrupt changes are not recovered reliably.",
        },
        indent=2,
    )
    + "\n"
)
