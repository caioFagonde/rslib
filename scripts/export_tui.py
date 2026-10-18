"""Render the actual Textual interface to a portable SVG showcase."""

import asyncio
import os
from pathlib import Path

from rslib.tui import Workbench


async def main():
    # Capture the supported true-color mode even in a noninteractive CI shell.
    os.environ.pop("NO_COLOR", None)
    app = Workbench(Path("data/showcase-tui"))
    async with app.run_test(size=(155, 46)) as pilot:
        await pilot.press("d")
        await app.workers.wait_for_complete()
        await pilot.press("a")
        await app.workers.wait_for_complete()
        await pilot.pause()
        Path("docs/showcase/07-terminal-workbench.svg").write_text(app.export_screenshot())


asyncio.run(main())
