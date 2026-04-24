"""TX WebSocket action handlers and dispatch table.

Each handler is a standalone async function: (runtime, msg, websocket) -> None.
Guards are checked by the dispatch loop before calling the handler. The full
action/event contract for /ws/tx is documented in the header comment below.

Author:  Irfan Annuar - USC ISI SERC
"""

# ── TX WebSocket Contract ──────────────────────────────────────────────
#
# Client sends:  {"action": "<name>", ...payload}
# Server sends:  {"type": "<event>", ...data}
#
# Actions (client → server):
#   queue             {input: str}                    → queue_update | error
#   queue_mission_cmd {payload: dict}                 → queue_update | error
#   delete            {index: int}                    → queue_update
#   clear             {}                              → queue_update
#   undo              {}                              → queue_update
#   guard             {index: int}                    → queue_update
#   reorder           {order: int[]}                  → queue_update
#   add_delay         {delay_ms: int, index?: int}    → queue_update
#   edit_delay        {index: int, delay_ms: int}     → queue_update
#   send              {}                              → send_progress | error
#   abort             {}                              → send_aborted
#   guard_approve     {}                              → (resumes send)
#   guard_reject      {}                              → send_aborted
#
# Events (server → client):
#   queue_update      {items, summary, sending}
#   history           {items}
#   sent              {data: TxHistoryItem}
#   send_progress     {sent, total, current, waiting}
#   send_complete     {sent}
#   send_aborted      {sent, remaining}
#   guard_confirm     {index, display}
#   error             {error: str}
#   send_error        {error: str}
#   session_new       {}
# ───────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Callable, NamedTuple

from ..state import MAX_QUEUE
from .queue import QueueItem, make_delay, validate_mission_cmd
from .._task_utils import log_task_exception

if TYPE_CHECKING:
    from fastapi import WebSocket
    from ..state import WebRuntime


QueueMutator = Callable[[list[QueueItem]], None]


# ---------------------------------------------------------------------------
#  Guards
# ---------------------------------------------------------------------------

def requires_idle(runtime: "WebRuntime") -> str | None:
    """Return error string if a send is in progress, else None."""
    if runtime.tx.sending["active"]:
        return "cannot modify queue during send"
    return None


def requires_space(runtime: "WebRuntime") -> str | None:
    """Return error string if the queue is full, else None."""
    if len(runtime.tx.queue) >= MAX_QUEUE:
        return f"queue full ({MAX_QUEUE} items max)"
    return None


# ---------------------------------------------------------------------------
#  Queue mutation helper
# ---------------------------------------------------------------------------

def mutate_queue_if_idle(
    runtime: "WebRuntime",
    fn: QueueMutator,
    *,
    check_space: bool = False,
) -> str | None:
    """Run fn(queue) under send_lock with atomic idle + capacity checks.

    Returns an error string if the queue is being sent or full, else None.
    fn receives the queue list and may mutate it. After fn returns,
    renumber and save are done under the same lock. Broadcasts happen
    after the lock is released by the caller.

    If check_space=True, also enforces MAX_QUEUE before running fn.

    This is the ONLY correct way to mutate the queue from action handlers.
    The dispatch-loop guards (requires_idle, requires_space) are fast
    pre-checks; this function is the authoritative gate under the lock.
    """
    with runtime.tx.send_lock:
        if runtime.tx.sending["active"]:
            return "cannot modify queue during send"
        if check_space and len(runtime.tx.queue) >= MAX_QUEUE:
            return f"queue full ({MAX_QUEUE} items max)"
        fn(runtime.tx.queue)
        runtime.tx.renumber_queue()
        runtime.tx.save_queue()
    return None


async def send_error(ws: "WebSocket", error: str) -> None:
    """Send an error message to a single client."""
    await ws.send_text(json.dumps({"type": "error", "error": error}))


# ---------------------------------------------------------------------------
#  Handlers
# ---------------------------------------------------------------------------

async def handle_queue(runtime: "WebRuntime", msg: dict, ws: "WebSocket") -> None:
    """Parse CLI text and queue the resulting command."""
    line = msg.get("input", "").strip()
    if not line:
        await send_error(ws, "empty input")
        return
    try:
        item = validate_mission_cmd(line, runtime=runtime)
        err = mutate_queue_if_idle(runtime, lambda q: q.append(item), check_space=True)
        if err:
            await send_error(ws, err)
            return
        await runtime.tx.send_queue_update()
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        await send_error(ws, str(exc))


async def handle_queue_mission_cmd(runtime: "WebRuntime", msg: dict, ws: "WebSocket") -> None:
    """Queue a command from the mission builder UI."""
    try:
        payload = msg.get("payload", {})
        item = validate_mission_cmd(payload, runtime=runtime)
        err = mutate_queue_if_idle(runtime, lambda q: q.append(item), check_space=True)
        if err:
            await send_error(ws, err)
            return
        await runtime.tx.send_queue_update()
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        await send_error(ws, str(exc))


async def handle_delete(runtime: "WebRuntime", msg: dict, ws: "WebSocket") -> None:
    """Delete a queue item by index."""
    idx = msg.get("index")
    def do_delete(q: list[QueueItem]) -> None:
        if isinstance(idx, int) and 0 <= idx < len(q):
            q.pop(idx)
    err = mutate_queue_if_idle(runtime, do_delete)
    if err:
        await send_error(ws, err)
        return
    await runtime.tx.send_queue_update()


async def handle_clear(runtime: "WebRuntime", msg: dict, ws: "WebSocket") -> None:
    """Clear the entire queue."""
    err = mutate_queue_if_idle(runtime, lambda q: q.clear())
    if err:
        await send_error(ws, err)
        return
    await runtime.tx.send_queue_update()


