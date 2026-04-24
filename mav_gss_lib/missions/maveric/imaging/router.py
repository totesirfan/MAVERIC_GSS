"""FastAPI router for the MAVERIC imaging plugin.

Mounted by `mission.py::build(ctx)` under HttpOps. Endpoints expose the
`ImageAssembler` state (paired status, file list, chunk progress,
preview) and allow deletion.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter

from mav_gss_lib.missions.maveric.imaging.assembler import ImageAssembler


def get_imaging_router(
    assembler: "ImageAssembler",
    config_accessor: Callable[[], dict[str, Any] | None] | None = None,
) -> APIRouter:
    """Build the imaging FastAPI router.

    ``config_accessor`` is a zero-arg callable that returns the current
    mission config dict. Passing a callable rather than a dict snapshot
    lets the router respect live config edits via /api/config.
    """
    from fastapi.responses import FileResponse, JSONResponse

    router = APIRouter(prefix="/api/plugins/imaging", tags=["imaging"])

    def _thumb_prefix() -> str:
        if config_accessor is None:
            return ""
        cfg = config_accessor() or {}
        return (cfg.get("imaging") or {}).get("thumb_prefix", "") or ""

    @router.get("/status")
    async def imaging_status():
        return JSONResponse(assembler.paired_status(_thumb_prefix()))

    @router.get("/files")
    async def imaging_files():
        return JSONResponse({"files": assembler.list_files()})

    @router.get("/chunks/{filename:path}")
    async def imaging_chunks(filename: str) -> JSONResponse:
        return JSONResponse({"filename": filename, "chunks": assembler.get_chunks(filename)})

    @router.delete("/file/{filename:path}")
    async def imaging_delete(filename: str) -> JSONResponse:
        assembler.delete_file(filename)
        return JSONResponse({"ok": True, "filename": filename})

    @router.get("/preview/{filename:path}", response_model=None)
    async def imaging_preview(filename: str) -> JSONResponse | FileResponse:
        path = Path(assembler.output_dir) / filename
        if not path.is_file():
            return JSONResponse({"error": "not found"}, status_code=404)
        stat = path.stat()
        if stat.st_size == 0:
            return JSONResponse({"error": "no image data yet"}, status_code=404)
        etag = f'"{stat.st_mtime_ns}-{stat.st_size}"'
        return FileResponse(
            path,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "no-cache",
                "ETag": etag,
            },
        )

    return router
