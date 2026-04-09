# Control Plane Cleanup — Design Spec

**Date:** 2026-04-08
**Scope:** Backend control plane split, RX rendering deduplication, frontend state split, TX contract alignment
**Out of scope:** Log replay indexing, mission adapter contract, wire_format.py, bundle size, existing virtualization/lazy-loading

---

## 1. Backend Control Plane Split

### 1A. Split api.py into `api/` package

**Current state:** `web_runtime/api.py` (663 lines, 19 endpoints) mixes config, schema, queue import/export, log browsing, and session lifecycle in one file.

**Target structure:**

```
web_runtime/api/
├── __init__.py          # re-exports `router` (includes all sub-routers)
├── config.py            # GET/PUT /api/config, GET /api/status, GET /api/selfcheck
├── schema.py            # GET /api/schema, GET /api/columns, GET /api/tx-columns, GET /api/tx/capabilities
├── queue_io.py          # GET /api/import-files, GET /api/import/{}/preview, POST /api/import/{}, POST /api/export-queue
├── logs.py              # GET /api/logs, GET /api/logs/{session_id}
├── session.py           # GET /api/session, POST /api/session/new, PATCH /api/session, deprecated aliases (all existing endpoints, relocated)
```

**Routing:** Each module defines its own `APIRouter`. `__init__.py` creates a parent router that includes all sub-routers. `app.py` continues to mount a single `api.router`.

**Shared state access:** All route modules receive `WebRuntime` via `request.app.state.runtime` (existing pattern). No new dependency injection needed.

**Shared helpers:** `parse_replay_entry()` stays in `logs.py` (only caller). `_session_info()` moves to `session.py`. `deep_merge()` stays in `runtime.py` (already there).

### 1B. TX WebSocket dispatch table

**Current state:** `web_runtime/tx.py` (233 lines) has a 13-branch if/elif chain with repeated guards:
- `sending()` check: 10 occurrences
- Queue-full check: 3 occurrences
- `renumber + save + broadcast`: 8 occurrences

**Target structure:**

```python
# tx.py — slimmed to ~60 lines: WS endpoint + dispatch setup

# tx_actions.py — ~180 lines: action handlers + guard wrappers

# Guards (applied via dispatch table metadata, not decorators):
def requires_idle(runtime) -> str | None:
    """Returns error string if queue is being sent, else None."""

def requires_space(runtime) -> str | None:
    """Returns error string if queue is full, else None."""

# Post-action helper:
async def persist_and_broadcast(runtime):
    """renumber → save → send_queue_update"""

# Dispatch table:
ACTIONS: dict[str, ActionSpec] = {
    "queue":          ActionSpec(handler=handle_queue,          guards=[requires_idle, requires_space]),
    "queue_mission_cmd": ActionSpec(handler=handle_queue_mission_cmd, guards=[requires_idle, requires_space]),
    "delete":         ActionSpec(handler=handle_delete,         guards=[requires_idle]),
    "clear":          ActionSpec(handler=handle_clear,          guards=[requires_idle]),
    "undo":           ActionSpec(handler=handle_undo,           guards=[requires_idle]),
    "guard":          ActionSpec(handler=handle_guard,          guards=[requires_idle]),
    "reorder":        ActionSpec(handler=handle_reorder,        guards=[requires_idle]),
    "add_delay":      ActionSpec(handler=handle_add_delay,      guards=[requires_idle, requires_space]),
    "edit_delay":     ActionSpec(handler=handle_edit_delay,     guards=[requires_idle]),
    "send":           ActionSpec(handler=handle_send,           guards=[]),
    "abort":          ActionSpec(handler=handle_abort,          guards=[]),
    "guard_approve":  ActionSpec(handler=handle_guard_approve,  guards=[]),
    "guard_reject":   ActionSpec(handler=handle_guard_reject,   guards=[]),
}

# ActionSpec is a simple NamedTuple or dataclass:
class ActionSpec(NamedTuple):
    handler: Callable  # async (runtime, data, websocket) -> None
    guards: list[Callable]  # each returns error string or None
```

**Dispatch loop in tx.py:**

```python
async def ws_tx(websocket, runtime):
    # ... connect, replay queue/history ...
    async for raw in websocket.iter_text():
        msg = json.loads(raw)
        action = msg.get("action")
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
```

