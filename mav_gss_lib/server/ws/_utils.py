"""Small helpers shared across WebSocket endpoint handlers.

Author:  Irfan Annuar - USC ISI SERC
"""
from __future__ import annotations

import json

from fastapi import WebSocket


async def send_phase_fail(ws: WebSocket, phase: str, detail: str) -> None:
    """Emit an update_phase failure event. Swallow send errors.

    Matches the prevailing style in preflight._broadcast and the four
    other WS-send sites that tolerate disconnected clients mid-send.
    """
    try:
        await ws.send_text(json.dumps({
            "type": "update_phase",
            "phase": phase,
            "status": "fail",
            "detail": detail,
        }))
    except Exception:
        pass
