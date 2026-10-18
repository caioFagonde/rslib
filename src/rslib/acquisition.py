"""Spend an optical scene budget on dates and AOI coverage, not repeated overlap."""

from __future__ import annotations

import numpy as np

from rslib.models import BBox
from rslib.planner import plan_coverage


def plan_stack_items(
    items: list[dict], bbox: BBox, interval: str, limit: int
) -> tuple[list[dict], dict]:
    """Date strata + per-day sampled footprint set cover.

    Within each requested-date stratum, prefer days whose geometric AOI coverage
    needs fewer scenes, then lower scene cloud cover. Overlapping tiles on one day
    do not crowd out every other date. Unfilled budget uses remaining days farthest
    from those already chosen. Geometry/cloud scores are acquisition heuristics;
    native pixel QA still determines actual usable observations.
    """
    if not 1 <= limit <= 32 or len(items) > 200:
        raise ValueError("Acquisition planning budget exceeded")
    start, end = interval.split("/")
    start = np.datetime64(start.removesuffix("Z"), "us")
    end = np.datetime64(end.removesuffix("Z"), "us")
    if np.isnat(start) or np.isnat(end) or end < start:
        raise ValueError("Invalid acquisition interval")
    duration = max(1, float((end - start) / np.timedelta64(1, "s")))
    grouped = {}
    for item in items:
        timestamp = item.get("properties", {}).get("datetime")
        if not timestamp:
            raise ValueError("Catalog item lacks an acquisition datetime")
        from datetime import UTC, datetime

        date = (
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            .astimezone(UTC)
            .date()
            .isoformat()
        )
        grouped.setdefault(date, []).append(item)
    candidates = []
    for day, group in sorted(grouped.items()):
        plan = plan_coverage(group, bbox, max_scenes=limit, grid_size=64)
        wanted = {(v["collection"], v["id"]) for v in plan["selected"]}
        scenes = [v for v in group if (v.get("collection"), v["id"]) in wanted]
        if not scenes:
            continue
        cloud = float(np.mean([v.get("properties", {}).get("eo:cloud_cover", 100) for v in scenes]))
        seconds = float((np.datetime64(day, "us") - start) / np.timedelta64(1, "s"))
        stratum = min(limit - 1, max(0, int(seconds / duration * limit)))
        candidates.append(
            {
                "day": day,
                "scenes": scenes,
                "coverage": plan["sampled_footprint_coverage"],
                "cloud": cloud,
                "stratum": stratum,
            }
        )
    chosen = []
    remaining = limit
    selected_days = []
    for stratum in range(limit):
        group = sorted(
            (c for c in candidates if c["stratum"] == stratum),
            key=lambda c: (-c["coverage"], len(c["scenes"]), c["cloud"], c["day"]),
        )
        candidate = next((c for c in group if len(c["scenes"]) <= remaining), None)
        if candidate:
            chosen.extend(candidate["scenes"])
            remaining -= len(candidate["scenes"])
            selected_days.append(candidate["day"])
    while remaining:
        group = [
            c for c in candidates if c["day"] not in selected_days and len(c["scenes"]) <= remaining
        ]
        if not group:
            break

        def priority(c):
            date = np.datetime64(c["day"])
            distance = (
                min(
                    abs(float((date - np.datetime64(d)) / np.timedelta64(1, "D")))
                    for d in selected_days
                )
                if selected_days
                else 0
            )
            return (-distance, -c["coverage"], len(c["scenes"]), c["cloud"], c["day"])

        candidate = min(group, key=priority)
        chosen.extend(candidate["scenes"])
        remaining -= len(candidate["scenes"])
        selected_days.append(candidate["day"])
    chosen.sort(key=lambda v: (v["properties"]["datetime"], v["id"]))
    return chosen, {
        "method": "date-stratified sampled-footprint set cover",
        "candidate_items": len(items),
        "candidate_days": len(grouped),
        "selected_items": len(chosen),
        "selected_days": sorted(selected_days),
        "raster_scene_limit": limit,
        "limitation": "Bounded fetched candidates and sampled geometry; no guarantee of AOI cloud-free or complete temporal coverage",
    }
