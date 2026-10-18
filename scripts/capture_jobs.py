"""Exercise browser job reload/cancel/retry and capture actual held-out evaluation."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8768")
args = parser.parse_args()
root = Path("docs/showcase")
errors, submissions = [], []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1600, "height": 1150}, device_scale_factor=1)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "request",
        lambda req: (
            submissions.append(req.url)
            if req.method == "POST" and req.url.endswith("/api/jobs")
            else None
        ),
    )
    page.goto(args.url + "/workflows.html", wait_until="networkidle")
    # An actual satellite job is cancelled during discovery/preparation. Reload
    # and retry attach to its durable ID, rather than submitting another recipe.
    page.locator("#step").fill("1")
    page.locator("#refresh").check()
    page.locator("#coverage-auto").uncheck()
    with page.expect_response(
        lambda r: r.url.endswith("/api/jobs") and r.request.method == "POST"
    ) as response:
        page.locator("#workspace-run").click()
    assert response.value.status == 202
    job = response.value.json()
    page.locator("#job-cancel").click(timeout=15000)
    page.wait_for_function(
        "document.querySelector('#job-title').textContent.includes('cancelled')", timeout=120000
    )
    cancelled = page.request.get(args.url + "/api/jobs/" + job["id"]).json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["manifest_url"] is None
    page.reload(wait_until="networkidle")
    page.wait_for_function("document.querySelector('#job-title').textContent.includes('cancelled')")
    with page.expect_response(lambda r: r.url.endswith("/retry")) as retry:
        page.locator("#job-retry").click()
    assert retry.value.status == 202
    # Reload while the server is still working; no second submission is sent.
    page.reload(wait_until="domcontentloaded")
    page.wait_for_function(
        "document.querySelector('#status').dataset.state==='complete'", timeout=240000
    )
    assert len(submissions) == 1, submissions
    complete = page.request.get(args.url + "/api/jobs/" + job["id"]).json()
    assert complete["status"] == "succeeded" and complete["attempt"] == 2
    assert complete["id"] == cancelled["id"]
    page.locator("#date-slider").evaluate(
        "el => {el.value = '18'; el.dispatchEvent(new Event('input', {bubbles: true}));}"
    )
    page.set_viewport_size({"width": 1600, "height": 1350})
    page.locator("#job-journal").evaluate("el => el.open = true")
    page.locator("#job-events").evaluate("el => el.scrollTop = el.scrollHeight")
    page.evaluate("window.scrollTo(0,0)")
    page.wait_for_timeout(700)
    page.screenshot(path=str(root / "26-recoverable-jobs.png"))
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(500)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
        "Mobile horizontal overflow"
    )
    page.screenshot(path=str(root / "28-jobs-mobile.png"), full_page=True)

    # Evaluate the fixed, checksummed six-acquisition satellite run used in the
    # scientific evidence JSON. Loading a result does not submit a new job.
    page.set_viewport_size({"width": 1600, "height": 1150})
    page.goto(
        args.url + "/workflows.html?run=1315d34695e8484093cf6a0ec3cdacad", wait_until="networkidle"
    )
    page.wait_for_function("document.querySelector('#status').dataset.state==='complete'")
    with page.expect_response(lambda r: r.url.endswith("/validation"), timeout=30000) as validation:
        page.locator("#validate-series").click()
    assert validation.value.status == 200
    result = validation.value.json()
    page.wait_for_function("document.querySelector('#validation-result table') !== null")
    expected = json.loads((root / "25-live-temporal-validation.json").read_text())
    assert result == expected
    assert len(page.locator("#validation-result table").all()) == 2
    page.locator(".validation-panel").screenshot(
        path=str(root / "27-live-reconstruction-check.png")
    )
    assert not errors, errors
    evidence = {
        "job": complete,
        "cancelled_attempt": cancelled,
        "assertions": {
            "single_recipe_submission_across_reloads": len(submissions) == 1,
            "same_job_retry": complete["id"] == cancelled["id"],
            "cancellation_has_no_manifest": cancelled["manifest_url"] is None,
            "validation_matches_checksum_evidence": result == expected,
            "mobile_no_horizontal_overflow": True,
            "page_errors": errors,
        },
        "validation_summary": result["summary"],
    }
    (root / "27-browser-job-validation-evidence.json").write_text(
        json.dumps(evidence, indent=2) + "\n"
    )
    print(json.dumps(evidence["assertions"], indent=2))
    browser.close()
