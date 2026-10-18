"""Opt-in public endpoint check, kept out of offline tests."""

import asyncio
import json
from pathlib import Path

from rslib.models import AnalysisRequest, BBox, Search
from rslib.pipeline import analyze_scene
from rslib.stac import client_for

bbox = BBox(west=-44.75, south=-22.5, east=-44.55, north=-22.3)
query = Search(bbox=bbox, datetime="2026-06-01/2026-08-01", max_items=3, max_cloud=20, max_pages=5)
catalog = asyncio.run(client_for("earth-search").search(query))
if not catalog["features"]:
    raise SystemExit("No matching live scenes; adjust the date interval. No synthetic fallback.")
item = catalog["features"][0]
request = AnalysisRequest(
    provider="earth-search", collection=item["collection"], item_id=item["id"], bbox=bbox, size=128
)
result = analyze_scene(item, request, Path("data/live-smoke/runs"))
print(json.dumps({"catalog": catalog["rslib"], "scene": item["id"], "analysis": result}, indent=2))
