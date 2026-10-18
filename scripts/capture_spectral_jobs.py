"""Opt-in real-data browser acceptance of queued spectral analysis and reports."""

import argparse
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8769")
args = parser.parse_args()
root = Path("docs/showcase")
run = "1315d34695e8484093cf6a0ec3cdacad"
expected = json.loads((root / "35-live-spectral-report.json").read_text())
with np.load(Path("data/runs") / run / "stack.npz", allow_pickle=False) as stack:
    valid = np.isfinite(stack["values"][2]).all(axis=0)
    missing = np.argwhere(~valid)[0]
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1680, "height": 1180}, device_scale_factor=1)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{args.url}/workflows.html?run={run}", wait_until="networkidle")
    page.wait_for_function("document.querySelector('#status').dataset.state==='complete'")
    link = page.locator("#spectral-launch")
    assert link.get_attribute("href") == f"/spectral.html?run={run}"
    assert link.get_attribute("download") is None
    link.click()
    page.wait_for_selector('#source-index option[value="2"]', state="attached")
    page.locator("#source-index").select_option("2")
    with page.expect_response(
        lambda r: r.url.endswith("/api/jobs") and r.request.method == "POST"
    ) as submitted:
        page.locator("#submit").click()
    assert submitted.value.status == 202
    job = submitted.value.json()
    page.wait_for_function(
        "document.querySelector('#status').dataset.state==='complete'", timeout=30000
    )
    page.wait_for_selector("#values tr")
    assert "Publishing complete" in page.locator("#journal").inner_text()
    assert "Complete exports are available" in page.locator("#journal").inner_text()
    report = page.request.get(
        job["manifest_url"]
        if job["manifest_url"]
        else f"{args.url}/api/analyses/{job['run_id']}/report.json"
    ).json()
    assert report["input_checksums"] == expected["input_checksums"]
    np.testing.assert_allclose(report["pca"]["loadings"], expected["pca"]["loadings"], atol=1e-13)
    np.testing.assert_allclose(
        report["vca"]["projected_endmembers"], expected["vca"]["projected_endmembers"], atol=1e-13
    )
    assert report["fcls"] == expected["fcls"]
    # Check an actual selected source cell through the image interaction.
    cell = report["vca"]["cells"][2]
    image = page.locator('img[data-layer="abundance.png"]')
    box = image.bounding_box()
    with page.expect_response(lambda r: "/pixel?" in r.url) as response:
        page.mouse.click(
            box["x"] + (cell["column"] + 0.5) / report["grid"]["width"] * box["width"],
            box["y"] + (cell["row"] + 0.5) / report["grid"]["height"] * box["height"],
        )
    pixel = response.value.json()
    assert pixel["row"] == cell["row"] and pixel["col"] == cell["column"] and pixel["valid"]
    np.testing.assert_allclose(pixel["observed"], report["vca"]["observed_spectra"][2], atol=1e-7)
    page.wait_for_selector("#values tr")
    page.locator("#loading-component").select_option("2")
    assert "PC3 explains" in page.locator("#variance").inner_text()
    assert page.locator("#loadings tr").count() == 6
    page.locator("#extra-display").select_option("pc-03.png")
    assert page.locator("#extra-map img").get_attribute("src").endswith("/pc-03.png")
    page.locator("#extra-display").select_option("")
    # A missing cell is selected by the same actual raster coordinates.
    box = image.bounding_box()
    with page.expect_response(lambda r: "/pixel?" in r.url) as response:
        page.mouse.click(
            box["x"] + (int(missing[1]) + 0.5) / report["grid"]["width"] * box["width"],
            box["y"] + (int(missing[0]) + 0.5) / report["grid"]["height"] * box["height"],
        )
    assert not response.value.json()["valid"]
    page.wait_for_function(
        "document.querySelector('#cell-detail').textContent.includes('Excluded or missing')"
    )
    assert page.locator("#values tr").count() == 0
    page.locator("#members button").first.click()
    page.wait_for_selector("#values tr")
    # A browser reload reattaches the same job and saved parameters.
    before = page.request.get(f"{args.url}/api/jobs?source_run_id={run}").json()["jobs"]
    url = page.url
    page.reload(wait_until="networkidle")
    page.wait_for_selector("#values tr")
    assert (
        page.locator("#seed").input_value() == "0"
        and page.locator("#source-index").input_value() == "2"
    )
    assert len(page.request.get(f"{args.url}/api/jobs?source_run_id={run}").json()["jobs"]) == len(
        before
    )
    assert job["id"] in page.url
    # Portable report and artifacts correspond to the same published result.
    bundle_response = page.request.get(f"{args.url}/api/analyses/{job['run_id']}/bundle.zip")
    bundle = ZipFile(BytesIO(bundle_response.body()))
    assert json.loads(bundle.read("report.json")) == report
    assert json.loads(bundle.read("request.json"))["spectral"] == report["recipe"]
    with page.expect_download() as downloaded:
        page.get_by_role("link", name="Saved job request", exact=True).click()
    assert json.loads(Path(downloaded.value.path()).read_text())["spectral"] == report["recipe"]
    # Retain a full working capture and the printable report.
    page.screenshot(path=str(root / "37-queued-spectral-workbench.png"), full_page=True)
    printable = browser.new_page(viewport={"width": 1450, "height": 1150})
    printable.on("pageerror", lambda e: errors.append(str(e)))
    printable.goto(f"{args.url}/api/analyses/{job['run_id']}/report.html", wait_until="networkidle")
    assert (
        printable.get_by_role("heading", name="Parent monitoring project", exact=True).count() == 1
    )
    assert report["source"]["id"] in printable.locator("body").inner_text()
    assert printable.locator("img").count() == 4
    printable.screenshot(path=str(root / "38-spectral-project-report.png"), full_page=True)
    printable.close()
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(200)
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), "Mobile overflow"
    page.screenshot(path=str(root / "39-spectral-workbench-mobile.png"), full_page=True)
    # Exercise retry through a real persisted cancelled job, not a fake result.
    cancelled = page.request.post(
        args.url + "/api/jobs", data={"kind": "spectral", "spectral": report["recipe"]}
    ).json()
    state = page.request.post(f"{args.url}/api/jobs/{cancelled['id']}/cancel").json()
    assert state["status"] in {"cancelled", "cancelling"}, state
    page.goto(f"{args.url}/spectral.html?job={cancelled['id']}", wait_until="networkidle")
    page.wait_for_function("document.querySelector('#status').dataset.state==='cancelled'")
    page.locator("#retry").click()
    page.wait_for_selector("#values tr", timeout=30000)
    retried = page.request.get(f"{args.url}/api/jobs/{cancelled['id']}").json()
    assert retried["status"] == "succeeded"
    assert retried["recipe"] == report["recipe"]
    assert not errors, errors
    evidence = {
        "synthetic": False,
        "source_run_id": run,
        "job_id": job["id"],
        "analysis_id": job["run_id"],
        "source": report["source"],
        "input_checksums": report["input_checksums"],
        "assertions": {
            "optical_run_launch_link": True,
            "queued_browser_execution": True,
            "numeric_parity_with_prior_cli_scene_fit": True,
            "terminal_journal_contains_publication": True,
            "raster_picks_actual_source_cell": pixel,
            "all_component_maps_and_loadings": True,
            "missing_values_remain_missing": True,
            "reload_keeps_job_and_parameters_without_duplicate_submission": True,
            "portable_bundle_and_saved_request_match_report": True,
            "printable_parent_recipe_and_support": True,
            "cancelled_job_retry_reuses_pinned_recipe": True,
            "mobile_no_overflow": True,
            "page_errors": errors,
        },
    }
    (root / "37-spectral-job-browser-evidence.json").write_text(
        json.dumps(evidence, indent=2) + "\n"
    )
    (root / "37-spectral-analysis-report.json").write_text(json.dumps(report, indent=2) + "\n")
    (root / "37-saved-spectral-request.json").write_text(
        json.dumps({"kind": "spectral", "spectral": report["recipe"]}, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in evidence["assertions"].items()
                if k != "raster_picks_actual_source_cell"
            },
            indent=2,
        )
    )
    browser.close()