**Handler signature:** Each handler is `async def handle_X(runtime: WebRuntime, msg: dict, websocket: WebSocket) -> None`. Handlers that mutate the queue call `persist_and_broadcast(runtime)` at the end.

### 1C. Extract `broadcast_safe()` from services.py

**Current state:** Dead-client cleanup pattern repeated 6+ times across RxService and TxService:

```python
dead = []
for ws in self.clients:
    try:
        await ws.send_text(payload)
    except Exception:
        dead.append(ws)
for ws in dead:
    self.clients.remove(ws)
```

**Target:** Single async helper at the top of `services.py` (used by both RxService and TxService, and importable by api/session.py).

**Concurrency contract:** The current code uses `self.lock` (a `threading.Lock`) around all client list mutations in both RxService and TxService. The helper must preserve this. It becomes an instance method on each service (or accepts the lock), not a bare function:

```python
async def broadcast_safe(clients: list[WebSocket], lock: threading.Lock, payload: str) -> None:
    """Send payload to all clients, removing dead connections under lock."""
    dead = []
    for ws in clients:
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

The lock is only held for the removal phase (fast), not during sends (slow/blocking). This matches the current pattern where sends happen outside the lock and removals happen inside it.

Replace all 6 occurrences in `RxService.broadcast()`, `RxService.broadcast_loop()` (3 sites), `TxService.broadcast()`, and the session rename broadcast in `api.py` (which uses `runtime.session_clients` — pass the appropriate lock or add one for session clients).

---

## 2. Deduplicate RX Rendering

**Current state:** `_rendering` is built twice per packet:
- `RxService._build_rendering()` (services.py:97-106) — for WebSocket broadcast
- `build_rx_log_record()` (parsing.py:201-207) — for JSONL logging

Both call the same 4 adapter methods. The only difference: `build_rx_log_record` pre-converts `ProtocolBlock`/`IntegrityBlock` dataclasses to dicts before embedding.

**Target:** Build once, reuse everywhere.

**Change:** In `RxService.broadcast_loop()`, the flow currently is:

```
packet arrives → _build_rendering(pkt) → broadcast to WS
                → build_rx_log_record(pkt) → log to JSONL (calls adapter again)
```

New flow:

```
packet arrives → build_rx_log_record(pkt) → returns record with _rendering (dict form)
              → broadcast record["_rendering"] to WS
              → log full record to JSONL
```

**Concrete changes:**

1. **`parsing.py` `build_rx_log_record()`** — no change needed, it already builds `_rendering` with dict-converted blocks.

2. **`services.py` `RxService.broadcast_loop()`** — replace the separate `_build_rendering()` call with reuse from the log record:
   ```python
   # Before:
   rendering = self._build_rendering(pkt)
   record = build_rx_log_record(pkt, ...)
   # broadcast rendering to WS
   # log record to JSONL

   # After:
   record = build_rx_log_record(pkt, ...)
   rendering = record["_rendering"]
   # broadcast rendering to WS
   # log record to JSONL
   ```

3. **Delete `RxService._build_rendering()`** — no longer needed.

**Constraint:** The `_rendering` dict format must remain identical for WebSocket consumers. Both current paths produce the same keys (`row`, `detail_blocks`, `protocol_blocks`, `integrity_blocks`), so this is safe.

---

## 3. Frontend State Split

### Current architecture

```
AppProvider (single context)
├── useRxSocket  → packets, stats, columns, status, replayMode, ...
├── useTxSocket  → queue, summary, history, sendProgress, guardConfirm, error, ...
├── useSession   → tag, startedAt, sessionId, isTrafficActive, ...
└── config       → GssConfig | null, setConfig
```

All consumers rerender when any sub-object changes. RX flushes every 50ms during live traffic, causing TX and session consumers to rerender unnecessarily.

**Acceptance criterion:** After the split, components that consume only `useTx()` or `useSession()` must not rerender when RX packets flush. Verify with React DevTools Profiler: during live RX traffic, TxPanel and SessionBar should show zero renders unless their own state changes.

### Target architecture

```
RxProvider (context 1)
└── useRxSocket  → same exports

