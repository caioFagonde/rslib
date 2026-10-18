from __future__ import annotations

import hashlib
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import numpy as np
import rasterio
from jinja2 import Environment, select_autoescape
from PIL import Image

from rslib import __version__
from rslib.cache import canonical_hash
from rslib.indices import INDEX_BANDS, landsat_clear, sentinel_clear, spectral_index, summarize
from rslib.models import AnalysisRequest
from rslib.raster import (
    Grid,
    optical_calibration,
    read_band,
    resolve_asset,
    sign_planetary_asset,
    write_cog,
)


def sanitized_href(href: str) -> str:
    p = urlsplit(href)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def colorize(values: np.ndarray, index: str = "ndvi") -> np.ndarray:
    if index == "rgb":
        rgb = np.moveaxis(np.clip(values / 0.35, 0, 1) ** (1 / 2.2), 0, -1)
        valid = np.isfinite(rgb).all(axis=-1)
        rgba = np.dstack([np.nan_to_num(rgb) * 255, valid * 255])
        return rgba.astype("uint8")
    stops = np.array(
        [[93, 58, 45], [197, 155, 88], [235, 224, 163], [118, 179, 121], [24, 107, 77], [8, 57, 47]]
    )
    valid = np.isfinite(values)
    normalized = np.clip((values + 1) / 2, 0, 1) * (len(stops) - 1)
    channels = [
        np.interp(np.nan_to_num(normalized), np.arange(len(stops)), stops[:, c]) for c in range(3)
    ]
    return np.dstack([*channels, valid * 255]).astype("uint8")


