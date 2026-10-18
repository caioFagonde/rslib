"""Capture the terminal's actual cross-sensor quantitative check on satellite data."""

import asyncio
import json
from pathlib import Path

from textual.widgets import DataTable

from rslib.tui import Workbench

RUN = "1315d34695e8484093cf6a0ec3cdacad"


async def capture():
    app = Workbench(Path("data"))
    async with app.run_test(size=(200, 55)) as pilot:
        app.last_stack = json.loads((app.data_dir / "runs" / RUN / "manifest.json").read_text())
        app.run_diagnostics("agreement")
        await app.workers.wait_for_complete()
        await pilot.pause(0.2)
        assert app.query_one("#diagnostics-table", DataTable).row_count == 6
        Path("docs/showcase/34-terminal-sensor-agreement.svg").write_text(app.export_screenshot())
        app.run_diagnostics("validation")
        await app.workers.wait_for_complete()
        assert app.query_one("#diagnostics-table", DataTable).row_count == 6
        Path("docs/showcase/34-terminal-checks-evidence.json").write_text(
            json.dumps(
                {
                    "run_id": RUN,
                    "synthetic": False,
                    "agreement_band_rows": 6,
                    "whole_date_holdout_rows": 6,
                    "same_published_input": True,
                },
                indent=2,
            )
            + "\n"
        )


asyncio.run(capture())
