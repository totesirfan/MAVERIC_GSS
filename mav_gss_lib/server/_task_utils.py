"""
mav_gss_lib.server._task_utils -- Shared asyncio task utilities.

Provides `log_task_exception` — the done-callback used by every background
asyncio task in the web runtime to surface silent failures to the standard
`logging` module. A task that dies without this callback is invisible: the
exception lives on the Task object and is only reported when the Task is
garbage-collected, long after the damage is done.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable


def log_task_exception(task_name: str) -> Callable[[asyncio.Task], None]:
    """Return a done-callback that logs any uncaught exception from a Task.

    The returned callback ignores cancellation and clean completion, and logs
    anything else at ERROR level with the task name so ops can grep for it.
    Use via `task.add_done_callback(log_task_exception("rx-broadcast"))`.
    """

    def _callback(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        logging.error("Background task %r died: %s", task_name, exc, exc_info=exc)

    return _callback
