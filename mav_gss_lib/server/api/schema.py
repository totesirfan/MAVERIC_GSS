"""
mav_gss_lib.server.api.schema -- Schema / Column Routes

Endpoints: api_schema, api_columns, api_tx_capabilities, api_tx_columns

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..state import get_runtime

router = APIRouter()


@router.get("/api/schema")
async def api_schema(request: Request):
    runtime = get_runtime(request)
    return runtime.mission.commands.schema() if runtime.mission.commands is not None else {}


@router.get("/api/columns")
async def api_columns(request: Request):
    """Return mission-provided column definitions for packet list rendering.

    Minimal enabler: same data as sent over /ws/rx on connect, exposed via
    REST so the log viewer can render rows from _rendering.row.
    """
    runtime = get_runtime(request)
    return [column.to_json() for column in runtime.mission.ui.packet_columns()]


@router.get("/api/tx/capabilities")
async def api_tx_capabilities(request: Request):
    """Return TX capabilities for the loaded mission."""
    runtime = get_runtime(request)
    return {"mission_commands": runtime.mission.commands is not None}


@router.get("/api/tx-columns")
async def api_tx_columns(request: Request):
    """Return mission-provided column definitions for TX queue/history rendering."""
    runtime = get_runtime(request)
    if runtime.mission.commands is None:
        return []
    return [column.to_json() for column in runtime.mission.commands.tx_columns()]