TxProvider (context 2)
└── useTxSocket  → same exports

SessionProvider (context 3)
└── useSession   → same exports
└── config, setConfig  → lives here (session-adjacent, rarely changes)

// Composition in App.tsx or MainDashboard:
<SessionProvider>
  <TxProvider>
    <RxProvider>
      {children}
    </RxProvider>
  </TxProvider>
</SessionProvider>
```

### Consumer hooks

```typescript
// New dedicated hooks (replace useAppRx, useAppTx, useAppSession, useAppConfig):
export function useRx(): RxContextValue    // from RxProvider
export function useTx(): TxContextValue    // from TxProvider
export function useSession(): SessionContextValue  // from SessionProvider
export function useConfig(): { config: GssConfig | null; setConfig: (c: GssConfig) => void }
```

### Migration

- `useAppRx()` → `useRx()`
- `useAppTx()` → `useTx()`
- `useAppSession()` → `useSession()`
- `useAppConfig()` → `useConfig()`
- `useAppContext()` — delete (no consumer should need all four at once)

### File changes

| File | Change |
|---|---|
| `hooks/useAppContext.tsx` | Delete entirely |
| `hooks/RxProvider.tsx` | New — wraps useRxSocket in its own context |
| `hooks/TxProvider.tsx` | New — wraps useTxSocket in its own context |
| `hooks/SessionProvider.tsx` | New — wraps useSession + config in its own context |
| `App.tsx` | Compose three providers |
| `MainDashboard.tsx` | Update imports: `useAppRx()` → `useRx()`, etc. |
| All consumers of `useAppRx/Tx/Session/Config` | Update imports |

### Session ↔ RX coordination

`sessionResetGen` is currently a weak sync between `useRxSocket` and `useSession` (both listen to the same WS broadcast independently). This continues to work with separate providers — no shared state needed.

---

## 4. TX Contract Alignment

**Goal:** Ensure WebSocket action names, payload shapes, and response types are consistent between `useTxSocket.ts` and the backend dispatch table.

**Approach:**

1. Audit all 13 actions: compare the `action` string and payload keys sent by `useTxSocket.ts` against what the backend handler expects.
2. Fix any actual mismatches (names, key casing, missing fields).
3. Add a contract comment block in `tx_actions.py` documenting each action's request/response shape.
4. Add a matching TypeScript type block in `useTxSocket.ts` (or a shared `tx-contract.ts`) documenting the same shapes from the frontend perspective.

**Known items to check:**
- `add_delay` payload shape (index field naming)
- `guard` vs `guard_approve` / `guard_reject` naming consistency
- `queue` vs `queue_mission_cmd` payload overlap

---

## Dependency Order

```
1A (api/ package split) ──── standalone (api.py only)
        ↓
1C (broadcast_safe) ──────── sequential after 1A (both touch api session broadcast)
        ↓
2  (RX rendering dedup) ──── sequential after 1C (both touch services.py)

1B (tx dispatch table) ───── parallel with 1A/1C/2 (tx.py + new tx_actions.py only)

3  (frontend state split) ── independent of all backend changes

4  (TX contract alignment) ─ after 1B (documents the dispatch table)
```

**File ownership constraints:**
- `1A` owns `api.py` → `api/` migration
- `1C` owns `services.py` broadcast patterns + imports the helper into `api/session.py` (created by 1A)
- `2` owns `services.py` rendering path + `parsing.py` (after 1C is done with services.py)
- `1B` owns `tx.py` + new `tx_actions.py` — no overlap with other items

Each item is independently committable and testable.

---

## Verification

After each item:
- Backend (control plane): `python3 tests/test_ops_web_runtime.py`, `python3 tests/test_ops_tx_runtime.py` — primary regression suites for this work
- Backend (protocol/logging): `python3 tests/test_ops_protocol_core.py`, `test_ops_logging.py`, `test_tx_plugin.py` — confirm no side-effect breakage
- Frontend: `npm run build` (TypeScript + bundle check), `npm run lint`
- Manual: start `MAV_WEB.py`, verify dashboard loads, RX/TX panels render, queue operations work
- Item 3 specifically: React DevTools Profiler check during live RX traffic (see acceptance criterion above)
