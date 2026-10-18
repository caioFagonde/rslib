"""Actual Rust results plotted as a standalone scientific figure, not generated artwork."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from rslib.hydro import demo_problem, simulate

directory = Path("docs/showcase")
directory.mkdir(parents=True, exist_ok=True)
problem = demo_problem()
problem["depths_m"] = [round(0.05 * i, 2) for i in range(1, 61)]
result = simulate(problem)
cell = result["cells"][0]
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)
fig, axes = plt.subplots(1, 3, figsize=(14, 5.5), layout="constrained")
colors = ["#415a49", "#7f9d6f", "#bb843f", "#335c82"]
for time_s, color in zip([0, 3600, 21600, 43200], colors, strict=True):
    samples = [s for s in cell["samples"] if s["time_s"] == time_s]
    axes[0].plot(
        [s["head_m"] for s in samples],
        [s["depth_m"] for s in samples],
        label=f"{time_s / 3600:g} h",
        color=color,
    )
    axes[1].plot(
        [s["factor_of_safety"] for s in samples], [s["depth_m"] for s in samples], color=color
    )
for ax in axes[:2]:
    ax.invert_yaxis()
    ax.set_ylabel("Vertical depth (m)")
    ax.grid(alpha=0.2)
axes[0].set_xlabel("Pressure head (m)")
axes[0].set_title("Transient infiltration / finite basal boundary", loc="left", fontsize=11)
axes[0].axvline(0, color="gray", linewidth=0.7, linestyle="--")
axes[0].legend(title="Elapsed time", frameon=False)
axes[1].set_xlabel("Factor of safety (dimensionless)")
axes[1].set_title("Depth-resolved stability", loc="left", fontsize=11)
axes[1].axvline(1, color="#af5141", linestyle="--", linewidth=1, label="FS = 1")
axes[1].set_xlim(0, 5)
times = sorted({s["time_s"] for s in cell["samples"]})
minimum = [min(s["factor_of_safety"] for s in cell["samples"] if s["time_s"] == t) for t in times]
axes[2].plot([t / 3600 for t in times], minimum, marker="o", color="#415a49", markersize=4)
axes[2].axvspan(0, 6, color="#b4c7d8", alpha=0.3, label="18 mm/h rainfall pulse")
axes[2].axhline(1, color="#af5141", linestyle="--", linewidth=1)
axes[2].set_xlabel("Elapsed time (h)")
axes[2].set_ylabel("Minimum FS over sampled depths")
axes[2].set_title("Storm response", loc="left", fontsize=11)
axes[2].legend(frameon=False, loc="upper right", fontsize=8)
axes[2].grid(alpha=0.2)
fig.suptitle(
    "RSLIB HYDRO / native Rust reference-equation implementation",
    x=0.02,
    ha="left",
    fontsize=16,
    fontweight="bold",
)
fig.supxlabel(
    "Hypothetical scenario · 32° slope · water table 1.5 m · basal depth 3 m · wet initial conditions\nModel outputs, not field observations or a validated hazard forecast",
    fontsize=9,
    color="#526252",
)
fig.savefig(directory / "08-rust-physics.svg")
fig.savefig(directory / "08-rust-physics.png", dpi=170)
(directory / "08-rust-physics-input.json").write_text(json.dumps(problem, indent=2) + "\n")
(directory / "08-rust-physics-result.json").write_text(json.dumps(result, indent=2) + "\n")
print(directory / "08-rust-physics.png")
