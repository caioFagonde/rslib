"""Exercise real sensor-pair diagnostics and the reviewed research browser."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8768")
args = parser.parse_args()
root = Path("docs/showcase")
errors = []
inventory = json.loads((root / "32-research-inventory.json").read_text())["methods"]
run = "1315d34695e8484093cf6a0ec3cdacad"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1660, "height": 1100}, device_scale_factor=1)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(f"{args.url}/workflows.html?run={run}", wait_until="networkidle")
    page.wait_for_function("document.querySelector('#status').dataset.state==='complete'")
    with page.expect_response(lambda r: "/agreement?" in r.url) as response:
        page.locator("#compare-sensors").click()
    assert response.value.status == 200
    agreement = response.value.json()
    expected = json.loads((root / "30-live-sensor-agreement.json").read_text())
    assert agreement == expected
    page.wait_for_selector("#agreement-scatter svg circle")
    assert page.locator("#agreement-result tbody tr").count() == 6
    # Pick a displayed spectral pair cell and verify that it enters the same
    # coordinate inspector used by the map, without a new preparation job.
    with page.expect_response(lambda r: "/pixel?" in r.url) as pixel:
        page.locator("#agreement-scatter circle").first.click(force=True)
    assert pixel.value.status == 200
    inspected = pixel.value.json()
    first = agreement["pairs"][0]["scatter_cells"]
    assert page.locator("#date-slider").input_value() == "18"
    assert inspected["series"][18]["support"] == 1
    assert inspected["series"][18]["left_source"]["id"] == agreement["pairs"][0]["comparison"]["id"]
    assert inspected["row"] == first["rows"][0] and inspected["col"] == first["columns"][0]
    page.locator("#agreement-band").select_option("red")
    assert page.locator("#agreement-scatter svg").get_attribute("aria-label").startswith("red")
    page.locator("#agreement-band").select_option("nir")
    page.locator(".agreement-panel:has(#agreement-result)").screenshot(
        path=str(root / "30-live-sensor-agreement.png")
    )
    # An impossible overlap requirement remains an explicit empty result.
    page.locator("#agreement-cells").fill("1048576")
    page.locator("#compare-sensors").click()
    page.wait_for_function(
        "document.querySelector('#agreement-result').textContent.includes('No pair meets')"
    )
    page.locator("#agreement-cells").fill("100")
    page.locator("#compare-sensors").click()
    page.wait_for_selector("#agreement-scatter svg")
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(350)
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), "Mobile overflow"
    page.locator(".agreement-panel:has(#agreement-result)").screenshot(
        path=str(root / "31-agreement-mobile.png")
    )
    page.set_viewport_size({"width": 1660, "height": 1100})
    page.goto(args.url + "/showcase/research.html", wait_until="networkidle")
    assert page.locator("#rows tr").count() == len(inventory)
    page.locator("#kind").select_option("classical_algorithm")
    classical_count = page.locator("#rows tr").count()
    assert classical_count == sum(m["kind"] == "classical_algorithm" for m in inventory) == 28
    page.get_by_role("button", name="Vertex Component Analysis (VCA)", exact=True).click()
    assert "library browser tui cli observed scene" in page.locator("#detail").inner_text().lower()
    page.locator("#kind").select_option("")
    page.locator("#availability").select_option("checkpoint_metadata_verified")
    verified_count = page.locator("#rows tr").count()
    assert verified_count >= 7
    page.locator("#search").fill("TESSERA")
    assert page.locator("#rows tr").count() == 1
    assert "21.03M" in page.locator("#detail").inner_text()
    page.locator("#search").fill("")
    page.locator("#availability").select_option("")
    page.locator("#domain").select_option("Vegetation biophysics")
    assert page.locator("#rows tr").count() == 2
    page.locator("#domain").select_option("")
    page.get_by_role("button", name="TESSERA v2 students", exact=True).click()
    page.screenshot(path=str(root / "32-research-methods.png"))
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(250)
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    assert not errors, errors
    evidence = {
        "run_id": run,
        "synthetic": False,
        "pair_count": len(agreement["pairs"]),
        "reference": agreement["pairs"][0]["reference"],
        "comparison": agreement["pairs"][0]["comparison"],
        "inspected_scatter_cell": {"row": inspected["row"], "column": inspected["col"]},
        "assertions": {
            "api_matches_checksum_report": agreement == expected,
            "scatter_opens_actual_grid_cell": True,
            "band_selection": True,
            "empty_overlap_result_explicit": True,
            "research_entries": len(inventory),
            "classical_method_entries": classical_count,
            "verified_checkpoint_entries": verified_count,
            "domain_search_filters_work": True,
            "mobile_no_horizontal_overflow": True,
            "page_errors": errors,
        },
    }
    (root / "32-agreement-research-browser-evidence.json").write_text(
        json.dumps(evidence, indent=2) + "\n"
    )
    print(json.dumps(evidence["assertions"], indent=2))
    browser.close()
