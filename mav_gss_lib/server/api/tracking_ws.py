"""WebSocket endpoint that streams Doppler corrections + tracking status.

Mounted by app.create_app via register_tracking_ws so the broadcaster and
tracking service references stay scoped to the runtime that owns them."""

from __future__ import annotations

from typing import Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from mav_gss_lib.server.tracking._tick import DopplerBroadcaster
from mav_gss_lib.server.tracking.service import TrackingService


def register_tracking_ws(
    app: FastAPI,
    get_broadcaster: Callable[[], DopplerBroadcaster],
    get_tracking: Callable[[], TrackingService],
) -> None:
    @app.websocket("/ws/tracking")
    async def ws_tracking(websocket: WebSocket) -> None:
        await websocket.accept()
        broadcaster = get_broadcaster()
        tracking = get_tracking()
        try:
            await websocket.send_json({"type": "status", **tracking.status()})
            async for message in broadcaster.subscribe():
                await websocket.send_json(message)
        except WebSocketDisconnect:
            return


__all__ = ["register_tracking_ws"]
