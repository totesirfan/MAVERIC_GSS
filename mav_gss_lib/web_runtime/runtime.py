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
import os
import signal
from typing import Any

from .state import SHUTDOWN_DELAY, WebRuntime, ensure_runtime

try:
    from mav_gss_lib.protocols.golay import MAX_PAYLOAD as GOLAY_MAX_PAYLOAD
except ImportError:
    GOLAY_MAX_PAYLOAD = 223


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
        os.kill(os.getpid(), signal.SIGINT)


def schedule_shutdown_check(runtime: WebRuntime) -> None:
    """Schedule or replace the delayed shutdown check task."""
    if runtime.shutdown_task and not runtime.shutdown_task.done():
        runtime.shutdown_task.cancel()
    try:
        runtime.shutdown_task = asyncio.get_event_loop().create_task(check_shutdown(runtime))
    except RuntimeError:
        pass


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


def make_delay(delay_ms):
    """Build one delay queue item."""
    return {"type": "delay", "delay_ms": delay_ms}


def make_mission_cmd(payload, adapter=None):
    """Build one mission-command queue item from a mission-specific payload.

    Calls the adapter's build_tx_command() to validate, encode, and
    produce display metadata. Does NOT check MTU — use
    validate_mission_cmd() for full admission.

    The original payload is stored so it can be re-built on queue restore.
    """
    result = adapter.build_tx_command(payload)
    return {
        "type": "mission_cmd",
        "raw_cmd": result["raw_cmd"],
        "display": result.get("display", {}),
        "guard": result.get("guard", False),
        "payload": payload,
    }


def validate_mission_cmd(payload, runtime: WebRuntime | None = None):
    """Validate and build a mission-command queue item.

    Checks: adapter has TX builder, build succeeds, MTU fits.
    """
    runtime = ensure_runtime(runtime)
    from mav_gss_lib.mission_adapter import has_tx_builder

    if not has_tx_builder(runtime.adapter):
        raise ValueError("mission does not support TX command builder")

    item = make_mission_cmd(payload, adapter=runtime.adapter)

    uplink_mode, send_csp, _send_ax25 = build_send_context(runtime)
    if uplink_mode == "ASM+Golay":
        csp_packet = send_csp.wrap(item["raw_cmd"])
        if len(csp_packet) > GOLAY_MAX_PAYLOAD:
            raise ValueError(
                f"command too large for ASM+Golay RS payload "
                f"({len(csp_packet)}B > {GOLAY_MAX_PAYLOAD}B)"
            )
    return item


def sanitize_queue_items(items, runtime: WebRuntime | None = None):
    """Filter a queue restore/import set down to valid command/delay items."""
    runtime = ensure_runtime(runtime)
    accepted = []
    skipped = 0
    for item in items:
        if item["type"] == "delay":
            accepted.append(item)
            continue
        if item["type"] == "mission_cmd":
            try:
                accepted.append(
                    validate_mission_cmd(
                        item.get("payload", {}),
                        runtime=runtime,
                    )
                )
            except ValueError:
                skipped += 1
            continue
        # Legacy cmd items — convert to mission payload
        try:
            adapter = runtime.adapter
            mission_payload = {
                "cmd_id": item["cmd"],
                "args": item.get("args", ""),
                "dest": adapter.node_name(item["dest"]),
                "echo": adapter.node_name(item["echo"]),
                "ptype": adapter.ptype_name(item["ptype"]),
                "guard": item.get("guard", False),
            }
            accepted.append(
                validate_mission_cmd(mission_payload, runtime=runtime)
            )
        except (ValueError, KeyError):
            skipped += 1
    return accepted, skipped
