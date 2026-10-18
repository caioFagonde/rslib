"""Cooperative workflow checkpoints, independent of a UI or job scheduler."""

from collections.abc import Callable

Progress = Callable[[dict], None]


def notify(progress: Progress | None, phase: str, message: str, **details) -> None:
    if progress:
        progress({"phase": phase, "message": message, **details})
