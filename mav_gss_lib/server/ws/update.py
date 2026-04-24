"""Updater WebSocket plumbing — extracted from preflight.py.

Hosts the three updater-coupled WS functions that share state on the
runtime.update_lock / update_status_future / update_in_progress fields:

- schedule_update_check: kicks off check_for_updates on a worker thread.
- _build_updates_event:  awaits the future and renders the WS event dict.
- _handle_apply_update:  drives apply_update with phase-progress broadcast.

The broadcast primitive (_broadcast) stays in preflight.py so the
preflight backlog/lock semantics remain owned by one module. This module
imports _broadcast at top-level; preflight.py imports nothing from
here at module top — only lazily inside the ws_preflight handler and
inside _resolve_updates.

Author:  Irfan Annuar - USC ISI SERC
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket

if TYPE_CHECKING:
    from ..state import WebRuntime

from mav_gss_lib.updater import (
    DirtyTreeError,
    UpdateStatus,
    apply_update,
    check_for_updates,
)
from ._utils import send_phase_fail
from .preflight import _broadcast


# =============================================================================
#  UPDATE CHECK SCHEDULING
# =============================================================================

def schedule_update_check(runtime: "WebRuntime") -> None:
    """Schedule check_for_updates() on the default thread-pool executor.

    Stores the asyncio.Future on runtime.update_status_future, replacing
    any previous value. Must be called from within the event loop.
    """
    loop = asyncio.get_running_loop()
    runtime.update_status_future = loop.run_in_executor(
        None,
        check_for_updates,
        10.0,
    )


# =============================================================================
#  UPDATES CHECK EVENT BUILDER
# =============================================================================

async def _build_updates_event(runtime: "WebRuntime") -> dict[str, Any]:
    """Resolve the update-status future and build the WS event dict.

    Async because runtime.update_status_future is an asyncio.Future that
    must be awaited, not .result()-polled from inside the event loop.
    """
    fut = runtime.update_status_future
    if fut is None:
        return {
            "type": "check",
            "group": "updates",
            "label": "Update check not run",
            "status": "skip",
            "fix": "",
            "detail": "",
            "meta": None,
        }
    try:
        status: UpdateStatus = await asyncio.wait_for(fut, timeout=2.0)
    except asyncio.TimeoutError:
        return {
            "type": "check",
            "group": "updates",
            "label": "Update check still running",
            "status": "skip",
            "fix": "",
            "detail": "",
            "meta": None,
        }
    except Exception as exc:
        return {
            "type": "check",
            "group": "updates",
            "label": "Update check failed",
            "status": "skip",
            "fix": "",
            "detail": str(exc),
            "meta": None,
        }

    runtime.update_status = status

    meta = {
        "branch": status.branch,
        "current_sha": status.current_sha,
        "behind_count": status.behind_count,
        "commits": [asdict(c) for c in status.commits],
        "missing_pip_deps": list(status.missing_pip_deps),
        "dirty": status.working_tree_dirty,
        "button": None,
        "button_disabled": False,
        "button_reason": None,
    }

    # The updater now only pulls commits; pip installs are the operator's
    # manual `pip install -r requirements.txt` step, surfaced here purely as
    # a warning when packages are missing. So the button only appears when
    # there's actually a commit to pull.
    has_update = status.behind_count > 0

    if status.update_applied_sha:
        label = f"Updated to {status.update_applied_sha[:7]}"
        result_status, result_label = ("ok", label)
    elif status.fetch_failed:
        meta["fetch_error"] = status.fetch_error
        # Dev mode is an intentional opt-out, not a failure. Emit 'ok' so the
        # developer still gets the green LAUNCH button and "ALL CHECKS PASSED"
        # summary — the row label makes the configured state clear without
        # nagging on every launch.
        if status.fetch_error and ".mav_dev" in status.fetch_error:
            result_status, result_label = ("ok", "Dev mode · updates disabled")
        elif status.fetch_error and "detached HEAD" in status.fetch_error:
            result_status, result_label = ("skip", "Detached HEAD · updates disabled")
        else:
            result_status, result_label = ("skip", "Update check skipped · could not reach origin")
    elif has_update:
        meta["button"] = "apply"
        if status.working_tree_dirty:
            meta["button_disabled"] = True
            meta["button_reason"] = "commit or stash local changes to enable"

        parts = [f"{status.behind_count} commits behind"]
        if status.missing_pip_deps:
            parts.append(
                f"{len(status.missing_pip_deps)} Python package"
                f"{'s' if len(status.missing_pip_deps) != 1 else ''} missing (run pip install)"
            )
        result_status, result_label = ("warn", "Update available · " + " · ".join(parts))
    elif status.missing_pip_deps:
        # No commits behind, but Python packages are missing — warn without the
        # apply button, since the updater can't fix this. Operator runs
        # `pip install -r requirements.txt` in their conda env.
        count = len(status.missing_pip_deps)
        result_status, result_label = (
            "warn",
            f"Up to date ({status.current_sha[:7]}) · "
            f"{count} Python package{'s' if count != 1 else ''} missing (run pip install)",
        )
    else:
        result_status, result_label = ("ok", f"Up to date ({status.current_sha[:7]})")

    return {
        "type": "check",
        "group": "updates",
        "label": result_label,
        "status": result_status,
        "fix": "",
        "detail": "",
        "meta": meta,
    }


# =============================================================================
#  APPLY UPDATE HANDLER
# =============================================================================

async def _handle_apply_update(runtime: "WebRuntime", websocket: WebSocket) -> None:
    """Handle an {action: "apply_update"} message.

    Never holds runtime.update_lock across any await — we flip the in-progress
    flag inside the lock, release, then dispatch to the worker thread.
    """
    # Phase 1: validate state and flip the in-progress flag atomically.
    fail_reason: "str | None" = None
    should_apply: bool = False
    status: "UpdateStatus | None" = None

    with runtime.update_lock:
        if runtime.launched:
            fail_reason = "updates disabled after launch"
        elif runtime.update_in_progress:
            fail_reason = "update already in progress"
        else:
            status = runtime.update_status
            if status is None:
                fail_reason = "update status unavailable (re-launch to refresh)"
            elif status.behind_count == 0:
                fail_reason = "nothing to update"
            elif status.working_tree_dirty:
                fail_reason = "local changes detected — commit or stash"
            else:
                runtime.update_in_progress = True
                should_apply = True
    # update_lock released here, BEFORE any awaits

    if fail_reason is not None:
        await send_phase_fail(websocket, "git_pull", fail_reason)
        return

    if not should_apply:
        return  # defensive

    # Phase 2: schedule apply_update on a worker thread with a thread->loop bridge.
    loop = asyncio.get_running_loop()

    def broadcast_dict(event: dict) -> None:
        """Called from worker thread; schedule onto the event loop.
        For the final 'restart' phase, block on flush before returning so
        the WS frame is sent before os.execv replaces the process."""
        fut = asyncio.run_coroutine_threadsafe(_broadcast(runtime, event), loop)
        if event.get("phase") == "restart" and event.get("status") == "running":
            try:
                fut.result(timeout=1.0)
            except Exception:
                pass

    # Phase 3: run apply_update, catch exceptions, always clear the flag.
    try:
        await loop.run_in_executor(None, apply_update, broadcast_dict, status)
    except DirtyTreeError:
        await send_phase_fail(websocket, "git_pull",
                              "local changes detected at apply time")
    except Exception as exc:
        await send_phase_fail(websocket, "git_pull",
                              f"{type(exc).__name__}: {exc}")
    finally:
        with runtime.update_lock:
            runtime.update_in_progress = False
