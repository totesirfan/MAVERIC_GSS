"""WebSocket handlers for the server.

Each module exports a FastAPI `router` that app.py mounts:

    rx.py        — /ws/rx        (inbound packet fan-out)
    tx.py        — /ws/tx        (outbound command queue)
    session.py   — /ws/session   (session id lifecycle)
    preflight.py — /ws/preflight (preflight check broadcast)
    update.py    — update traffic over the preflight broadcast

Author:  Irfan Annuar - USC ISI SERC
"""
