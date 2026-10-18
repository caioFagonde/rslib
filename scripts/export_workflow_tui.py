"""Export the actual terminal stack workflow and gap-support rendering."""

import asyncio
import os
from pathlib import Path

os.environ.pop("NO_COLOR", None)

from rslib.tui import Workbench


async def capture():
    app = Workbench(Path("data/showcase-stack-tui"))
    async with app.run_test(size=(180, 54)) as pilot:
        app.action_stack()
        await app.workers.wait_for_complete()
        assert app.last_stack is not None
        for _ in range(3):
            app.action_next_frame()
        app.action_support()
        await pilot.pause(0.2)
        Path("docs/showcase/15-terminal-optical-workflow.svg").write_text(app.export_screenshot())


asyncio.run(capture())
