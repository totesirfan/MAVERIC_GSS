"""Session WebSocket endpoint — lightweight session event stream.

Sends session_new, session_renamed, and periodic traffic_status events
to connected clients. No packet data, no columns, no backlog.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .state import get_runtime
from .runtime import schedule_shutdown_check
from .security import authorize_websocket

router = APIRouter()


@router.websocket("/ws/session")
async def ws_session(websocket: WebSocket):
    runtime = get_runtime(websocket)
    if not await authorize_websocket(websocket):
        return
    await websocket.accept()
    runtime.had_clients = True

    # Send current session info on connect
    session_info = {
        "type": "session_info",
        "session_id": runtime.session.session_id,
        "tag": runtime.session.tag,
        "started_at": runtime.session.started_at,
        "generation": runtime.session.generation,
    }
    await websocket.send_text(json.dumps(session_info))

    # Send immediate traffic status on connect
    traffic_active = (
        runtime.rx.last_rx_at > 0
        and (time.time() - runtime.rx.last_rx_at) < 10.0
    )
    await websocket.send_text(json.dumps({
        "type": "traffic_status",
        "active": traffic_active,
    }))

    # Register in session_clients
    runtime.session_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in runtime.session_clients:
            runtime.session_clients.remove(websocket)
        schedule_shutdown_check(runtime)
