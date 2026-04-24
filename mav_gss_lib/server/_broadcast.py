"""
mav_gss_lib.server._broadcast -- Shared WebSocket broadcast helper

Used by RxService, TxService, and api/session.py.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import threading


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
