"""FastAPI router for MAVERIC mission identity.

Mounted by ``mission.py::build(ctx)`` under HttpOps. Surfaces the codec's
node / ptype / gs_node tables (parsed from ``mission.yml extensions``)
to mission-side frontend plugins (TX builder dropdown, packet badge
labels) without leaking mission-specific identity into the platform's
``/api/config`` endpoint. The mission database is the source of truth;
this route is read-only.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from mav_gss_lib.missions.maveric.codec import MaverPacketCodec
from mav_gss_lib.platform.spec import Mission


def get_identity_router(codec: MaverPacketCodec, mission: Mission) -> APIRouter:
    router = APIRouter(prefix="/api/plugins/maveric", tags=["maveric"])

    @router.get("/identity")
    async def maveric_identity() -> JSONResponse:
        ext: dict[str, Any] = dict(getattr(mission, "extensions", {}) or {})
        return JSONResponse({
            "mission_name":      getattr(mission, "name", None) or "",
            "nodes":             ext.get("nodes", {}),
            "ptypes":            ext.get("ptypes", {}),
            "node_descriptions": ext.get("node_descriptions", {}),
            "gs_node":           codec.gs_node_name or ext.get("gs_node"),
        })

    return router
