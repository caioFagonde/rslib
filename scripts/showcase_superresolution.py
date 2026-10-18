"""Opt-in real Sentinel-2 + consumer-hardware SR benchmark and comparison figure.

Requires the sr extra and matplotlib. Weights are an explicit ~3.4 MB download.
No high-resolution ground truth is provided: this measures resources and
low-resolution consistency, NOT accuracy at a claimed 2.5 m spatial resolution.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
from rasterio.transform import from_origin
from rasterio.warp import transform
from scipy.ndimage import zoom

from rslib.indices import sentinel_clear
from rslib.raster import Grid, optical_calibration, read_band, resolve_asset, write_cog
from rslib.stac import client_for
from rslib.superresolution import (
    fetch_weights,
    load_sen2sr_lite,
    model_card,
    superresolve_rgbn,
    upscale_grid,
)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--device", choices=["cpu", "cuda"], default="cuda" if torch.cuda.is_available() else "cpu"
)
parser.add_argument("--repeats", type=int, default=3)
parser.add_argument("--scene", default="S2B_T23KNR_20260729T131748_L2A")
args = parser.parse_args()
if not 1 <= args.repeats <= 10:
    parser.error("repeats must be 1 to 10")
output = Path("data/superresolution")
output.mkdir(parents=True, exist_ok=True)
gallery = Path("docs/showcase")
gallery.mkdir(parents=True, exist_ok=True)
item_path = output / f"{args.scene}.json"
if item_path.exists():
    item = json.loads(item_path.read_text())
else:
    item = asyncio.run(client_for("earth-search").item("sentinel-2-c1-l2a", args.scene))
    item_path.write_text(json.dumps(item, indent=2) + "\n")
cx, cy = transform("EPSG:4326", "EPSG:32723", [-44.65], [-22.40])
grid = Grid("EPSG:32723", from_origin(cx[0] - 640, cy[0] + 640, 10, 10), 128, 128)
cache = output / f"{args.scene}-rgbn.npy"
if cache.exists():
    image = np.load(cache, allow_pickle=False)
else:

    def read(name):
        asset = resolve_asset(item, name)
        scale, offset, _ = optical_calibration(item, asset, "earth-search")
        return read_band(asset["href"], grid, scale=scale, offset=offset)

    with ThreadPoolExecutor(3) as executor:
        image = np.stack(list(executor.map(read, ["red", "green", "blue", "nir"])))
    clear = sentinel_clear(read_band(resolve_asset(item, "scl")["href"], grid, categorical=True), 1)
    image[:, ~clear] = np.nan
    if np.isfinite(image).all(axis=0).mean() < 0.95:
        raise ValueError("Showcase patch is not sufficiently clear; choose another actual scene")
    np.save(cache, image, allow_pickle=False)
weights_dir = Path("data/models/sen2sr-lite-rgbn-x4")
fetch_weights(weights_dir)
model = load_sen2sr_lite(weights_dir, args.device)
precision = "float16" if args.device == "cuda" else "float32"


def synchronize():
    if args.device == "cuda":
        torch.cuda.synchronize()


superresolve_rgbn(model, image, device=args.device, precision=precision)  # warm-up
synchronize()
if args.device == "cuda":
    torch.cuda.reset_peak_memory_stats()
timings = []
for _ in range(args.repeats):
    synchronize()
    start = time.perf_counter()
    result = superresolve_rgbn(model, image, device=args.device, precision=precision)
    synchronize()
    timings.append(time.perf_counter() - start)
write_cog(output / "native-rgbn.tif", image, grid)
write_cog(output / "sen2sr-lite-rgbn.tif", result, upscale_grid(grid))
reduced = result.reshape(4, 128, 4, 128, 4).mean(axis=(2, 4))
rmse = np.sqrt(np.nanmean((reduced - image) ** 2, axis=(1, 2)))
evidence = {
    "kind": "Actual pretrained inference on real satellite data; no HR ground truth",
    "scene": args.scene,
    "provider": "earth-search",
    "collection": item["collection"],
    "center_lon_lat": [-44.65, -22.40],
    "input_grid": grid.metadata(),
    "output_grid": upscale_grid(grid).metadata(),
    "clear_fraction": float(np.isfinite(image).all(axis=0).mean()),
    "model": model_card(),
    "device": args.device,
    "precision": precision,
    "fft_precision": "float32",
    "tile_size": 128,
    "halo": 16,
    "batch_size": 1,
    "input_shape": list(image.shape),
    "output_shape": list(result.shape),
    "seconds_warm_repeats": timings,
    "seconds_warm_median": float(np.median(timings)),
    "timing_scope": "inference, halo assembly and device transfers; excludes acquisition, loading and export",
    "torch": torch.__version__,
    "python": platform.python_version(),
    "gpu": torch.cuda.get_device_name() if args.device == "cuda" else None,
    "gpu_total_mib": torch.cuda.get_device_properties(0).total_memory / 2**20
    if args.device == "cuda"
    else None,
    "peak_torch_allocated_mib": torch.cuda.max_memory_allocated() / 2**20
    if args.device == "cuda"
    else None,
    "peak_torch_reserved_mib": torch.cuda.max_memory_reserved() / 2**20
    if args.device == "cuda"
    else None,
    "memory_scope": "PyTorch allocator only; excludes driver, CUDA context and other processes",
    "box_average_back_to_native_rmse_rgbn": rmse.tolist(),
    "metric_scope": "Diagnostic box-average consistency, not the sensor PSF and not HR accuracy",
    "artifacts": [
        {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in [output / "native-rgbn.tif", output / "sen2sr-lite-rgbn.tif"]
    ],
}
(output / "manifest.json").write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n")
(gallery / "09-superresolution-evidence.json").write_text(
    json.dumps(evidence, indent=2, allow_nan=False) + "\n"
)
plt.rcParams.update(
    {"font.family": "DejaVu Sans", "text.color": "#deebd7", "axes.titlecolor": "#deebd7"}
)
fig, axes = plt.subplots(1, 3, figsize=(16, 7), facecolor="#102018")
# One fixed reflectance stretch and one AOI for all views; no individual enhancement.
rgb = image[:3].transpose(1, 2, 0)
bicubic = zoom(rgb, (4, 4, 1), order=3)
views = [rgb, bicubic, result[:3].transpose(1, 2, 0)]
titles = [
    "Native Sentinel-2 / 10 m samples",
    "Bicubic / 2.5 m display grid",
    "SEN2SRLite / 2.5 m model grid",
]
for ax, view, title in zip(axes, views, titles, strict=True):
    ax.imshow(np.clip(view * 3, 0, 1), interpolation="nearest")
    ax.set_title(title, fontsize=13, pad=15)
    ax.set_axis_off()
fig.suptitle(
    "RSLIB / SUPER-RESOLUTION ON CONSUMER HARDWARE", x=0.04, ha="left", fontsize=20, y=0.97
)
fig.text(
    0.04,
    0.89,
    f"Actual Sentinel-2 L2A · Itatiaia, Brazil · {item['properties']['datetime'][:10]} · identical RGB stretch",
    color="#abc49f",
    fontsize=12,
)
fig.text(
    0.04,
    0.10,
    f"{evidence['gpu'] or 'CPU'}  |  batch 1 · 128 px tiles + halo · {precision} convolution / fp32 FFT",
    fontsize=12,
    color="#c6e8ac",
)
memory = evidence["peak_torch_allocated_mib"]
fig.text(
    0.04,
    0.06,
    f"Measured warm inference: {np.median(timings):.3f} s for 128² → 512² RGBN"
    + (
        f" · peak Torch allocation {memory:.1f} MiB (excludes CUDA context)"
        if memory is not None
        else ""
    ),
    fontsize=11,
    color="#abc49f",
)
fig.text(
    0.04,
    0.02,
    "Model-derived detail. No high-resolution ground truth here; a finer pixel grid does not establish finer measured resolution.",
    fontsize=10,
    color="#e7c595",
)
fig.subplots_adjust(left=0.04, right=0.98, bottom=0.16, top=0.83, wspace=0.05)
fig.savefig(gallery / "09-superresolution.png", dpi=160, facecolor=fig.get_facecolor())
print(json.dumps(evidence, indent=2))
