"""Inspect the actual-data spectral figure in Chromium and retain acceptance evidence."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8768")
args = parser.parse_args()
root = Path("docs/showcase")
report = json.loads((root / "35-live-spectral-report.json").read_text())
width, height = report["grid"]["width"], report["grid"]["height"]
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1520, "height": 1270}, device_scale_factor=1)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(args.url + "/showcase/spectral.html", wait_until="networkidle")
    assert page.locator(".map img").count() == 4
    assert page.evaluate(
        f"[...document.querySelectorAll('.map img')].every(i=>i.complete && i.naturalWidth==={width} && i.naturalHeight==={height})"
    )
    # Inspect a recorded VCA source cell, then verify the displayed source
    # spectrum against the report's recorded observed spectrum.
    row, col = (report["vca"]["cells"][0][name] for name in ("row", "column"))
    box = page.locator("#abundance").bounding_box()
    page.mouse.click(
        box["x"] + (col + 0.5) / width * box["width"],
        box["y"] + (row + 0.5) / height * box["height"],
    )
    assert page.locator("body").get_attribute("data-row") == str(row)
    assert page.locator("body").get_attribute("data-col") == str(col)
    assert page.locator("#values tr").count() == 6
    for k, tr in enumerate(page.locator("#values tr").all()):
        observed = float(tr.locator("td").nth(1).inner_text())
        assert abs(observed - report["vca"]["observed_spectra"][0][k]) < 0.000006
    # A real missing/outside cell remains missing, not a fitted zero fraction.
    missing = page.evaluate("D.valid.findIndex(v=>!v)")
    assert missing >= 0
    page.evaluate(f"pick({missing // width},{missing % width})")
    assert "Excluded or missing" in page.locator("#cell").inner_text()
    assert page.locator("#values tr").count() == 0
    page.evaluate(f"pick({row},{col})")
    with page.expect_download() as info:
        page.locator("#download").click()
    downloaded = Path(info.value.path())
    assert json.loads(downloaded.read_text()) == report
    page.screenshot(path=str(root / "35-live-spectral-analysis.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(200)
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    page.screenshot(path=str(root / "36-spectral-mobile.png"), full_page=True)
    assert not errors, errors
    evidence = {
        "synthetic": False,
        "source": report["source"]["id"],
        "input_checksums": report["input_checksums"],
        "assertions": {
            "four_actual_grid_images": True,
            "click_picks_exact_source_cell": {"row": row, "column": col},
            "displayed_spectra_match_report_observations": True,
            "missing_cell_has_no_fraction_or_spectrum": True,
            "download_equals_analysis_report": True,
            "mobile_no_horizontal_overflow": True,
            "page_errors": errors,
        },
    }
    (root / "35-spectral-browser-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence["assertions"], indent=2))
    browser.close()
