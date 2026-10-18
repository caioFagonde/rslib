"""Exercise actual polygon/project interactions and capture the monitoring workspace."""

import argparse
import csv
import io
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8768")
parser.add_argument("--live", action="store_true")
args = parser.parse_args()
root = Path("docs/showcase")
fields = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "id": "west",
            "properties": {"name": "Western area"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-44.659, -22.409],
                        [-44.651, -22.409],
                        [-44.651, -22.391],
                        [-44.659, -22.391],
                        [-44.659, -22.409],
                    ],
                    [
                        [-44.657, -22.402],
                        [-44.653, -22.402],
                        [-44.653, -22.398],
                        [-44.657, -22.398],
                        [-44.657, -22.402],
                    ],
                ],
            },
        },
        {
            "type": "Feature",
            "id": "east",
            "properties": {"name": "Eastern area"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-44.650, -22.409],
                        [-44.641, -22.409],
                        [-44.641, -22.391],
                        [-44.646, -22.393],
                        [-44.650, -22.391],
                        [-44.650, -22.409],
                    ]
                ],
            },
        },
    ],
}
errors = []


def upload(page):
    page.locator("#areas-file").set_input_files(
        {
            "name": "areas.geojson",
            "mimeType": "application/geo+json",
            "buffer": json.dumps(fields).encode(),
        }
    )
    page.wait_for_function("document.querySelector('#boundary-count').textContent==='2'")


def save(page):
    with page.expect_response(
        lambda r: "/api/projects" in r.url and r.request.method == "POST"
    ) as response:
        page.locator("#save-project").click()
    assert response.value.status == 200, response.value.text()
    project = response.value.json()
    page.wait_for_function("document.querySelector('#project-select').value!==''")
    return project


def wait_run(page, response):
    assert response.status == 202, response.text()
    page.wait_for_function(
        "document.querySelector('#status').dataset.state==='complete'", timeout=240000
    )
    job = page.request.get(args.url + "/api/jobs/" + response.json()["id"]).json()
    return page.request.get(args.url + job["manifest_url"]).json()