async def handle_undo(runtime: "WebRuntime", msg: dict, ws: "WebSocket") -> None:
    """Remove the last item from the queue."""
    err = mutate_queue_if_idle(runtime, lambda q: q.pop() if q else None)
    if err:
        await send_error(ws, err)
        return
    await runtime.tx.send_queue_update()


async def handle_guard(runtime: "WebRuntime", msg: dict, ws: "WebSocket") -> None:
    """Toggle the guard flag on a queue item."""
    idx = msg.get("index")
    def do_guard(q: list[QueueItem]) -> None:
        if isinstance(idx, int) and 0 <= idx < len(q):
            item = q[idx]
            if item["type"] == "mission_cmd":
                item["guard"] = not item.get("guard", False)
    err = mutate_queue_if_idle(runtime, do_guard)
    if err:
        await send_error(ws, err)
        return
    await runtime.tx.send_queue_update()


async def handle_reorder(runtime: "WebRuntime", msg: dict, ws: "WebSocket") -> None:
    """Reorder queue items by index list."""
    order = msg.get("order", [])
    def do_reorder(q: list[QueueItem]) -> None:
        if isinstance(order, list) and len(order) == len(q):
            try:
                q[:] = [q[index] for index in order]
            except (IndexError, TypeError):
                pass
    err = mutate_queue_if_idle(runtime, do_reorder)
    if err:
        await send_error(ws, err)
        return
    await runtime.tx.send_queue_update()


async def handle_add_delay(runtime: "WebRuntime", msg: dict, ws: "WebSocket") -> None:
    """Insert a delay item at a given index or append."""
    delay_ms = max(0, min(300_000, int(msg.get("delay_ms", 1000))))
    idx = msg.get("index")
    item = make_delay(delay_ms)
    def do_add(q: list[QueueItem]) -> None:
        if isinstance(idx, int) and 0 <= idx <= len(q):
            q.insert(idx, item)
        else:
            q.append(item)
    err = mutate_queue_if_idle(runtime, do_add, check_space=True)
    if err:
        await send_error(ws, err)
        return
    await runtime.tx.send_queue_update()


async def handle_edit_delay(runtime: "WebRuntime", msg: dict, ws: "WebSocket") -> None:
    """Update delay_ms on an existing delay item."""
    idx = msg.get("index")
    delay_ms = msg.get("delay_ms")
    def do_edit(q: list[QueueItem]) -> None:
        if (
            isinstance(idx, int)
            and 0 <= idx < len(q)
            and q[idx]["type"] == "delay"
            and isinstance(delay_ms, (int, float))
        ):
            q[idx]["delay_ms"] = max(0, min(300_000, int(delay_ms)))
    err = mutate_queue_if_idle(runtime, do_edit)
    if err:
        await send_error(ws, err)
        return
    await runtime.tx.send_queue_update()


async def handle_send(runtime: "WebRuntime", msg: dict, ws: "WebSocket") -> None:
    """Start the TX send loop."""
    error = None
    with runtime.tx.send_lock:
        if runtime.tx.sending["active"] and runtime.tx.send_task and runtime.tx.send_task.done():
            runtime.tx.sending["active"] = False
        if runtime.tx.sending["active"]:
            error = "send already in progress"
        elif not runtime.tx.queue:
            error = "queue is empty"
        else:
            runtime.tx.abort.clear()
            runtime.tx.guard_ok.clear()
            runtime.tx.sending.update(
                active=True, total=len(runtime.tx.queue), idx=0,
                guarding=False, sent_at=0, waiting=False,
            )
    if error:
        await send_error(ws, error)
        return
    runtime.tx.send_task = asyncio.create_task(runtime.tx.run_send())
    runtime.tx.send_task.add_done_callback(log_task_exception("tx-send"))


async def handle_abort(runtime: "WebRuntime", msg: dict, ws: "WebSocket") -> None:
    """Abort the current send."""
    runtime.tx.abort.set()


async def handle_guard_approve(runtime: "WebRuntime", msg: dict, ws: "WebSocket") -> None:
    """Approve a pending guard confirmation."""
    runtime.tx.guard_ok.set()


async def handle_guard_reject(runtime: "WebRuntime", msg: dict, ws: "WebSocket") -> None:
    """Reject a pending guard — triggers abort."""
    runtime.tx.abort.set()


# ---------------------------------------------------------------------------
#  Dispatch table
# ---------------------------------------------------------------------------

class ActionSpec(NamedTuple):
    handler: Callable
    guards: list[Callable]


ACTIONS: dict[str, ActionSpec] = {
    "queue":             ActionSpec(handler=handle_queue,             guards=[requires_idle, requires_space]),
    "queue_mission_cmd": ActionSpec(handler=handle_queue_mission_cmd, guards=[requires_idle, requires_space]),
    "delete":            ActionSpec(handler=handle_delete,            guards=[requires_idle]),
    "clear":             ActionSpec(handler=handle_clear,             guards=[requires_idle]),
    "undo":              ActionSpec(handler=handle_undo,              guards=[requires_idle]),
    "guard":             ActionSpec(handler=handle_guard,             guards=[requires_idle]),
    "reorder":           ActionSpec(handler=handle_reorder,           guards=[requires_idle]),
    "add_delay":         ActionSpec(handler=handle_add_delay,         guards=[requires_idle, requires_space]),
    "edit_delay":        ActionSpec(handler=handle_edit_delay,        guards=[requires_idle]),
    "send":              ActionSpec(handler=handle_send,              guards=[]),
    "abort":             ActionSpec(handler=handle_abort,             guards=[]),
    "guard_approve":     ActionSpec(handler=handle_guard_approve,     guards=[]),
    "guard_reject":      ActionSpec(handler=handle_guard_reject,      guards=[]),
}
