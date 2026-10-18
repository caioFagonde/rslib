"""Idempotently publish the accepted roadmap as GitHub milestones/issues and a board.

Requires configured gh authentication. Project creation additionally needs the
project scope; a missing scope leaves the repository issues/milestones intact.
"""

import argparse
import json
import subprocess

MILESTONES = {
    "Release A — dependable optical monitoring": "A1–A4 acceptance gates in docs/ROADMAP.md. Current active work: reference labels and evaluation; no scheduled delivery date.",
    "Release B — classical and additional sensors": "Classical fit/apply workflows, calibrated SAR and measured model integrations after optical readiness gates.",
    "Release C — quantitative applications": "Application-specific inputs, units, uncertainty and independent field/reference evaluation.",
    "Native hydrology": "Independent Rust implementation of public equations and reference cases; no installed TRIGRS wrapper.",
}
ISSUES = [
    (
        "A1: Attach independent labels to the frozen reference campaign",
        "Release A — dependable optical monitoring",
        "active",
        "Six actual-satellite sites and source/support diagnostics are frozen; independent cloud and material labels are absent.\n\n- Pin label versions, licenses, acquisition correspondence, class definitions and geographic split groups.\n- Start with expert high-quality cloud/shadow patches; keep scribble/unlabeled data and model masks separate.\n- Declare application tolerances before evaluation. Report omission, commission, coverage and unscored samples.\n- Obtain an appropriate labeled material/spectral reference for FCLS; reconstruction RMSE alone is not fraction accuracy.\n\nAcceptance: reproducible label alignment and held-out reports with hashes, class/coverage denominators and independent references. Existing Itatiaia data remain development-only.",
    ),
    (
        "A2: Integrate HLS L30/S30 discovery and access",
        "Release A — dependable optical monitoring",
        "planned",
        "The library recognizes preharmonized inputs but the high-level optical workflow discovers ordinary Sentinel-2/Landsat SR.\n\nImplement documented HLS discovery/access, source versions, Fmask/aerosol policy, calibration and saved-job provenance. Preserve preharmonized values without applying the local bandpass adjustment twice.\n\nAcceptance: pinned real L30/S30 cases, QA/calibration and interface parity checks, explicit credentials/access behavior, and reports that distinguish HLS from ground truth.",
    ),
    (
        "A2: Diagnose cross-sensor NIR residuals across sites",
        "Release A — dependable optical monitoring",
        "planned",
        "The retained Itatiaia pair has high NDVI correlation but weak NIR agreement. A common grid does not prove registration.\n\nCompare multiple near-coincident pairs by band, native footprint, illumination, atmospheric/QA context and residual spatial offset. Retain uncorrected inputs and avoid fitting a correction to the diagnostic case.\n\nAcceptance: held-out site/season strata, sample coverage and per-band/spatial diagnostics; any correction needs its own declared validation gate.",
    ),
    (
        "A3: Benchmark and select bounded chunk execution",
        "Release A — dependable optical monitoring",
        "planned",
        "Current optical preparation materializes bounded arrays; the xarray adapter does not make acquisition lazy.\n\nBenchmark the existing loader against ODC-STAC/xarray/Dask under equivalent calibration, native QA and aggregation. Measure cold acquisition, bytes/requests, cache reuse, peak RSS, output size and cell/date interaction. Select a backend from measured parity and resource results.\n\nAcceptance: documented 2/10/50 km benchmark profile, chunk-seam/mask/source parity, cancellation/resume without duplicate reads, bounded inspector queries and a declared memory budget. Proposed targets in ROADMAP.md are not existing performance claims.",
    ),
    (
        "A4: Evaluate composites and temporal policies with coverage",
        "Release A — dependable optical monitoring",
        "planned",
        "Expose existing whole-spectrum quality/medoid operations as saved workbench tasks with source dates/counts/spread. Evaluate QA-weighted Whittaker smoothing and event-sensitive gap rules against the existing paired baselines.\n\nInclude contiguous/cloud-shaped gaps and change periods; preserve observations and distinguish smoothing from reconstruction. Keep edge dates, abstention and unsupported cells in coverage. The frozen five-day query failures are retained diagnostics.\n\nAcceptance: identical held-out cells, error/coverage tradeoffs, gap/change strata, source inspection and explicit retrospective-versus-causal behavior.",
    ),
    (
        "B1: Extend validated classical fit/apply workflows",
        "Release B — classical and additional sensors",
        "planned",
        "PCA/VCA/FCLS are implemented; this work extends coherent workflows rather than a static method catalog.\n\nPriorities: defensible MNF noise covariance, SAM/SID, matched filters/ACE/RX, verified sensor/product tasseled-cap coefficients, hyperspectral spectral-response handling, and physical-window texture/morphology. Reuse supported libraries when licensing and numerical behavior fit.\n\nAcceptance: saved coefficients/mask contracts, independent numerical references and task labels, held-out evaluation, browser/TUI/CLI parity and measured resources.",
    ),
    (
        "B2: Add calibrated Sentinel-1 and optical/SAR workflows",
        "Release B — classical and additional sensors",
        "planned",
        "Sentinel-1 discovery exists; calibrated analysis and fusion are not implemented.\n\nStart with documented analysis-ready backscatter or a reproducible calibration/terrain-correction backend. Preserve orbit, polarization, geometry, incidence, layover/shadow masks, speckle policy and linear/dB units.\n\nAcceptance: independent processing/reference comparison and geographically separated flood/wetness/change events. SAR-assisted optical estimates remain identified as estimates; InSAR is a separate complex-data workflow.",
    ),
    (
        "C: Validate soil/carbon and quantitative application inputs",
        "Release C — quantitative applications",
        "planned",
        "Soil/SOC helpers and physical scenarios are separate components, not a validated carbon or hazard application.\n\nDefine each target, units, spatial/temporal support, measured inputs, uncertainty and independent references before integrating retrievals. Preserve SoilGrids transformations and pedotransfer assumptions. SOC stock changes are not measured emissions. Do not invent absent geotechnical or meteorological inputs.\n\nAcceptance: one bounded application with external reference observations, declared tolerances, uncertainty/sensitivity evidence and reproducible reports. Follow the application-specific gates in ROADMAP.md.",
    ),
    (
        "Hydrology: Validate further TRIGRS-equation coverage in Rust",
        "Native hydrology",
        "planned",
        "The current native engine implements the documented wet-initial-condition kernel, pressure/FS scenarios and D8 runon water accounting. It does not implement the full unsaturated Gardner/moving-water-table model.\n\nTranscribe independent published benchmark cases and equation/unit mappings before extending unsupported physics. Keep forcing/material inputs explicit and preserve numerical/mass-balance checks.\n\nAcceptance: independent reference comparisons and parameter sensitivity for each added regime; site observations are required before hazard claims. No installed TRIGRS executable is required or wrapped.",
    ),
]


