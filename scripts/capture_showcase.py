"""Capture real browser states. Run with a local server and Playwright Chromium installed."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8768")
parser.add_argument("--live", action="store_true", help="Also query public STAC/COG endpoints")
args = parser.parse_args()
output = Path("docs/showcase")
output.mkdir(parents=True, exist_ok=True)
evidence = {"base_url": args.url, "captures": [], "page_errors": [], "console_errors": []}
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True, args=["--no-sandbox", "--enable-unsafe-swiftshader"]
    )
    page = browser.new_page(viewport={"width": 1600, "height": 1100}, device_scale_factor=1)
    page.on("pageerror", lambda error: evidence["page_errors"].append(str(error)))
    page.on(
        "console",
        lambda message: (
            evidence["console_errors"].append(message.text) if message.type == "error" else None
        ),
    )
    page.goto(args.url, wait_until="domcontentloaded")
    page.locator("#run-state").filter(has_text="COMPLETE").wait_for(timeout=45000)
    page.wait_for_timeout(2500)
    assert not page.locator("#map-empty").is_visible(), "WebGL map failed"
    page.screenshot(path=str(output / "01-browser-demo.png"), full_page=True)
    evidence["captures"].append(
        {"path": "01-browser-demo.png", "kind": "working browser; synthetic multispectral fixture"}
    )
    page.locator("#view-3d").click()
    page.wait_for_function(
        "document.querySelector('#view-3d').classList.contains('active')", timeout=90000
    )
    page.wait_for_timeout(7000)
    assert not page.locator("#map-empty").is_visible(), "Terrain rendering failed"
    page.screenshot(path=str(output / "03-browser-terrain.png"), full_page=True)
    evidence["captures"].append(
        {
            "path": "03-browser-terrain.png",
            "kind": "actual Copernicus DEM surface mesh; synthetic analysis texture",
        }
    )
    page.locator("#view-3d").click()
    page.locator("#hydro-open").click()
    page.locator("#hydro-run").click()
    page.locator(".hydro-stat").wait_for(timeout=15000)
    page.screenshot(path=str(output / "04-rust-storm-lab.png"), full_page=True)
    evidence["captures"].append(
        {
            "path": "04-rust-storm-lab.png",
            "kind": "working Rust laboratory; hypothetical material/storm parameters",
        }
    )
    page.keyboard.press("Escape")
    if args.live:
        page.locator("#provider").select_option("earth-search")
        page.wait_for_function(
            "document.querySelector('#collection').value === 'sentinel-2-c1-l2a'", timeout=45000
        )
        page.locator("#search").click()
        page.wait_for_function(
            "!document.querySelector('#search').disabled && document.querySelectorAll('.scene').length > 0",
            timeout=60000,
        )
        page.locator("#analyze").click()
        page.locator("#run-state").filter(has_text="COMPLETE").wait_for(timeout=90000)
        page.locator(".left-panel").evaluate("element => element.scrollTop=0")
        page.wait_for_timeout(500)
        manifest_url = page.locator("#manifest-link").get_attribute("href")
        manifest = page.request.get(args.url + manifest_url).json()
        assert manifest["synthetic"] is False
        assert manifest["statistics"]["valid_pixels"] > 0
        evidence["live"] = {
            "scene": manifest["scene"]["id"],
            "statistics": manifest["statistics"],
            "seconds": manifest["elapsed_seconds"],
        }
        page.screenshot(path=str(output / "05-live-sentinel-analysis.png"), full_page=True)
        evidence["captures"].append(
            {
                "path": "05-live-sentinel-analysis.png",
                "kind": "working browser with actual Sentinel-2 Collection 1 observations",
            }
        )
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(1500)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
        "Mobile horizontal overflow"
    )
    page.screenshot(path=str(output / "06-mobile-workbench.png"), full_page=True)
    evidence["captures"].append(
        {"path": "06-mobile-workbench.png", "kind": "responsive browser layout"}
    )
    browser.close()
(output / "capture-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
print(json.dumps(evidence, indent=2))
if evidence["page_errors"]:
    raise SystemExit("Browser JavaScript errors were recorded")
