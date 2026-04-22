from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from mav_gss_lib.web_runtime.state import get_runtime


def get_telemetry_router() -> APIRouter:
    router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

    @router.delete("/{domain}/snapshot")
    async def clear_snapshot(domain: str, request: Request):
        runtime = get_runtime(request)
        msg = runtime.telemetry.clear(domain)
        if msg is None:
            raise HTTPException(status_code=404, detail=f"unknown domain: {domain}")
        await runtime.rx.broadcast(msg)
        return JSONResponse({"ok": True})

    @router.get("/{domain}/catalog")
    async def get_domain_catalog(domain: str, request: Request):
        """Return whatever catalog the mission registered for this domain.

        The platform does not define the catalog shape; it is opaque
        mission data. 404 if the domain is unknown OR if the mission
        registered the domain without a catalog callable.
        """
        runtime = get_runtime(request)
        if not runtime.telemetry.has_domain(domain):
            raise HTTPException(status_code=404, detail=f"unknown domain: {domain}")
        catalog = runtime.telemetry.get_catalog(domain)
        if catalog is None:
            raise HTTPException(status_code=404, detail=f"no catalog for domain: {domain}")
        return JSONResponse(catalog)

    return router
