"""Auth and origin checks for the web runtime."""

from __future__ import annotations

from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse

from .state import PORT, get_runtime


def require_api_token(request: Request) -> JSONResponse | None:
    runtime = get_runtime(request)
    if request.headers.get("x-gss-token", "") == runtime.session_token:
        return None
    return JSONResponse(status_code=403, content={"error": "invalid session token"})


def origin_allowed(origin: str | None, host: str | None) -> bool:
    if not origin:
        return True
    if not host:
        return False
    allowed = {
        f"http://{host}",
        f"https://{host}",
        f"http://127.0.0.1:{PORT}",
        f"http://localhost:{PORT}",
        f"https://127.0.0.1:{PORT}",
        f"https://localhost:{PORT}",
    }
    return origin in allowed


async def authorize_websocket(websocket: WebSocket) -> bool:
    runtime = get_runtime(websocket)
    token = websocket.query_params.get("token", "")
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if token != runtime.session_token or not origin_allowed(origin, host):
        await websocket.close(code=1008)
        return False
    return True
