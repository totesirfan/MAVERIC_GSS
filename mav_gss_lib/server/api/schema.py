"""
mav_gss_lib.server.api.schema -- Schema / Column Routes

Endpoints: api_schema, api_tx_capabilities, api_tx_columns, api_rx_columns

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request

from mav_gss_lib.platform.contract.commands import CommandSchemaItem

from ..state import get_runtime

router = APIRouter()


# response_model=None is REQUIRED here. Without it, FastAPI promotes
# the return annotation to a Pydantic response model and would strip
# every key not declared on `CommandSchemaItem` — including the MAVERIC
# extension fields (`dest`, `echo`, `ptype`, `nodes`) that the frontend
# plugin needs. Verified against FastAPI 0.135.3 / Pydantic 2.12.5
# (TypedDict gets coerced to a BaseModel via `create_model_field`,
# which filters values to the declared schema). The annotation is
# kept for static analysis (mypy / IDE); `response_model=None` makes
# runtime serialization pure JSON pass-through.
@router.get("/api/schema", response_model=None)
async def api_schema(request: Request) -> Mapping[str, CommandSchemaItem]:
    runtime = get_runtime(request)
    return runtime.mission.commands.schema() if runtime.mission.commands is not None else {}


@router.get("/api/tx/capabilities")
async def api_tx_capabilities(request: Request) -> dict[str, Any]:
    """Return TX capabilities for the loaded mission."""
    runtime = get_runtime(request)
    return {"mission_commands": runtime.mission.commands is not None}


@router.get("/api/tx-columns")
async def api_tx_columns(request: Request) -> list[dict[str, Any]]:
    """Return declarative TX column definitions from mission.yml."""
    runtime = get_runtime(request)
    spec_root = getattr(runtime.mission, "spec_root", None)
    ui = getattr(spec_root, "ui", None) if spec_root is not None else None
    if ui is None:
        return []
    return [column.to_json() for column in ui.tx_columns]


@router.get("/api/rx-columns")
async def api_rx_columns(request: Request) -> list[dict[str, Any]]:
    """Return declarative RX column definitions from mission.yml.

    Each entry is `{id, label, path, width?, align?, flex?, toggle?, badge?}`.
    Empty list when the mission omits the ``ui.rx_columns`` block — the
    frontend falls through to platform-shell columns only.
    """
    runtime = get_runtime(request)
    spec_root = getattr(runtime.mission, "spec_root", None)
    ui = getattr(spec_root, "ui", None) if spec_root is not None else None
    if ui is None:
        return []
    return [column.to_json() for column in ui.rx_columns]
