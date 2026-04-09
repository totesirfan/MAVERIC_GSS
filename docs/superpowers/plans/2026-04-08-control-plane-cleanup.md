# Control Plane Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split concentrated backend control-plane modules, deduplicate RX rendering, split frontend state into isolated providers, and align the TX WebSocket contract.

**Architecture:** Backend api.py splits into a package of route modules; tx.py gets a dispatch table replacing the if/elif chain; broadcast_safe() centralizes dead-client cleanup with lock-aware snapshots; RX rendering computes once and flows through; frontend AppProvider splits into three independent React contexts.

**Tech Stack:** Python 3.10+ / FastAPI / asyncio / threading, React 18 / TypeScript / Vite

**Spec:** `docs/superpowers/specs/2026-04-08-control-plane-cleanup-design.md`

---

## Dependency Order

```
Task 1 (api/ package) → Task 2 (broadcast_safe) → Task 3 (RX rendering dedup)
Task 4 (tx dispatch table)  — parallel with Tasks 1-3
Task 5 (frontend state split) — independent of all backend tasks
Task 6 (TX contract alignment) — after Task 4
```

---

### Task 1: Split api.py into `api/` package

**Files:**
- Delete: `mav_gss_lib/web_runtime/api.py`
- Create: `mav_gss_lib/web_runtime/api/__init__.py`
- Create: `mav_gss_lib/web_runtime/api/config.py`
- Create: `mav_gss_lib/web_runtime/api/schema.py`
- Create: `mav_gss_lib/web_runtime/api/queue_io.py`
- Create: `mav_gss_lib/web_runtime/api/logs.py`
- Create: `mav_gss_lib/web_runtime/api/session.py`
- Modify: `mav_gss_lib/web_runtime/app.py:24`
- Modify: `tests/test_ops_web_runtime.py:20-26` (update imports)

- [ ] **Step 1: Create `api/__init__.py` with combined router**

```python
"""
mav_gss_lib.web_runtime.api -- REST API Routes (package)

Organizes HTTP routes into focused modules. The parent router
re-exports all sub-routers for app.py to mount as before.
"""

from fastapi import APIRouter

from .config import router as config_router
from .schema import router as schema_router
from .queue_io import router as queue_io_router
from .logs import router as logs_router
from .session import router as session_router

router = APIRouter()
router.include_router(config_router)
router.include_router(schema_router)
router.include_router(queue_io_router)
router.include_router(logs_router)
router.include_router(session_router)
```

- [ ] **Step 2: Create `api/config.py` — status, selfcheck, config get/put**

Move lines 47–162 from the old `api.py` into this file. The module needs these imports:

```python
"""Config and status endpoints."""

from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from mav_gss_lib.config import (
    apply_ax25,
    apply_csp,
    save_gss_config,
)
from ..state import get_runtime
from ..runtime import deep_merge
from ..security import require_api_token

router = APIRouter()
```

Then paste the four route functions verbatim: `api_status`, `api_selfcheck`, `api_config_get`, `api_config_put`. No logic changes — pure relocation.

- [ ] **Step 3: Create `api/schema.py` — schema, columns, capabilities**

Move lines 165–193 from the old `api.py`:

```python
"""Schema and column definition endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..state import get_runtime

router = APIRouter()
```

Then paste: `api_schema`, `api_columns`, `api_tx_capabilities`, `api_tx_columns`. No logic changes.

- [ ] **Step 4: Create `api/queue_io.py` — import/export**

Move lines 200–299 from the old `api.py`:

```python
"""Queue import and export endpoints."""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..state import MAX_QUEUE, get_runtime
from ..tx_queue import parse_import_file, make_delay, sanitize_queue_items, validate_mission_cmd, item_to_json
from ..security import require_api_token

router = APIRouter()
```

Then paste: `list_import_files`, `preview_import`, `import_file`, `export_queue`. No logic changes.

- [ ] **Step 5: Create `api/logs.py` — log browsing**

Move lines 306–455 from the old `api.py`:

```python
"""Log browsing endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..state import get_runtime

router = APIRouter()
```

Then paste: `parse_replay_entry` (helper function) and routes `api_logs`, `api_log_entries`. No logic changes.

