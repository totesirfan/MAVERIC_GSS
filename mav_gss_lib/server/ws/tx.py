"""TX WebSocket endpoint — /ws/tx with dispatch-table action routing.

On connect, replays the current queue + send-state snapshot and recent
send history. Thereafter each inbound message is dispatched via
``tx.actions.ACTIONS`` — guards run first, then the handler; unknown
actions return a structured error. See ``tx/actions.py`` for the full
action/event contract.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..state import MAX_HISTORY, get_runtime
from ..shutdown import schedule_shutdown_check
from ..tx.actions import ACTIONS, send_error
from ..security import authorize_websocket

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
