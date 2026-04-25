"""Preflight WebSocket endpoint — streams startup check results.

Sends check results as they execute. Late-joining clients receive
the full backlog of already-completed checks. Supports rerun with
single-run guard to prevent concurrent executions.

Updater-coupled WS plumbing (schedule_update_check, _build_updates_event,
_handle_apply_update) lives in update.py. This module calls into it
lazily inside async handlers to avoid a top-level back-edge — update
imports _broadcast from here at module top.

Author:  Irfan Annuar - USC ISI SERC
"""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from mav_gss_lib.preflight import CheckResult, run_preflight, summarize
from ..state import get_runtime
from ..security import authorize_websocket

if TYPE_CHECKING:
    from ..state import WebRuntime

router = APIRouter()


# =============================================================================
#  PREFLIGHT PAYLOAD BUILDER
# =============================================================================

def _build_preflight_payload(runtime: "WebRuntime") -> dict:
    """Return a snapshot dict of the current preflight + spec-warning state.

    Included in the /ws/preflight broadcast and available for the UI to
    display non-fatal spec authoring warnings alongside check results.
    The ``mission_parse_warnings`` list is populated when the mission was
    loaded via the declarative YAML path; it is empty for hand-built missions.
    """
    return {
        "phase": getattr(runtime, "preflight_status", None),
        "results": list(getattr(runtime, "preflight_results", [])),
        "update": getattr(runtime, "update_status", None),
        "mission_parse_warnings": [
            str(w) for w in getattr(runtime, "parse_warnings", ())
        ],
    }


# =============================================================================
#  BROADCAST HELPERS
# =============================================================================

async def _broadcast(runtime: "WebRuntime", event: dict[str, Any]) -> None:
    """Append event to backlog, broadcast to all current clients, cull dead ones.

    Keeps the backlog append and the client snapshot inside a single
    `preflight_lock` acquisition — matches the atomic snapshot taken by
    the WS handler's backlog-replay path, so a new client connecting
    mid-broadcast never sees the same event twice.

    The send loop runs outside the lock (send_text is awaited) and any
    per-client failure is deferred into a second lock acquisition that
    removes the dead sockets from `preflight_clients`.
    """
    with runtime.preflight_lock:
        runtime.preflight_results.append(event)
        snapshot = list(runtime.preflight_clients)
    msg = json.dumps(event)
    dead = []
    for ws in snapshot:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    if dead:
        with runtime.preflight_lock:
            for ws in dead:
                if ws in runtime.preflight_clients:
                    runtime.preflight_clients.remove(ws)


# =============================================================================
#  PREFLIGHT DRIVER
# =============================================================================

async def run_preflight_and_broadcast(runtime: "WebRuntime", emit_reset: bool = False) -> None:
    """Run preflight checks and broadcast each result to connected clients.

    Guarded by runtime.preflight_running — concurrent calls are ignored.
    Always emits a summary event, even if a phase raises, so the UI
    reaches a terminal state and rerun stays unblocked.
    """
    if runtime.preflight_running:
        return
    runtime.preflight_running = True
    try:
        await _reset_snapshot(runtime, emit_reset)
        results: list[CheckResult] = []
        results.extend(await _run_mission_checks(runtime))
        results.append(await _resolve_updates(runtime))
        await _emit_summary(runtime, results)
    finally:
        runtime.preflight_running = False


async def _reset_snapshot(runtime: "WebRuntime", emit_reset: bool) -> None:
    """Clear backlog, flip preflight_done=False, optionally broadcast reset.

    The backlog clear and the preflight_done=False write share one lock
    acquisition so a joiner cannot snapshot an empty backlog while
    preflight_done is still True from the prior run.
    """
    with runtime.preflight_lock:
        runtime.preflight_results.clear()
        runtime.preflight_done = False
        reset_clients = list(runtime.preflight_clients) if emit_reset else []

    if not emit_reset:
        return

    reset_msg = json.dumps({"type": "reset"})
    dead: list = []
    for ws in reset_clients:
        try:
            await ws.send_text(reset_msg)
        except Exception:
            dead.append(ws)
    if dead:
        with runtime.preflight_lock:
            for ws in dead:
                if ws in runtime.preflight_clients:
                    runtime.preflight_clients.remove(ws)


