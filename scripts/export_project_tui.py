"""Capture a saved browser project's actual area statistics in Textual."""

import argparse
import asyncio
import json
import os
from pathlib import Path

os.environ.pop("NO_COLOR", None)

from rslib.tui import Workbench

parser = argparse.ArgumentParser()
parser.add_argument("--project", default=None)
parser.add_argument("--data", type=Path, default=Path("data"))
args = parser.parse_args()
project_id = (
    args.project
    or json.loads(Path("docs/showcase/19-project-evidence.json").read_text())["project_id"]
)


async def capture():
    app = Workbench(args.data, project_id=project_id)
    async with app.run_test(size=(190, 54)) as pilot:
        assert app.last_stack is not None
        for _ in range(4):
            app.action_next_frame()
        app.action_fields()
        await pilot.pause(0.2)
        Path("docs/showcase/23-project-terminal.svg").write_text(app.export_screenshot())
        evidence = {
            "kind": "Actual terminal reopening a persisted browser project without acquisition",
            "project_id": project_id,
            "run_id": app.last_stack["id"],
            "date": app.last_stack["timeline"][app.stack_frame]["day"],
            "fields": app.last_stack["fields"],
            "synthetic": app.last_stack["synthetic"],
        }
        Path("docs/showcase/23-terminal-project-evidence.json").write_text(
            json.dumps(evidence, indent=2) + "\n"
        )


asyncio.run(capture())