def analyze_scene(item: dict, request: AnalysisRequest, output_root: Path) -> dict:
    """Bounded preview analysis, shared by API, CLI and TUI. No full-scene downloads."""
    started = time.monotonic()
    grid = Grid.preview(request.bbox, request.size)
    required = INDEX_BANDS[request.index]
    sentinel = request.provider == "demo" or item.get("collection", "").startswith("sentinel-2")
    landsat = "landsat" in item.get("collection", "")
    if not sentinel and not landsat:
        raise ValueError(
            "Analysis currently supports Sentinel-2 and Landsat optical scenes; use the raster/terrain library for DEMs"
        )
    qa_names = ["scl"] if sentinel else ["qa_pixel", "qa_radsat"]
    sources = {name: resolve_asset(item, name) for name in (*required, *qa_names)}
    provenance = []

    def load(pair):
        name, asset = pair
        categorical = name in qa_names
        scale, offset, policy = (
            (1, 0, "Categorical QA; no reflectance conversion")
            if categorical
            else optical_calibration(item, asset, request.provider)
        )
        href = asset["href"]
        if request.provider == "planetary-computer":
            href = sign_planetary_asset(href)
        data = read_band(
            href,
            grid,
            categorical=categorical,
            zero_is_valid=name == "qa_radsat",
            scale=scale,
            offset=offset,
        )
        return (
            name,
            data,
            {
                "band": name,
                "asset": asset["key"],
                "href": sanitized_href(asset["href"]),
                "calibration": {
                    "scale": scale,
                    "offset": offset,
                    "policy": policy,
                },
            },
        )

    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="rslib-band") as executor:
        loaded = list(executor.map(load, sources.items()))
    bands = {}
    for name, data, source in loaded:
        bands[name] = data
        provenance.append(source)
    if sentinel:
        clear = sentinel_clear(bands["scl"], request.cloud_buffer)
        mask_method = "Sentinel SCL classes 4/5/6; nearest sample; buffer in output pixels"
    else:
        qa, sat = bands["qa_pixel"], bands["qa_radsat"]
        clear = (
            landsat_clear(np.nan_to_num(qa), np.nan_to_num(sat))
            & np.isfinite(qa)
            & np.isfinite(sat)
        )
        if request.cloud_buffer:
            from scipy.ndimage import binary_dilation

            clear = ~binary_dilation(~clear, iterations=request.cloud_buffer)
        mask_method = "Landsat C2 QA_PIXEL bits 0–5 + QA_RADSAT; buffer in output pixels"
    clear &= np.logical_and.reduce([np.isfinite(bands[name]) for name in required])
    if request.index == "rgb":
        values = np.stack([np.where(clear, bands[name], np.nan) for name in required])
        stats = {name: summarize(values[i]) for i, name in enumerate(required)}
    else:
        values = np.where(clear, spectral_index(request.index, bands), np.nan)
        stats = summarize(values)
    run_id = uuid.uuid4().hex
    directory = output_root / run_id
    directory.mkdir(parents=True)
    Image.fromarray(colorize(values, request.index)).save(directory / "preview.png")
    write_cog(directory / "analysis.tif", values, grid)
    elapsed = time.monotonic() - started
    report = {
        "schema_version": "rslib-run/1",
        "id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "synthetic": request.provider == "demo",
        "request": request.model_dump(),
        "scene": {
            "id": item["id"],
            "collection": item.get("collection"),
            "properties": item.get("properties", {}),
            "license": item.get("license", "See collection license"),
            "links": [
                {"rel": link.get("rel"), "href": sanitized_href(link["href"])}
                for link in item.get("links", [])
                if "href" in link
            ],
        },
        "inputs": provenance,
        "grid": grid.metadata(),
        "mask": {"method": mask_method, "clear_fraction": float(clear.mean())},
        "statistics": stats,
        "elapsed_seconds": round(elapsed, 3),
        "reproducibility": {
            "rslib": __version__,
            "numpy": np.__version__,
            "rasterio": rasterio.__version__,
            "gdal": rasterio.__gdal_version__,
            "input_fingerprint": canonical_hash([request.model_dump(), item["id"], provenance]),
        },
        "sampling": "Bounded nearest-neighbor WGS84 preview grid. Statistics describe sampled pixels; not native-resolution zonal statistics or area-weighted estimates. Small clouds may be missed by downsampling.",
        "outputs": [
            {
                "path": filename,
                "sha256": hashlib.sha256((directory / filename).read_bytes()).hexdigest(),
            }
            for filename in ("preview.png", "analysis.tif")
        ],
        "preview_url": f"/api/runs/{run_id}/preview.png",
        "cog_url": f"/api/runs/{run_id}/analysis.tif",
        "report_url": f"/api/runs/{run_id}/report.html",
        "manifest_url": f"/api/runs/{run_id}/manifest.json",
    }
    (directory / "report.html").write_text(render_report(report))
    (directory / "manifest.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def render_report(report: dict) -> str:
    env = Environment(autoescape=select_autoescape(default=True))
    return env.from_string("""<!doctype html><html lang="en"><meta charset="utf-8"><title>RSLIB analysis report</title>
    <style>body{max-width:900px;margin:3rem auto;padding:1rem;font:16px system-ui;color:#17382e}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef3ef;padding:1rem}img{max-width:100%;background:#dde4de}h1{font-size:2.4rem}@media print{body{margin:0}pre{font-size:9px}}</style>
    <h1>RSLIB / {{ r.request.index|upper }}</h1><p>{{ r.scene.id }} · {{ r.created_at }}</p>
    {% if r.synthetic %}<strong>SYNTHETIC DEMONSTRATION — not satellite observations</strong>{% endif %}
    <p>{{ r.sampling }}</p><img src="preview.png" alt="Cloud-masked analysis raster">
    <h2>Statistics</h2><pre>{{ stats }}</pre><h2>Provenance and processing</h2><pre>{{ manifest }}</pre>
    <p>Print this page to PDF. Machine-readable provenance: <a href="manifest.json">manifest.json</a>; georeferenced output: <a href="analysis.tif">COG</a>.</p></html>""").render(
        r=report,
        stats=json.dumps(report["statistics"], indent=2),
        manifest=json.dumps(report, indent=2),
    )