async def _run_mission_checks(runtime: "WebRuntime") -> list[CheckResult]:
    """Stream mission preflight checks, broadcast each, return the list."""
    results: list[CheckResult] = []
    try:
        for check in run_preflight(
            cfg=runtime.platform_cfg,
            mission_cfg=runtime.mission_cfg,
            mission=runtime.mission,
            mission_id=runtime.mission_id,
            operator=runtime.operator,
            host=runtime.host,
            station=runtime.station,
        ):
            await _broadcast(runtime, {
                "type": "check",
                "group": check.group,
                "label": check.label,
                "status": check.status,
                "fix": check.fix,
                "detail": check.detail,
            })
            results.append(check)
            # Yield to event loop so WS frames flush and clients can connect
            await asyncio.sleep(0)
    except Exception as exc:
        err = CheckResult(
            group="internal",
            label="Preflight generator error",
            status="fail",
            detail=str(exc),
        )
        await _broadcast(runtime, {
            "type": "check",
            "group": err.group,
            "label": err.label,
            "status": err.status,
            "fix": err.fix,
            "detail": err.detail,
        })
        results.append(err)
    return results


async def _resolve_updates(runtime: "WebRuntime") -> CheckResult:
    """Resolve update status, broadcast as a check row, return synthetic result.

    Does NOT call schedule_update_check — scheduling is owned by app.py
    lifespan and the rerun handler in ws_preflight. Re-firing here would
    clobber a running future on cold start.
    """
    # Lazy import to avoid a top-level back-edge — update imports
    # _broadcast from this module at its top.
    from .update import _build_updates_event
    try:
        event = await _build_updates_event(runtime)
        await _broadcast(runtime, event)
        return CheckResult(
            group="updates",
            label=event["label"],
            status=event["status"],
        )
    except Exception as exc:
        fail_event = {
            "type": "check",
            "group": "updates",
            "label": "Update check failed",
            "status": "skip",
            "fix": "",
            "detail": str(exc),
            "meta": None,
        }
        await _broadcast(runtime, fail_event)
        return CheckResult(
            group="updates",
            label=fail_event["label"],
            status=fail_event["status"],
        )


async def _emit_summary(runtime: "WebRuntime", results: list[CheckResult]) -> None:
    """Compute summary, broadcast, and flip preflight_done=True under lock."""
    summary = summarize(results)
    # summarize() in preflight.py does not track 'skip' — compute it here
    # so the UI can distinguish a true "all passed" run from one that
    # silently skipped the updates check (e.g., offline fetch).
    skipped = sum(1 for r in results if r.status == "skip")
    summary_event = {
        "type": "summary",
        "total": summary.total,
        "passed": summary.passed,
        "failed": summary.failed,
        "warnings": summary.warnings,
        "skipped": skipped,
        "ready": summary.ready,
        "mission_parse_warnings": [
            str(w) for w in getattr(runtime, "parse_warnings", ())
        ],
    }
    await _broadcast(runtime, summary_event)
    with runtime.preflight_lock:
        runtime.preflight_done = True


# =============================================================================
#  WS ENDPOINT
# =============================================================================

@router.websocket("/ws/preflight")
async def ws_preflight(websocket: WebSocket) -> None:
    runtime = get_runtime(websocket)
    if not await authorize_websocket(websocket):
        return
    await websocket.accept()

    # Snapshot backlog and register as a live client (under lock)
    with runtime.preflight_lock:
        backlog = list(runtime.preflight_results)
        runtime.preflight_clients.append(websocket)

    try:
        # Replay backlog for late joiners
        for event in backlog:
            await websocket.send_text(json.dumps(event))

        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            action = msg.get("action")

            if action == "rerun" and not runtime.preflight_running:
                # Refresh the update future so the rerun picks up a fresh fetch
                # rather than replaying the stale cached result.
                from .update import schedule_update_check
                schedule_update_check(runtime)
                # run_preflight_and_broadcast atomically clears backlog
                # and broadcasts the reset event to all current clients.
                await run_preflight_and_broadcast(runtime, emit_reset=True)
                continue

            if action == "launched":
                with runtime.update_lock:
                    runtime.launched = True
                continue

            if action == "apply_update":
                from .update import _handle_apply_update
                await _handle_apply_update(runtime, websocket)
                continue
    except WebSocketDisconnect:
        pass
    finally:
        with runtime.preflight_lock:
            if websocket in runtime.preflight_clients:
                runtime.preflight_clients.remove(websocket)