- [ ] **Step 6: Create `api/session.py` — session lifecycle**

Move lines 458–663 from the old `api.py`:

```python
"""Session lifecycle endpoints."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..state import Session, get_runtime
from ..security import require_api_token

router = APIRouter()
```

Then paste: `_session_info`, `api_session_get`, `api_session_new`, `api_session_rename`, `tag_session`, `new_session`. No logic changes.

- [ ] **Step 7: Delete the old `api.py` file**

```bash
rm mav_gss_lib/web_runtime/api.py
```

- [ ] **Step 8: Verify `app.py` import still works**

`app.py` line 24 already imports `from .api import router as api_router`. Since `api/__init__.py` re-exports `router`, no change is needed in `app.py`. Verify by reading the import:

```python
# app.py line 24 — this import resolves to api/__init__.py now
from .api import router as api_router
```

- [ ] **Step 9: Update test imports**

In `tests/test_ops_web_runtime.py`, lines 20–26 import directly from `mav_gss_lib.web_runtime.api`. Update these to point at the new submodules:

```python
# Before:
from mav_gss_lib.web_runtime.api import (
    export_queue,
    import_file,
    list_import_files,
    parse_import_file,
    preview_import,
)

# After:
from mav_gss_lib.web_runtime.api.queue_io import (
    export_queue,
    import_file,
    list_import_files,
    preview_import,
)
from mav_gss_lib.web_runtime.api.logs import parse_replay_entry
from mav_gss_lib.web_runtime.tx_queue import parse_import_file
```

Note: `parse_import_file` was already re-imported into the old `api.py` from `tx_queue`. Check whether the test actually uses it from `api` or from `tx_queue` and adjust accordingly.

- [ ] **Step 10: Run tests**

```bash
cd tests
python3 test_ops_web_runtime.py -v
python3 test_ops_tx_runtime.py -v
python3 test_ops_protocol_core.py -v
```

Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add mav_gss_lib/web_runtime/api/ tests/test_ops_web_runtime.py
git rm mav_gss_lib/web_runtime/api.py
git commit -m "Split api.py into api/ package with focused route modules"
```

---

### Task 2: Extract `broadcast_safe()` from services.py

**Files:**
- Modify: `mav_gss_lib/web_runtime/services.py`
- Modify: `mav_gss_lib/web_runtime/api/session.py` (created in Task 1)

- [ ] **Step 1: Add `broadcast_safe()` helper at top of services.py**

Insert after the existing imports (after line 38):

```python
async def broadcast_safe(clients: list, lock: threading.Lock, payload: str) -> None:
    """Send payload to all clients, removing dead connections.

    Snapshots the client list under lock before iterating to avoid
    races with concurrent connect/disconnect. Lock is held briefly
    twice: once to snapshot, once to remove dead sockets.
    """
    with lock:
        snapshot = list(clients)
    dead = []
    for ws in snapshot:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    if dead:
        with lock:
            for ws in dead:
                if ws in clients:
                    clients.remove(ws)
```

- [ ] **Step 2: Replace `RxService.broadcast()` (lines 108–119)**

```python
async def broadcast(self, msg):
    """Broadcast one JSON-serializable message to all RX websocket clients."""
    text = json.dumps(msg) if isinstance(msg, dict) else msg
    await broadcast_safe(self.clients, self.lock, text)
```

- [ ] **Step 3: Replace packet broadcast in `broadcast_loop()` (lines 155–164)**

Replace:
```python
                msg = json.dumps({"type": "packet", "data": pkt_json})
                with self.lock:
                    dead = []
                    for ws in self.clients:
                        try:
                            await ws.send_text(msg)
                        except Exception:
                            dead.append(ws)
                    for ws in dead:
                        self.clients.remove(ws)
```

With:
```python
                msg = json.dumps({"type": "packet", "data": pkt_json})
                await broadcast_safe(self.clients, self.lock, msg)
