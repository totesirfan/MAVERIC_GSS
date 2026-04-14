"""
mav_gss_lib.web_runtime.api.session -- Session Lifecycle Routes

Endpoints: api_session_get, api_session_new, api_session_rename, tag_session, new_session
Helpers:   _session_info

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..state import Session, get_runtime
from ..security import require_api_token
from ..services import broadcast_safe

router = APIRouter()


def _session_info(runtime) -> dict:
    """Build session info dict from runtime state."""
    s = runtime.session
    return {
        "session_id": s.session_id,
        "tag": s.tag,
        "started_at": s.started_at,
        "generation": s.generation,
    }


@router.get("/api/session")
async def api_session_get(request: Request):
    """Return current session info and traffic status."""
    runtime = get_runtime(request)
    info = _session_info(runtime)
    traffic_active = (
        runtime.rx.last_rx_at > 0
        and (time.time() - runtime.rx.last_rx_at) < 10.0
    )
    info["traffic_active"] = traffic_active
    return info


@router.post("/api/session/new")
async def api_session_new(body: dict, request: Request):
    """Create a new session with two-phase atomic log rotation."""
    runtime = get_runtime(request)
    denied = require_api_token(request)
    if denied:
        return denied

    tag = body.get("tag", "") or "untitled"
    if not runtime.rx.log and not runtime.tx.log:
        return JSONResponse(status_code=400, content={"error": "No active session"})

    old_gen = runtime.session.generation
    new_session = Session(
        session_id=uuid.uuid4().hex,
        tag=tag,
        started_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        generation=old_gen + 1,
    )

    # -- Prepare phase: open new files without closing old ones --
    rx_prepared = None
    tx_prepared = None
    try:
        if runtime.rx.log:
            rx_prepared = runtime.rx.log.prepare_new_session(tag)
        if runtime.tx.log:
            tx_prepared = runtime.tx.log.prepare_new_session(tag)
    except Exception as exc:
        # Cleanup any prepared files on failure
        for prepared in (rx_prepared, tx_prepared):
            if prepared is not None:
                for key in ("text_f", "jsonl_f"):
                    try:
                        prepared[key].close()
                    except Exception:
                        pass
                for key in ("text_path", "jsonl_path"):
                    try:
                        if os.path.isfile(prepared[key]):
                            os.remove(prepared[key])
                    except OSError:
                        pass
        logging.error("Session prepare failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": f"prepare failed: {exc}"})

    # -- Commit phase: commit each log independently --
    # True cross-log atomicity is not possible without a transaction manager.
    # We commit each side independently and always update session state.
    # If one side fails, we report partial success — the session is still valid
    # but one log may be on the old files.
    commit_errors = []
    if rx_prepared:
        try:
            runtime.rx.log.commit_new_session(rx_prepared)
        except Exception as exc:
            logging.error("RX log commit failed: %s", exc)
            commit_errors.append(f"RX: {exc}")
    if tx_prepared:
        try:
            runtime.tx.log.commit_new_session(tx_prepared)
        except Exception as exc:
            logging.error("TX log commit failed: %s", exc)
            commit_errors.append(f"TX: {exc}")
    # Always update session — even partial rotation is better than stale state
    runtime.session = new_session

    # Mirror the frontend's session_new clears so a hard refresh can't
    # rehydrate stale state from the WS bootstrap path (rx.py:25, tx.py:35).
    runtime.rx.packets.clear()
    runtime.tx.history.clear()

    # Broadcast session_new to all channels
    event = {
        "type": "session_new",
        "session_id": new_session.session_id,
        "tag": new_session.tag,
        "started_at": new_session.started_at,
    }
    await runtime.rx.broadcast(event)
    await runtime.tx.broadcast(event)
    event_text = json.dumps(event)
    await broadcast_safe(runtime.session_clients, runtime.session_lock, event_text)

    info = _session_info(runtime)
    if commit_errors:
        info["ok"] = False
        info["partial"] = True
        info["error"] = "; ".join(commit_errors)
        return JSONResponse(status_code=207, content=info)
    info["ok"] = True
    return info


@router.patch("/api/session")
async def api_session_rename(body: dict, request: Request):
    """Rename the current session tag and log files.

    Rollback is supported on POSIX (synchronous rename). On Windows,
    rename is queued to the writer thread so rollback is not reliable.
    """
    runtime = get_runtime(request)
    denied = require_api_token(request)
    if denied:
        return denied

    tag = body.get("tag", "").strip() or "untitled"
    old_tag = runtime.session.tag

    # Preflight: check both log rename targets
    rx_new_text = rx_new_jsonl = None
    tx_new_text = tx_new_jsonl = None
    try:
        if runtime.rx.log:
            rx_new_text, rx_new_jsonl = runtime.rx.log.rename_preflight(tag)
        if runtime.tx.log:
            tx_new_text, tx_new_jsonl = runtime.tx.log.rename_preflight(tag)
    except (FileExistsError, ValueError) as exc:
        return JSONResponse(status_code=409, content={"error": str(exc)})

    # Save original paths for rollback
    rx_old_text = runtime.rx.log.text_path if runtime.rx.log else None
    rx_old_jsonl = runtime.rx.log.jsonl_path if runtime.rx.log else None

    # Rename RX
    try:
        if runtime.rx.log:
            runtime.rx.log.rename(tag)
    except Exception as exc:
        logging.error("RX rename failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": f"RX rename failed: {exc}"})

    # Rename TX — rollback RX on failure
    try:
        if runtime.tx.log:
            runtime.tx.log.rename(tag)
    except Exception as exc:
        logging.error("TX rename failed: %s, rolling back RX", exc)
        if runtime.rx.log and rx_old_text and rx_old_jsonl:
            try:
                os.rename(runtime.rx.log.text_path, rx_old_text)
                os.rename(runtime.rx.log.jsonl_path, rx_old_jsonl)
                runtime.rx.log.text_path = rx_old_text
                runtime.rx.log.jsonl_path = rx_old_jsonl
            except Exception as rb_exc:
                logging.error("RX rollback also failed: %s", rb_exc)
        return JSONResponse(status_code=500, content={"error": f"TX rename failed: {exc}"})

    # Update session tag
    runtime.session.tag = tag

    # Broadcast session_renamed
    event = {
        "type": "session_renamed",
        "session_id": runtime.session.session_id,
        "tag": tag,
    }
    await runtime.rx.broadcast(event)
    await runtime.tx.broadcast(event)
    event_text = json.dumps(event)
    await broadcast_safe(runtime.session_clients, runtime.session_lock, event_text)

    info = _session_info(runtime)
    info["ok"] = True
    return info


@router.post("/api/logs/tag")
async def tag_session(body: dict, request: Request):
    """Deprecated: use PATCH /api/session instead."""
    logging.warning("POST /api/logs/tag is deprecated — use PATCH /api/session")
    return await api_session_rename(body, request)


@router.post("/api/logs/new")
async def new_session(body: dict, request: Request):
    """Deprecated: use POST /api/session/new instead."""
    logging.warning("POST /api/logs/new is deprecated — use POST /api/session/new")
    return await api_session_new(body, request)
