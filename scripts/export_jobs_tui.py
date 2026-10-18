"""Capture the actual terminal reading the persisted browser job journal."""

import asyncio
import json
from pathlib import Path

from textual.widgets import DataTable

from rslib.tui import Workbench


async def capture():
    evidence = json.loads(Path("docs/showcase/27-browser-job-validation-evidence.json").read_text())
    identifier = evidence["job"]["id"]
    app = Workbench(Path("data"))
    async with app.run_test(size=(200, 56)) as pilot:
        app.selected_job_id = identifier
        app.action_jobs()
        await pilot.pause(0.3)
        assert app.query_one("#jobs-table", DataTable).row_count >= 1
        Path("docs/showcase/29-terminal-job-journal.svg").write_text(app.export_screenshot())
        app.open_selected_job()
        assert app.last_stack["id"] == evidence["job"]["run_id"]
        assert app.last_stack["synthetic"] is False
        Path("docs/showcase/29-terminal-job-evidence.json").write_text(
            json.dumps(
                {
                    "job_id": identifier,
                    "run_id": app.last_stack["id"],
                    "synthetic": app.last_stack["synthetic"],
                    "reused_browser_job": True,
                    "opened_result_without_submission": True,
                    "summary": app.last_stack["summary"],
                },
                indent=2,
            )
            + "\n"
        )


asyncio.run(capture())
