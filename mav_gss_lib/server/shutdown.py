"""
mav_gss_lib.server.shutdown -- Shutdown-delay helpers.

Used by API/WS handlers to schedule a delayed process exit once all
browser clients disconnect.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import asyncio
import signal

from .state import WebRuntime
from ._task_utils import log_task_exception

SHUTDOWN_DELAY = 2


async def check_shutdown(runtime: WebRuntime) -> None:
    """Exit the process after a quiet period if all clients are gone."""
    await asyncio.sleep(SHUTDOWN_DELAY)
    with runtime.rx.lock:
        rx_count = len(runtime.rx.clients)
    with runtime.tx.lock:
        tx_count = len(runtime.tx.clients)
    if rx_count == 0 and tx_count == 0 and runtime.had_clients:
        with runtime.tx.send_lock:
            sending_active = runtime.tx.sending["active"]
        if sending_active:
            schedule_shutdown_check(runtime)
            return
        signal.raise_signal(signal.SIGINT)


def schedule_shutdown_check(runtime: WebRuntime) -> None:
    """Schedule or replace the delayed shutdown check task."""
    if runtime.shutdown_task and not runtime.shutdown_task.done():
        runtime.shutdown_task.cancel()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    runtime.shutdown_task = loop.create_task(check_shutdown(runtime))
    runtime.shutdown_task.add_done_callback(log_task_exception("shutdown-check"))
