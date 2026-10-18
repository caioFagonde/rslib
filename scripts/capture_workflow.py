"""Capture current optical inspection; retain 01–15 as historical interfaces."""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8768")
parser.add_argument("--live", action="store_true", help="Also inspect actual satellite inputs")
args = parser.parse_args()
root = Path("docs/showcase")
errors = []


def select_estimate(page, report):
    # A cloud pattern can leave the center cell without any permissible bracket.
    # Select a cell from the actual output; do not assume its support state.
    found = None
    for fy, fx in [(0.5, 0.5), (0.25, 0.25), (0.75, 0.75), (0.25, 0.75), (0.75, 0.25)]:
        row, col = int(report["grid"]["height"] * fy), int(report["grid"]["width"] * fx)
        response = page.request.get(f"{args.url}/api/runs/{report['id']}/pixel?row={row}&col={col}")
        if response.ok and any(s["support"] == 2 for s in response.json()["series"]):
            found = row, col
            break
    assert found, "No estimated cell found in sampled locations"
    row, col = found
    with page.expect_response(lambda r: "/pixel?" in r.url) as response:
        page.locator("#cell-row").fill(str(row))
        page.locator("#cell-col").fill(str(col))
        page.locator("#cell-form button").click()
    assert response.value.status == 200, response.value.text()
    pixel = response.value.json()
    day = next(i for i, sample in enumerate(pixel["series"]) if sample["support"] == 2)
    page.locator("#date-slider").fill(str(day))
    page.locator("#date-slider").dispatch_event("input")
    page.wait_for_function("document.querySelector('#pixel-detail').textContent.includes('Left:')")
    sample = pixel["series"][day]
    assert sample["left_source"]["id"] in page.locator("#pixel-detail").inner_text()
    assert sample["right_source"]["id"] in page.locator("#pixel-detail").inner_text()
    return pixel


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1600, "height": 1200}, device_scale_factor=1)
    page.on("pageerror", lambda e: errors.append(str(e)))
    requests = []
    page.on("request", lambda r: requests.append(r.url) if r.method == "POST" else None)
    page.goto(args.url + "/workflows.html", wait_until="networkidle")
    assert page.locator("#results").is_hidden()
    assert not requests, "Opening an empty workspace must not run a synthetic analysis"
    with page.expect_response(lambda r: r.url.endswith("/api/stack"), timeout=60000) as response:
        page.locator("#example").click()
    report = response.value.json()
    assert response.value.status == 200, report
    page.wait_for_function("document.querySelector('#status').dataset.state==='complete'")
    with page.expect_response(lambda r: r.url.endswith("/api/stack"), timeout=60000) as response:
        page.locator("#run").click()
    report = response.value.json()
    assert response.value.status == 200, report
    assert report["summary"]["cache_hits"] == report["summary"]["observations"] == 8
    page.wait_for_function("document.querySelector('#status').dataset.state==='complete'")
    pixel = select_estimate(page, report)
    # Check mouse selection too, rather than relying only on the coordinate form.
    with page.expect_response(lambda r: "/pixel?" in r.url) as response:
        image = page.locator("#frame").bounding_box()
        page.mouse.click(
            image["x"] + image["width"] * (pixel["col"] + 0.5) / report["grid"]["width"],
            image["y"] + image["height"] * (pixel["row"] + 0.5) / report["grid"]["height"],
        )
    clicked = response.value.json()
    assert clicked["row"] == pixel["row"] and clicked["col"] == pixel["col"]
    with page.expect_download() as downloaded:
        page.locator("#pixel-csv").click()
    csv_path = root / "16-cell-series.csv"
    downloaded.value.save_as(csv_path)
    rows = list(csv.DictReader(io.StringIO(csv_path.read_text())))
    assert len(rows) == len(pixel["series"])
    for row, sample in zip(rows, pixel["series"], strict=True):
        assert row["day"] == sample["day"] and row["synthetic"] == "true"
        assert (
            row["value"] == ""
            if sample["value"] is None
            else abs(float(row["value"]) - sample["value"]) < 1e-12
        )
        if sample["left_source"]:
            assert row["left_id"] == sample["left_source"]["id"]
    with page.expect_download() as downloaded:
        page.locator("#save-recipe").click()
    recipe = json.loads(Path(downloaded.value.path()).read_text())
    recipe["step_days"] = 10
    page.locator("#recipe-file").set_input_files(
        {
            "name": "recipe.json",
            "mimeType": "application/json",
            "buffer": json.dumps(recipe).encode(),
        }
    )
    page.wait_for_function("document.querySelector('#step').value==='10'")
    page.locator("#step").fill("5")
    # Reopening the run restores outputs and inputs without a new preparation.
    requests.clear()
    page.reload(wait_until="networkidle")
    page.wait_for_function("document.querySelector('#status').dataset.state==='complete'")
    assert not requests
    assert page.locator("#step").input_value() == "5"
    pixel = select_estimate(page, report)
    page.evaluate("window.scrollTo(0,0)")
    page.screenshot(path=str(root / "16-cell-inspection.png"), full_page=True)
    page.locator("#support-toggle").click()
    assert page.locator("#support-legend").is_visible()
    page.locator("#support-toggle").click()
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(root / "18-inspection-mobile.png"), full_page=True)
    evidence = {
        "kind": "Browser interaction checks over synthetic inputs; no accuracy benchmark",
        "summary": report["summary"],
        "grid": report["grid"],
        "pixel": pixel,
        "checks": [
            "explicit execution",
            "prepared cache reuse",
            "coordinate and mouse inspection",
            "CSV values and provenance",
            "recipe save/load",
            "reopen without acquisition",
            "support legend",
            "390px layout",
        ],
        "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
    }
    if args.live:
        page.set_viewport_size({"width": 1600, "height": 1200})
        page.locator("#source").select_option("live")
        page.locator("#limit").fill("2")
        page.locator("#step").fill("1")
        with page.expect_response(
            lambda r: r.url.endswith("/api/stack"), timeout=120000
        ) as response:
            page.locator("#run").click()
        live = response.value.json()
        assert response.value.status == 200 and not live["synthetic"], live
        page.wait_for_function("document.querySelector('#status').dataset.state==='complete'")
        assert "missing" in page.locator("#missing-total").inner_text()
        live_pixel = select_estimate(page, live)
        page.evaluate("window.scrollTo(0,0)")
        page.screenshot(path=str(root / "17-live-cell-inspection.png"), full_page=True)
        (root / "17-live-inspection-evidence.json").write_text(
            json.dumps({"report": live, "pixel": live_pixel, "errors": errors}, indent=2) + "\n"
        )
    evidence["errors"] = errors
    (root / "16-inspection-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    # The scene explorer must retain functional controls after its copy changes.
    page.goto(args.url, wait_until="domcontentloaded")
    assert page.locator("h1").inner_text() == "Scene explorer"
    assert page.locator("#provider").is_visible()
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.locator('a[href="/workflows.html"]').is_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    browser.close()
print(json.dumps(evidence["summary"], indent=2))
if errors:
    raise SystemExit(errors)
