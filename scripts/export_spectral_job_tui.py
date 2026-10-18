"""Reopen the browser's actual spectral job in the TUI and compare Python/CLI fits."""

import asyncio
import json
import os
import subprocess
import uuid
from pathlib import Path

import numpy as np
from textual.widgets import DataTable, Select

from rslib.spectral_workflow import analyze_spectra
from rslib.tui import Workbench

root = Path("docs/showcase")


async def capture():
    os.environ.pop("NO_COLOR", None)  # Capture the supported true-color mode only.
    evidence = json.loads((root / "37-spectral-job-browser-evidence.json").read_text())
    app = Workbench(Path("data"))
    async with app.run_test(size=(210, 65)) as pilot:
        assert app.job_runner.lock is None, (
            "Run the preview server first; the TUI must share its worker"
        )
        app.selected_job_id = evidence["job_id"]
        app.open_selected_job()
        await app.workers.wait_for_complete()
        await pilot.pause(0.2)
        report = app.spectral_report
        assert report["id"] == evidence["analysis_id"]
        assert app.query_one("#spectral-values", DataTable).row_count == 6
        assert app.query_one("#spectral-members", DataTable).row_count == 3
        app.query_one("#sp-loading", Select).value = "2"
        await pilot.pause(0.1)
        assert app.query_one("#spectral-loadings", DataTable).row_count == 6
        app.query_one("#spectral-result").scroll_visible(top=True)
        await pilot.pause(0.2)
        (root / "40-terminal-spectral-job.svg").write_text(app.export_screenshot())
        # Cross-interface checks on the exact saved inputs, not another AOI.
        recipe = report["recipe"]
        outputs = Path("data/acceptance") / ("spectral-" + uuid.uuid4().hex)
        python_report = await asyncio.to_thread(
            analyze_spectra,
            Path("data/runs") / recipe["run_id"],
            outputs / "python",
            **{
                k: recipe[k]
                for k in ["source_index", "components", "endmembers", "projection", "seed"]
            },
            expected_checksums=recipe["input_checksums"],
        )
        command = [
            "uv",
            "run",
            "rslib",
            "spectral-analysis",
            str(Path("data/runs") / recipe["run_id"]),
            str(outputs / "cli"),
        ]
        for key in ["source_index", "components", "endmembers", "projection", "seed"]:
            command.extend(["--" + key.replace("_", "-"), str(recipe[key])])
        completed = await asyncio.to_thread(
            subprocess.run, command, capture_output=True, text=True, check=True
        )
        cli_report = json.loads((outputs / "cli" / "report.json").read_text())
        for candidate in [python_report, cli_report]:
            assert candidate["input_checksums"] == report["input_checksums"]
            np.testing.assert_allclose(
                candidate["pca"]["loadings"], report["pca"]["loadings"], atol=1e-13
            )
            np.testing.assert_allclose(
                candidate["vca"]["projected_endmembers"],
                report["vca"]["projected_endmembers"],
                atol=1e-13,
            )
            assert candidate["fcls"] == report["fcls"]
        result = {
            "capture_color_mode": "truecolor; NO_COLOR unset only for the capture process",
            "synthetic": False,
            "job_id": evidence["job_id"],
            "analysis_id": report["id"],
            "source_run_id": recipe["run_id"],
            "input_checksums": report["input_checksums"],
            "assertions": {
                "same_browser_job_opened_in_terminal": True,
                "terminal_shared_existing_worker": True,
                "six_band_cell_inspection": True,
                "all_pca_components_selectable": True,
                "browser_terminal_cli_python_numerical_parity": True,
                "new_job_not_submitted_on_open": app.jobs.get_job(evidence["job_id"])["attempt"]
                == 1,
            },
            "separate_parity_outputs": str(outputs),
            "cli_return_code": completed.returncode,
        }
        (root / "40-spectral-interface-parity.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result["assertions"], indent=2))


asyncio.run(capture())
