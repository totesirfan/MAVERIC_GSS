"""
mav_gss_lib.web_runtime.runtime -- Shared Web Runtime Helpers

Small helper functions shared across the web backend for queue-item
construction, config merging, shutdown scheduling, and TX admission
validation.

These functions stay intentionally light so API routes and websocket
handlers do not need to duplicate queue/build/validation logic.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import asyncio
import copy
import signal
from typing import Any

from .state import SHUTDOWN_DELAY, WebRuntime, ensure_runtime
from .tx_queue import (  # noqa: F401
    make_delay, make_note, make_mission_cmd, validate_mission_cmd, sanitize_queue_items,
)
from ._task_utils import log_task_exception


# =============================================================================
#  SHUTDOWN HELPERS
# =============================================================================

async def check_shutdown(runtime: WebRuntime) -> None:
    """Exit the process after a quiet period if all clients are gone."""
    await asyncio.sleep(SHUTDOWN_DELAY)
    with runtime.rx.lock:
        rx_count = len(runtime.rx.clients)
    with runtime.tx.lock:
        tx_count = len(runtime.tx.clients)
    if rx_count == 0 and tx_count == 0 and runtime.had_clients:
        if runtime.tx.sending["active"]:
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


# =============================================================================
#  QUEUE / TX HELPERS
# =============================================================================

def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    """Merge nested dict *override* into *base* in place."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            deep_merge(base[key], value)
        else:
            base[key] = value


def build_send_context(runtime: WebRuntime | None = None):
    """Copy the current send-mode protocol context from the runtime."""
    runtime = ensure_runtime(runtime)
    with runtime.cfg_lock:
        return (
            runtime.cfg.get("tx", {}).get("uplink_mode", "AX.25"),
            copy.copy(runtime.csp),
            copy.copy(runtime.ax25),
        )


