"""Opt-in local browser checks/captures for the static docs and actual reference viewer."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--url", default="http://127.0.0.1:8767")
args = parser.parse_args()
root = Path("docs/showcase")
report = json.loads((root / "42-reference-case-audit.json").read_text())
errors, visited = [], []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1500, "height": 1250}, device_scale_factor=1)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(args.url + "/showcase/reference-cases.html", wait_until="networkidle")
    assert page.locator("#cases tr").count() == len(report["cases"])
    for i, case in enumerate(report["cases"]):
        page.locator("#case").select_option(str(i))
        assert case["partition"] in page.locator("#heading").inner_text()
        for source in [0, len(case["sources"]) - 1]:
            page.locator("#source").select_option(str(source))
            page.wait_for_function(
                "id => [...document.querySelectorAll('.maps img')].every(i => i.complete && i.naturalWidth > 0 && i.src.includes(id))",
                arg=case["id"],
            )
            assert case["sources"][source]["id"] in page.locator("#source-stats").inner_text()
        assert "step_days" in page.locator("#recipe").text_content()
        assert page.locator("#timeline .support").count() == len(case["query_timeline"])
        visited.append(
            {
                "case": case["id"],
                "sources_inspected": [0, len(case["sources"]) - 1],
                "partition": case["partition"],
                "images_loaded": True,
            }
        )
    page.locator("#case").select_option("1")
    page.locator("#source").select_option("2")
    page.wait_for_function(
        "[...document.querySelectorAll('.maps img')].every(i => i.complete && i.naturalWidth > 0)"
    )
    page.screenshot(path=str(root / "43-reference-case-browser.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(root / "43-reference-mobile.png"), full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1080})
    page.goto(args.url, wait_until="networkidle")
    assert page.title().startswith("RSLIB")
    page.locator('a[href*="OPERATIONS/"]').first.click()
    page.wait_for_url("**/OPERATIONS/")
    assert "optical" in page.locator("h1").inner_text().lower()
    search = page.locator(".md-search__input")
    search.fill("native QA")
    page.wait_for_function("document.querySelectorAll('.md-search-result__item').length > 0")
    search_results = page.locator(".md-search-result__item").count()
    page.keyboard.press("Escape")
    page.goto(args.url, wait_until="networkidle")
    page.screenshot(path=str(root / "44-documentation-site.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(root / "44-documentation-mobile.png"), full_page=True)
    browser.close()
assert not errors, errors
(root / "43-reference-browser-evidence.json").write_text(
    json.dumps(
        {
            "type": "Actual static-documentation and reference-viewer browser checks",
            "cases": visited,
            "documentation_navigation": True,
            "search_results": search_results,
            "mobile_horizontal_overflow": False,
            "page_errors": errors,
            "accuracy_validated": False,
        },
        indent=2,
    )
    + "\n"
)
print(
    "Verified case/source navigation, raster loads, documentation navigation/search and mobile layout"
)
