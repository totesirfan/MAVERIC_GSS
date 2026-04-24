"""
mav_gss_lib.server.api.identity -- Identity Route

Returns the operator, host, and station captured at runtime startup.
Local-only — no auth gate (matches /api/status).

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..state import get_runtime

router = APIRouter()


@router.get("/api/identity")
async def api_identity(request: Request) -> dict[str, Any]:
    runtime = get_runtime(request)
    return {
        "operator": runtime.operator,
        "host": runtime.host,
        "station": runtime.station,
    }