```

- [ ] **Step 4: Replace plugin hook broadcast (lines 173–182)**

Replace:
```python
                            for extra in extra_msgs:
                                extra_text = json.dumps(extra)
                                with self.lock:
                                    dead = []
                                    for ws in self.clients:
                                        try:
                                            await ws.send_text(extra_text)
                                        except Exception:
                                            dead.append(ws)
                                    for ws in dead:
                                        self.clients.remove(ws)
```

With:
```python
                            for extra in extra_msgs:
                                extra_text = json.dumps(extra)
                                await broadcast_safe(self.clients, self.lock, extra_text)
```

- [ ] **Step 5: Replace status broadcast (lines 230–238)**

Replace:
```python
                with self.lock:
                    dead = []
                    for ws in self.clients:
                        try:
                            await ws.send_text(status_msg)
                        except Exception:
                            dead.append(ws)
                    for ws in dead:
                        self.clients.remove(ws)
```

With:
```python
                await broadcast_safe(self.clients, self.lock, status_msg)
```

- [ ] **Step 6: Replace `TxService.broadcast()` (lines 320–331)**

```python
async def broadcast(self, msg):
    """Broadcast one JSON-serializable message to all TX websocket clients."""
    text = json.dumps(msg) if isinstance(msg, dict) else msg
    await broadcast_safe(self.clients, self.lock, text)
```

- [ ] **Step 7: Replace session broadcast in `api/session.py`**

In `api_session_new()` (around the session_clients broadcast), replace:
```python
    event_text = json.dumps(event)
    for sc in list(runtime.session_clients):
        try:
            await sc.send_text(event_text)
        except Exception:
            pass
```

With:
```python
    from ..services import broadcast_safe
    event_text = json.dumps(event)
    await broadcast_safe(runtime.session_clients, runtime.session_lock, event_text)
```

Do the same replacement in `api_session_rename()`.

**Note:** `runtime.session_lock` does not exist yet. Add it to `WebRuntime.__init__` in `state.py`:

```python
self.session_lock = threading.Lock()
```

And import threading at the top of `state.py` if not already present.

- [ ] **Step 8: Run tests**

```bash
cd tests
python3 test_ops_web_runtime.py -v
python3 test_ops_tx_runtime.py -v
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add mav_gss_lib/web_runtime/services.py mav_gss_lib/web_runtime/api/session.py mav_gss_lib/web_runtime/state.py
git commit -m "Extract broadcast_safe() with lock-aware snapshot iteration"
```

---

### Task 3: Deduplicate RX rendering

**Files:**
- Modify: `mav_gss_lib/web_runtime/services.py:97-106,136-152`

- [ ] **Step 1: Reorder log record and rendering in `broadcast_loop()`**

In `RxService.broadcast_loop()`, the current flow (around lines 136–153) is:

```python
                try:
                    if self.log:
                        self.log.write_jsonl(build_rx_log_record(pkt, version, meta, self.runtime.adapter))
                        self.log.write_packet(pkt, adapter=self.runtime.adapter)
                except Exception as exc:
                    logging.warning("RX log write failed: %s", exc)
                pkt_json = {
                    "num": pkt.pkt_num,
                    ...
                    "_rendering": self._build_rendering(pkt),
                }
```

Replace with:

```python
                record = build_rx_log_record(pkt, version, meta, self.runtime.adapter)
                try:
                    if self.log:
                        self.log.write_jsonl(record)
                        self.log.write_packet(pkt, adapter=self.runtime.adapter)
                except Exception as exc:
                    logging.warning("RX log write failed: %s", exc)
                pkt_json = {
                    "num": pkt.pkt_num,
                    "time": pkt.gs_ts_short,
                    "time_utc": pkt.gs_ts,
                    "frame": pkt.frame_type,
                    "size": len(pkt.raw),
                    "raw_hex": pkt.raw.hex(),
                    "warnings": pkt.warnings,
                    "is_echo": pkt.is_uplink_echo,
                    "is_dup": pkt.is_dup,
                    "is_unknown": pkt.is_unknown,
                    "_rendering": record["_rendering"],
                }
