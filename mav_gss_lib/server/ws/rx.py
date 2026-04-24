"""RX WebSocket endpoint — /ws/rx packet fan-out.

On connect, sends mission packet-column definitions, replays the in-memory
packet backlog, and emits any mission-plugin replay events. Thereafter the
client receives live packet/status/telemetry frames published by
``RxService.broadcast_loop``.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from mav_gss_lib.platform import collect_connect_events

from ..state import get_runtime
from ..shutdown import schedule_shutdown_check
from ..security import authorize_websocket

router = APIRouter()

@router.websocket("/ws/rx")
async def ws_rx(websocket: WebSocket) -> None:
    runtime = get_runtime(websocket)
    if not await authorize_websocket(websocket):
        return
    await websocket.accept()
    runtime.had_clients = True
    # Send column definitions before any packet data
    columns = [column.to_json() for column in runtime.mission.ui.packet_columns()]
    await websocket.send_text(json.dumps({"type": "columns", "data": columns}))
    for pkt_json in list(runtime.rx.packets):
        try:
            await websocket.send_text(json.dumps({"type": "packet", "data": pkt_json}))
        except Exception:
            return

    for msg in collect_connect_events(runtime.mission):
        await websocket.send_text(json.dumps(msg))

    with runtime.rx.lock:
        runtime.rx.clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        with runtime.rx.lock:
            if websocket in runtime.rx.clients:
                runtime.rx.clients.remove(websocket)
        schedule_shutdown_check(runtime)
