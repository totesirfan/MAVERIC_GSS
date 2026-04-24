"""
mav_gss_lib.server.api.queue_io -- Queue Import / Export Routes

Endpoints: list_import_files, preview_import, import_file, export_queue

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..state import MAX_QUEUE, get_runtime
from ..tx.queue import parse_import_file, sanitize_queue_items, item_to_json
from ..security import require_api_token

router = APIRouter()


@router.get("/api/import-files")
async def list_import_files(request: Request) -> list[dict[str, Any]]:
    runtime = get_runtime(request)
    import_dir = runtime.generated_commands_dir()
    if not import_dir.exists():
        return []
    files = []
    for path in sorted(import_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        files.append({"name": path.name, "path": str(path), "size": path.stat().st_size})
    return files


@router.get("/api/import/{filename}/preview", response_model=None)
async def preview_import(filename: str, request: Request) -> dict[str, Any] | JSONResponse:
    runtime = get_runtime(request)
    import_dir = runtime.generated_commands_dir().resolve()
    filepath = (import_dir / filename).resolve()
    if filepath.parent != import_dir:
        return JSONResponse(status_code=400, content={"error": "Invalid filename"})
    if not filepath.exists():
        return JSONResponse(status_code=404, content={"error": "File not found"})
    raw_items, skipped = parse_import_file(filepath, runtime=runtime)
    items, invalid = sanitize_queue_items(raw_items, runtime=runtime)
    skipped += invalid
    preview = []
    for item in items:
        if item["type"] == "delay":
            preview.append({"type": "delay", "delay_ms": item["delay_ms"]})
            continue
        if item["type"] == "note":
            preview.append({"type": "note", "text": item["text"]})
            continue
        preview.append({
            "type": "mission_cmd",
            "display": item.get("display", {}),
            "guard": item.get("guard", False),
            "size": len(item.get("raw_cmd", b"")),
        })
    return {"items": preview, "skipped": skipped}


@router.post("/api/import/{filename}", response_model=None)
async def import_file(filename: str, request: Request) -> dict[str, Any] | JSONResponse:
    runtime = get_runtime(request)
    denied = require_api_token(request)
    if denied:
        return denied
    import_dir = runtime.generated_commands_dir().resolve()
    filepath = (import_dir / filename).resolve()
    if filepath.parent != import_dir:
        return JSONResponse(status_code=400, content={"error": "Invalid filename"})
    if not filepath.exists():
        return JSONResponse(status_code=404, content={"error": "File not found"})
    raw_items, skipped = parse_import_file(filepath, runtime=runtime)
    items, invalid = sanitize_queue_items(raw_items, runtime=runtime)
    skipped += invalid

    with runtime.tx.send_lock:
        if runtime.tx.sending["active"]:
            return JSONResponse(status_code=409, content={"error": "cannot modify queue during send"})
        space = MAX_QUEUE - len(runtime.tx.queue)
        if space <= 0:
            return JSONResponse(status_code=400, content={"error": f"queue full ({MAX_QUEUE} items max)"})
        if len(items) > space:
            return JSONResponse(status_code=400, content={"error": f"import has {len(items)} items but only {space} queue slots available"})
        runtime.tx.queue.extend(items)
        runtime.tx.renumber_queue()
        runtime.tx.save_queue()
    await runtime.tx.send_queue_update()
    return {"loaded": len(items), "skipped": skipped}


@router.post("/api/export-queue", response_model=None)
async def export_queue(body: dict[str, Any], request: Request) -> dict[str, Any] | JSONResponse:
    runtime = get_runtime(request)
    denied = require_api_token(request)
    if denied:
        return denied
    name = body.get("name", "").strip()
    if not name:
        from datetime import datetime

        name = datetime.now().strftime("queue_%Y%m%d_%H%M%S")
    import re as _re

    name = _re.sub(r"[^\w\-.]", "_", name)
    if not name.endswith(".jsonl"):
        name += ".jsonl"
    export_dir = runtime.generated_commands_dir()
    export_dir.mkdir(exist_ok=True)
    filepath = (export_dir / name).resolve()
    if filepath.parent != export_dir.resolve():
        return JSONResponse(status_code=400, content={"error": "Invalid filename"})
    with runtime.tx.send_lock:
        items = list(runtime.tx.queue)
    lines = [
        f"// {item['text']}" if item["type"] == "note" else json.dumps(item_to_json(item))
        for item in items
    ]
    filepath.write_text("\n".join(lines) + "\n")
    return {"ok": True, "filename": name, "count": len(items)}
