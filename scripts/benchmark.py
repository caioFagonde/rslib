"""Reproducible local benchmarks. Measures observed performance; no invented baselines."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from pathlib import Path

from rslib.demo import create_demo
from rslib.hydro import demo_problem, simulate
from rslib.models import AnalysisRequest
from rslib.pipeline import analyze_scene

parser = argparse.ArgumentParser()
parser.add_argument("--size", type=int, default=512)
parser.add_argument("--repeats", type=int, default=3)
parser.add_argument("--output", type=Path, default=Path("data/benchmark"))
args = parser.parse_args()
if not 1 <= args.repeats <= 30:
    parser.error("repeats must be 1–30")
fixture = create_demo(args.output / "demo")
times = []
for _ in range(args.repeats):
    t = time.perf_counter()
    analyze_scene(fixture["features"][0], AnalysisRequest(size=args.size), args.output / "runs")
    times.append(time.perf_counter() - t)
problem = demo_problem()
problem["cells"] *= 1000
t = time.perf_counter()
result = simulate(problem)
hydro_seconds = time.perf_counter() - t
report = {
    "machine": platform.platform(),
    "python": platform.python_version(),
    "preview_size": args.size,
    "repeats": args.repeats,
    "analysis_seconds": times,
    "median_seconds": statistics.median(times),
    "hydro_cells": len(result["cells"]),
    "hydro_seconds_including_json_ipc": hydro_seconds,
    "notes": "Warm local synthetic inputs; includes output serialization and artifact writes. Not remote acquisition latency or a comparison with another library.",
}
(args.output / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