```

- [ ] **Step 2: Delete `_build_rendering()` method**

Remove lines 97–106 (`RxService._build_rendering`). It is no longer called anywhere.

```python
# DELETE this entire method:
    def _build_rendering(self, pkt) -> dict:
        """Build structured rendering-slot data for one packet."""
        from dataclasses import asdict
        adapter = self.runtime.adapter
        return {
            "row": adapter.packet_list_row(pkt),
            "detail_blocks": adapter.packet_detail_blocks(pkt),
            "protocol_blocks": [asdict(b) for b in adapter.protocol_blocks(pkt)],
            "integrity_blocks": [asdict(b) for b in adapter.integrity_blocks(pkt)],
        }
```

- [ ] **Step 3: Verify no other callers of `_build_rendering`**

```bash
grep -r "_build_rendering" mav_gss_lib/
```

Expected: no matches.

- [ ] **Step 4: Run tests**

```bash
cd tests
python3 test_ops_web_runtime.py -v
python3 test_ops_tx_runtime.py -v
python3 test_ops_logging.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add mav_gss_lib/web_runtime/services.py
git commit -m "Compute RX rendering once per packet, reuse for WS and logging"
```

---

### Task 4: TX WebSocket dispatch table

**Files:**
- Create: `mav_gss_lib/web_runtime/tx_actions.py`
- Modify: `mav_gss_lib/web_runtime/tx.py`

- [ ] **Step 1: Create `tx_actions.py` with guards, helpers, and all 13 handlers**

```python
"""TX WebSocket action handlers and dispatch table.

Each handler is a standalone async function: (runtime, msg, websocket) -> None.
Guards are checked by the dispatch loop before calling the handler.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Callable, NamedTuple

from .state import MAX_QUEUE
from .tx_queue import make_delay, validate_mission_cmd

if TYPE_CHECKING:
    from fastapi import WebSocket
    from .state import WebRuntime


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

def mutate_queue_if_idle(runtime: "WebRuntime", fn) -> str | None:
    """Run fn(queue) under send_lock with an atomic idle check.

    Returns an error string if the queue is being sent, else None.
    fn receives the queue list and may mutate it. After fn returns,
    renumber and save are done under the same lock. Broadcasts happen
    after the lock is released by the caller.

    This is the ONLY correct way to mutate the queue from action handlers.
    The dispatch-loop guard (requires_idle) is a fast pre-check; this
    function is the authoritative gate under the lock.
    """
    with runtime.tx.send_lock:
        if runtime.tx.sending["active"]:
            return "cannot modify queue during send"
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
        payload = runtime.adapter.cmd_line_to_payload(line)
        item = validate_mission_cmd(payload, runtime=runtime)
        err = mutate_queue_if_idle(runtime, lambda q: q.append(item))
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
        err = mutate_queue_if_idle(runtime, lambda q: q.append(item))
        if err:
            await send_error(ws, err)
            return
        await runtime.tx.send_queue_update()
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        await send_error(ws, str(exc))


async def handle_delete(runtime: "WebRuntime", msg: dict, ws: "WebSocket") -> None:
    """Delete a queue item by index."""
    idx = msg.get("index")
    def do_delete(q):
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
    def do_guard(q):
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
    def do_reorder(q):
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
    def do_add(q):
        if isinstance(idx, int) and 0 <= idx <= len(q):
            q.insert(idx, item)
        else:
            q.append(item)
    err = mutate_queue_if_idle(runtime, do_add)
    if err:
        await send_error(ws, err)
        return
    await runtime.tx.send_queue_update()


async def handle_edit_delay(runtime: "WebRuntime", msg: dict, ws: "WebSocket") -> None:
    """Update delay_ms on an existing delay item."""
    idx = msg.get("index")
    delay_ms = msg.get("delay_ms")
    def do_edit(q):
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
```

- [ ] **Step 2: Rewrite `tx.py` to use dispatch table**

Replace the entire `ws_tx` function body (keeping imports minimal):

```python
"""TX WebSocket endpoint with dispatch-table action routing."""

from __future__ import annotations

import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .state import MAX_HISTORY, get_runtime
from .runtime import schedule_shutdown_check
from .tx_actions import ACTIONS, send_error
from .security import authorize_websocket

router = APIRouter()


@router.websocket("/ws/tx")
async def ws_tx(websocket: WebSocket):
    runtime = get_runtime(websocket)
    if not await authorize_websocket(websocket):
        return
    await websocket.accept()
    runtime.had_clients = True

    try:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "queue_update",
                    "items": runtime.tx.queue_items_json(),
                    "summary": runtime.tx.queue_summary(),
                    "sending": runtime.tx.sending.copy(),
                }
            )
        )
        await websocket.send_text(json.dumps({"type": "history", "items": runtime.tx.history[-MAX_HISTORY:]}))
    except Exception:
        return

    with runtime.tx.lock:
        runtime.tx.clients.append(websocket)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await send_error(websocket, "invalid JSON")
                continue

            action = msg.get("action", "")
            spec = ACTIONS.get(action)
            if not spec:
                await send_error(websocket, f"unknown action: {action}")
                continue

            for guard in spec.guards:
                err = guard(runtime)
                if err:
                    await send_error(websocket, err)
                    break
            else:
                await spec.handler(runtime, msg, websocket)

    except WebSocketDisconnect:
        pass
    finally:
        with runtime.tx.lock:
            if websocket in runtime.tx.clients:
                runtime.tx.clients.remove(websocket)
            no_tx_clients = len(runtime.tx.clients) == 0
        if no_tx_clients and runtime.tx.sending.get("guarding"):
            runtime.tx.abort.set()
        schedule_shutdown_check(runtime)
```

- [ ] **Step 3: Remove old import from tx.py**

The old `tx.py` imported `from .services import item_to_json`. Check if anything still needs this. If not, remove it. If `app.py` or another module imported `item_to_json` through `tx.py`, update that import to go directly to `tx_queue`.

- [ ] **Step 4: Run tests**

```bash
cd tests
python3 test_ops_tx_runtime.py -v
python3 test_ops_web_runtime.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add mav_gss_lib/web_runtime/tx_actions.py mav_gss_lib/web_runtime/tx.py
git commit -m "Replace TX WebSocket if/elif chain with dispatch table"
```

---

### Task 5: Frontend state split — three independent providers

**Files:**
- Create: `mav_gss_lib/web/src/hooks/RxProvider.tsx`
- Create: `mav_gss_lib/web/src/hooks/TxProvider.tsx`
- Create: `mav_gss_lib/web/src/hooks/SessionProvider.tsx`
- Delete: `mav_gss_lib/web/src/hooks/useAppContext.tsx`
- Modify: `mav_gss_lib/web/src/App.tsx`
- Modify: `mav_gss_lib/web/src/components/MainDashboard.tsx`
- Modify: `mav_gss_lib/web/src/hooks/usePluginServices.ts`

- [ ] **Step 1: Create `RxProvider.tsx`**

```tsx
import { createContext, useContext, type ReactNode } from 'react'
import { useRxSocket } from '@/hooks/useRxSocket'

type RxContextValue = ReturnType<typeof useRxSocket>

const RxContext = createContext<RxContextValue | null>(null)

export function RxProvider({ children }: { children: ReactNode }) {
  const rx = useRxSocket()
  return <RxContext.Provider value={rx}>{children}</RxContext.Provider>
}

export function useRx(): RxContextValue {
  const ctx = useContext(RxContext)
  if (!ctx) throw new Error('useRx must be used within RxProvider')
  return ctx
}
```

- [ ] **Step 2: Create `TxProvider.tsx`**

```tsx
import { createContext, useContext, type ReactNode } from 'react'
import { useTxSocket } from '@/hooks/useTxSocket'

type TxContextValue = ReturnType<typeof useTxSocket>

const TxContext = createContext<TxContextValue | null>(null)

export function TxProvider({ children }: { children: ReactNode }) {
  const tx = useTxSocket()
  return <TxContext.Provider value={tx}>{children}</TxContext.Provider>
}

export function useTx(): TxContextValue {
  const ctx = useContext(TxContext)
  if (!ctx) throw new Error('useTx must be used within TxProvider')
  return ctx
}
```

- [ ] **Step 3: Create `SessionProvider.tsx`**

```tsx
import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'
import { useSession, type SessionState } from '@/hooks/useSession'
import type { GssConfig } from '@/lib/types'

interface SessionContextValue extends SessionState {
  config: GssConfig | null
  setConfig: (c: GssConfig) => void
}

const SessionContext = createContext<SessionContextValue | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const session = useSession()
  const [config, setConfig] = useState<GssConfig | null>(null)

  useEffect(() => {
    fetch('/api/config')
      .then((r) => r.json())
      .then((data: GssConfig) => setConfig(data))
      .catch(() => {})
  }, [])

  return (
    <SessionContext.Provider value={{ ...session, config, setConfig }}>
      {children}
    </SessionContext.Provider>
  )
}

export function useSessionContext(): SessionContextValue {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSessionContext must be used within SessionProvider')
  return ctx
}

export function useConfig() {
  const ctx = useSessionContext()
  return { config: ctx.config, setConfig: ctx.setConfig }
}
```

- [ ] **Step 4: Update `App.tsx` — compose three providers**

Replace the `AppProvider` import and usage:

```tsx
// Before:
import { AppProvider, useAppConfig, useAppRx, useAppSession } from '@/hooks/useAppContext'

// After:
import { SessionProvider, useSessionContext, useConfig } from '@/hooks/SessionProvider'
import { TxProvider } from '@/hooks/TxProvider'
import { RxProvider, useRx } from '@/hooks/RxProvider'
```

Replace the `App` component's provider:

```tsx
// Before:
  return (
    <AppProvider>
      <AppShell />
    </AppProvider>
  )

// After:
  return (
    <SessionProvider>
      <TxProvider>
        <RxProvider>
          <AppShell />
        </RxProvider>
      </TxProvider>
    </SessionProvider>
  )
```

Update `AppShell`:
```tsx
// Before:
  const { config, setConfig } = useAppConfig()

// After:
  const { config, setConfig } = useConfig()
```

Update `PluginPageShell`:
```tsx
// Before:
  const rx = useAppRx()
  const session = useAppSession()

// After:
  const rx = useRx()
  const session = useSessionContext()
```

- [ ] **Step 5: Update `MainDashboard.tsx`**

```tsx
// Before:
import { useAppRx, useAppTx, useAppSession } from '@/hooks/useAppContext'
...
  const rx = useAppRx()
  ...
  const tx = useAppTx()
  const session = useAppSession()

// After:
import { useRx } from '@/hooks/RxProvider'
import { useTx } from '@/hooks/TxProvider'
import { useSessionContext } from '@/hooks/SessionProvider'
...
  const rx = useRx()
  ...
  const tx = useTx()
  const session = useSessionContext()
```

- [ ] **Step 6: Update `usePluginServices.ts`**

```tsx
// Before:
import { useAppRx, useAppTx, useAppSession, useAppConfig } from '@/hooks/useAppContext'
...
  const rx = useAppRx()
  const tx = useAppTx()
  const session = useAppSession()
  const { config } = useAppConfig()

// After:
import { useRx } from '@/hooks/RxProvider'
import { useTx } from '@/hooks/TxProvider'
import { useSessionContext, useConfig } from '@/hooks/SessionProvider'
...
  const rx = useRx()
  const tx = useTx()
  const session = useSessionContext()
  const { config } = useConfig()
```

- [ ] **Step 7: Delete `useAppContext.tsx`**

```bash
rm mav_gss_lib/web/src/hooks/useAppContext.tsx
```

- [ ] **Step 8: Verify no remaining references**

```bash
grep -r "useAppContext\|useAppRx\|useAppTx\|useAppSession\|useAppConfig\|AppProvider" mav_gss_lib/web/src/
```

Expected: no matches.

- [ ] **Step 9: Build and lint**

```bash
cd mav_gss_lib/web
npm run build
npm run lint
```

Expected: no TypeScript errors, no lint errors.

- [ ] **Step 10: Commit (source only first)**

```bash
git add mav_gss_lib/web/src/
git rm mav_gss_lib/web/src/hooks/useAppContext.tsx
git commit -m "Split AppProvider into RxProvider, TxProvider, SessionProvider"
```

- [ ] **Step 11: Commit dist**

```bash
git add mav_gss_lib/web/dist/
git commit -m "Rebuild dist after frontend state split"
```

---

### Task 6: TX contract alignment

**Files:**
- Modify: `mav_gss_lib/web_runtime/tx_actions.py` (add contract docs)
- Modify: `mav_gss_lib/web/src/hooks/useTxSocket.ts` (fix drift, add contract types)

- [ ] **Step 1: Audit all 13 actions**

Compare each action's frontend send shape (`useTxSocket.ts`) against the backend handler's `msg.get()` keys (`tx_actions.py`).

| Action | Frontend sends | Backend reads | Match? |
|--------|---------------|---------------|--------|
| `queue` | `{action, input}` | `msg.get("input")` | ✓ |
| `queue_mission_cmd` | `{action, payload}` | `msg.get("payload")` | ✓ |
| `delete` | `{action, index}` | `msg.get("index")` | ✓ |
| `clear` | `{action}` | — | ✓ |
| `undo` | `{action}` | — | ✓ |
| `guard` | `{action, index}` | `msg.get("index")` | ✓ |
| `reorder` | `{action, order}` | `msg.get("order")` | ✓ |
| `add_delay` | `{action, after_index, delay_ms}` | `msg.get("index"), msg.get("delay_ms")` | **MISMATCH: `after_index` vs `index`** |
| `edit_delay` | `{action, index, delay_ms}` | `msg.get("index"), msg.get("delay_ms")` | ✓ |
| `send` | `{action}` | — | ✓ |
| `abort` | `{action}` | — | ✓ |
| `guard_approve` | `{action}` | — | ✓ |
| `guard_reject` | `{action}` | — | ✓ |

- [ ] **Step 2: Fix the `add_delay` mismatch**

The frontend sends `after_index` but the backend reads `index`. The backend is the source of truth (it uses `index` for insert position). Update the frontend:

In `useTxSocket.ts`, the `addDelay` callback (line 132–135):

```typescript
// Before:
  const addDelay = useCallback((ms: number) => {
    const q = queueRef.current
    send('add_delay', { after_index: q.length - 1, delay_ms: ms })
  }, [send])

// After:
  const addDelay = useCallback((ms: number) => {
    const q = queueRef.current
    send('add_delay', { index: q.length, delay_ms: ms })
  }, [send])
```

Note: changed from `after_index: q.length - 1` (insert after last) to `index: q.length` (insert at end), which matches the backend's `queue.insert(idx, item)` / `queue.append(item)` logic.

- [ ] **Step 3: Add contract comment to `tx_actions.py`**

Add at the top of the file, after the module docstring:

```python
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
```

- [ ] **Step 4: Build and lint frontend**

```bash
cd mav_gss_lib/web
npm run build
npm run lint
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add mav_gss_lib/web_runtime/tx_actions.py mav_gss_lib/web/src/hooks/useTxSocket.ts
git commit -m "Align TX WebSocket contract and document action shapes"
```

- [ ] **Step 6: Commit dist**

```bash
git add mav_gss_lib/web/dist/
git commit -m "Rebuild dist after TX contract alignment"
```

---

## Final Verification

After all tasks are complete:

- [ ] **Run full backend test suite**

```bash
cd tests
python3 test_ops_web_runtime.py -v
python3 test_ops_tx_runtime.py -v
python3 test_ops_protocol_core.py -v
python3 test_ops_logging.py -v
python3 test_tx_plugin.py -v
```

- [ ] **Run frontend build + lint**

```bash
cd mav_gss_lib/web
npm run build
npm run lint
```

- [ ] **Manual smoke test**

Start `MAV_WEB.py`, open the dashboard. Verify:
- RX panel loads, columns display
- TX panel loads, can queue/delete/reorder/clear commands
- Send queue with a guard item — guard confirm dialog appears
- Config sidebar opens, saves, closes
- Log viewer opens, lists sessions, displays entries
- Session rename works
- New session works

- [ ] **Frontend rerender check (Task 5 acceptance criterion)**

Open React DevTools Profiler. During live RX traffic:
- TxPanel should show zero renders (unless TX state changes)
- SessionBar should show zero renders (unless session state changes)