def run(page):
    with page.expect_response(
        lambda r: r.url.endswith("/api/jobs") and r.request.method == "POST", timeout=240000
    ) as response:
        page.locator("#workspace-run").click()
    return wait_run(page, response.value)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1600, "height": 1150}, device_scale_factor=1)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(args.url + "/workflows.html", wait_until="networkidle")
    assert page.locator("#results").is_hidden()
    with page.expect_response(lambda r: r.url.endswith("/api/jobs"), timeout=60000) as response:
        page.locator("#example").click()
    wait_run(page, response.value)
    upload(page)
    page.locator("#project-name").fill("Itatiaia optical test")
    # Draw an actual polygon on the WebGL map, save it, then remove it.
    page.locator("#boundary-name").fill("Drawn check")
    page.locator("#draw-area").click()
    box = page.locator("#optical-map").bounding_box()
    for dx, dy in [(-20, -30), (20, -30), (0, 10)]:
        page.mouse.click(box["x"] + box["width"] / 2 + dx, box["y"] + box["height"] / 2 + dy)
    page.locator("#finish-area").click()
    page.wait_for_function("document.querySelector('#boundary-count').textContent==='3'")
    project = save(page)
    assert len(project["recipe"]["fields"]) == 3
    page.get_by_role("button", name="Remove Drawn check").click()
    project = save(page)
    page.locator("#coverage-auto").check()
    page.locator("#coverage-goal").fill("95")
    report = run(page)
    assert report["acquisition"]["stop_reason"] == "candidate_budget_exhausted"
    assert len(report["acquisition"]["steps"]) > 1
    assert (
        len(report["fields"]) == 2
        and len(report["request"]["fields"][0]["geometry"]["coordinates"]) == 2
    )
    # Click a polygon, then switch modes and inspect a cell at the map center.
    page.evaluate("window.scrollTo(0,0)")
    box = page.locator("#optical-map").bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2 - 120, box["y"] + box["height"] / 2 + 60)
    page.wait_for_function("document.querySelector('#series-scope').value==='field:west'")
    page.locator("#map-interaction").select_option("cell")
    with page.expect_response(lambda r: "/pixel?longitude=" in r.url) as response:
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    assert response.value.status == 200
    pixel = response.value.json()
    assert abs(pixel["longitude"] + 44.65) < 0.0005 and abs(pixel["latitude"] + 22.4) < 0.0005
    page.wait_for_function("document.querySelector('#series-scope').value==='pixel'")
    page.locator("#series-scope").select_option("field:west")
    page.locator("#date-slider").fill("4")
    page.locator("#date-slider").dispatch_event("input")
    assert "2026-06-21" in page.locator("#map-date").inner_text()
    with page.expect_download() as download:
        page.locator("#fields-csv").click()
    csv_path = root / "19-area-series.csv"
    download.value.save_as(csv_path)
    rows = list(csv.DictReader(io.StringIO(csv_path.read_text())))
    assert len(rows) == 20
    for row in rows:
        f = next(f for f in report["fields"] if f["id"] == row["field_id"])
        sample = next(s for s in f["timeline"] if s["day"] == row["day"])
        assert float(row["observed_area_m2"]) == sample["observed_area_m2"]
        assert (
            abs(
                sum(
                    float(row[k])
                    for k in ["observed_area_m2", "estimated_area_m2", "missing_area_m2"]
                )
                - f["area_m2"]
            )
            < 1e-6
        )
    # Reopen a project with its run; no catalog/raster preparation should run.
    requests = []
    page.on("request", lambda r: requests.append(r.url) if r.method == "POST" else None)
    page.reload(wait_until="networkidle")
    page.wait_for_function("document.querySelector('#status').dataset.state==='complete'")
    assert not requests
    assert page.locator("#project-select").input_value() == project["id"]
    assert page.locator("#run-history button").count() == 1
    page.locator("#series-scope").select_option("field:west")
    page.locator("#date-slider").fill("4")
    page.locator("#date-slider").dispatch_event("input")
    page.wait_for_load_state("networkidle")
    page.evaluate("window.scrollTo(0,0)")
    page.screenshot(path=str(root / "19-monitoring-project.png"), full_page=True)
    page.locator("#map-layer").select_option("support")
    page.locator("#date-slider").fill("3")
    page.locator("#date-slider").dispatch_event("input")
    page.locator("#area-metric").select_option("supported_mean")
    page.wait_for_load_state("networkidle")
    page.screenshot(path=str(root / "20-area-support.png"), full_page=True)
    page.locator("#area-metric").select_option("fixed_observed_mean")
    assert "Same observed cells" in page.locator("#chart-note").inner_text()
    assert "No values" in page.locator("#chart").inner_text()
    page.locator("#area-metric").select_option("observed_mean")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    page.screenshot(path=str(root / "21-monitoring-mobile.png"), full_page=True)
    evidence = {
        "kind": "Actual project/map/area interactions over synthetic sensor observations",
        "project_id": project["id"],
        "report": report,
        "point": pixel,
        "checks": [
            "GeoJSON polygon holes",
            "polygon drawing and removal",
            "project save and revision",
            "QA-measured acquisition stopping",
            "map polygon selection",
            "map cell inspection",
            "area CSV exact values and area balance",
            "reopen project without acquisition",
            "support layer",
            "fixed observed footprint null handling",
            "390px layout",
        ],
        "errors": errors,
    }
    (root / "19-project-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    if args.live:
        page.set_viewport_size({"width": 1600, "height": 1150})
        page.locator("#new-project").click()
        upload(page)
        # Keep exactly the same bounded AOI for comparison/cache reuse.
        page.locator("#bbox").fill("-44.66,-22.41,-44.64,-22.39")
        page.locator("#project-name").fill("Itatiaia · Sentinel-2 and Landsat")
        page.locator("#step").fill("1")
        page.locator("#limit").fill("4")
        live_project = save(page)
        live = run(page)
        assert not live["synthetic"] and live["summary"]["observations"] >= 4
        page.locator("#map-layer").select_option("index")
        page.locator("#series-scope").select_option("field:west")
        best = max(
            range(len(live["timeline"])),
            key=lambda i: live["fields"][0]["timeline"][i]["observed_fraction"],
        )
        page.locator("#date-slider").fill(str(best))
        page.locator("#date-slider").dispatch_event("input")
        page.wait_for_load_state("networkidle")
        page.evaluate("window.scrollTo(0,0)")
        page.screenshot(path=str(root / "22-live-monitoring-project.png"), full_page=True)
        (root / "22-live-project-evidence.json").write_text(
            json.dumps(
                {
                    "kind": "Actual satellite observations; user-defined analysis polygons, not cadastral boundaries",
                    "project_id": live_project["id"],
                    "report": live,
                    "errors": errors,
                },
                indent=2,
            )
            + "\n"
        )
    browser.close()
print(
    json.dumps(
        {"project": project["id"], "acquisition": report["acquisition"], "errors": errors}, indent=2
    )
)
if errors:
    raise SystemExit(errors)