def gh(*args, value=None):
    command = ["gh", *args]
    if value is not None:
        command += ["--input", "-"]
    return json.loads(
        subprocess.check_output(
            command, input=json.dumps(value).encode() if value is not None else None
        )
    )


def main(repo, board):
    milestones = gh("api", "--paginate", f"repos/{repo}/milestones?state=all&per_page=100")
    numbers = {m["title"]: m["number"] for m in milestones}
    for title, description in MILESTONES.items():
        if title not in numbers:
            created = gh(
                "api",
                f"repos/{repo}/milestones",
                value={"title": title, "description": description},
            )
            numbers[title] = created["number"]
    for name, color, description in [
        ("active", "0E7770", "Current milestone work"),
        ("planned", "667788", "Accepted roadmap; not implemented"),
    ]:
        subprocess.run(
            [
                "gh",
                "label",
                "create",
                name,
                "--repo",
                repo,
                "--color",
                color,
                "--description",
                description,
                "--force",
            ],
            check=True,
        )
    existing = gh(
        "issue", "list", "--repo", repo, "--state", "all", "--limit", "100", "--json", "title,url"
    )
    issues = {i["title"]: i["url"] for i in existing}
    for title, milestone, label, body in ISSUES:
        if title not in issues:
            created = gh(
                "api",
                f"repos/{repo}/issues",
                value={
                    "title": title,
                    "body": body
                    + f"\n\nScope and acceptance source: https://github.com/{repo}/blob/main/docs/ROADMAP.md",
                    "milestone": numbers[milestone],
                    "labels": [label],
                },
            )
            issues[title] = created["html_url"]
    print(
        json.dumps({"repository": repo, "roadmap_issues": [issues[i[0]] for i in ISSUES]}, indent=2)
    )
    if board:
        owner = repo.split("/")[0]
        projects = gh("project", "list", "--owner", owner, "--format", "json")
        project = next((p for p in projects["projects"] if p["title"] == "RSLIB roadmap"), None)
        if project is None:
            project = gh(
                "project",
                "create",
                "--owner",
                owner,
                "--title",
                "RSLIB roadmap",
                "--format",
                "json",
            )
        number = str(project["number"])
        subprocess.run(
            ["gh", "project", "link", number, "--owner", owner, "--repo", repo], check=True
        )
        items = gh(
            "project", "item-list", number, "--owner", owner, "--limit", "100", "--format", "json"
        )
        included = {item.get("content", {}).get("url") for item in items["items"]}
        for title, *_ in ISSUES:
            if issues[title] not in included:
                subprocess.run(
                    ["gh", "project", "item-add", number, "--owner", owner, "--url", issues[title]],
                    check=True,
                )
        print(project["url"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="caioFagonde/rslib")
    parser.add_argument("--board", action="store_true", help="Requires the gh project OAuth scope")
    args = parser.parse_args()
    main(args.repo, args.board)
