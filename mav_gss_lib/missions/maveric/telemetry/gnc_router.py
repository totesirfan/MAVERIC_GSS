"""FastAPI router for the GNC register snapshot store.

Mounted automatically by `mav_gss_lib.missions.maveric.get_plugin_routers`
when the adapter carries a `gnc_store`. The dashboard fetches the
snapshot on initial mount AND on every session reset so stored values
appear immediately instead of waiting for the next RX packet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mav_gss_lib.missions.maveric.telemetry.gnc_registers import GncRegisterStore


def get_gnc_router(store: "GncRegisterStore"):
    from fastapi import APIRouter, Request
    from fastapi.responses import JSONResponse

    from mav_gss_lib.missions.maveric.telemetry.gnc_registers import REGISTERS
    from mav_gss_lib.web_runtime.state import get_runtime

    router = APIRouter(prefix="/api/plugins/gnc", tags=["gnc"])

    @router.get("/snapshot")
    async def gnc_snapshot():
        """Return every stored register snapshot keyed by register name."""
        return JSONResponse(store.get_all())

    @router.delete("/snapshot")
    async def clear_gnc_snapshot(request: Request):
        """Operator action: wipe the persisted snapshot.

        Broadcasts `gnc_snapshot_cleared` on /ws/rx so peer tabs reset
        their in-memory state. Broadcasting after the disk clear also
        eliminates the race where a live `gnc_register_update` arriving
        between the DELETE and the local setState would otherwise be
        silently overwritten by the clear.
        """
        store.clear()
        runtime = get_runtime(request)
        await runtime.rx.broadcast({"type": "gnc_snapshot_cleared"})
        return JSONResponse({"ok": True})

    @router.get("/catalog")
    async def gnc_catalog():
        """Return every register definition in the catalog.

        The dashboard's Registers tab hydrates from this list — one row
        per catalog entry — and overlays live snapshot values on top.
        Sorted by (module, register) so the table renders in a stable
        order without the client having to re-sort each render.
        """
        sorted_keys = sorted(REGISTERS.keys())
        return JSONResponse([
            {
                "module":   module,
                "register": register,
                "name":     REGISTERS[(module, register)].name,
                "type":     REGISTERS[(module, register)].type,
                "unit":     REGISTERS[(module, register)].unit,
                "notes":    REGISTERS[(module, register)].notes,
            }
            for module, register in sorted_keys
        ])

    return router
