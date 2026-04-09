"""
mav_gss_lib.web_runtime.api -- REST API Routes

HTTP routes for the web runtime: status/config/schema reads, queue
import/export, log browsing, and session tagging helpers.

Routes here operate on the shared WebRuntime attached to the FastAPI
app, keeping request handlers thin and delegating operational logic to
runtime helpers and services.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from mav_gss_lib.config import (
    apply_ax25,
    apply_csp,
    get_generated_commands_dir,
    load_gss_config,
    save_gss_config,
)
from .state import MAX_QUEUE, Session, get_runtime
from .runtime import deep_merge
from .tx_queue import parse_import_file, make_delay, sanitize_queue_items, validate_mission_cmd, item_to_json
from .security import require_api_token

router = APIRouter()


# =============================================================================
#  STATUS / CONFIG / SCHEMA
# =============================================================================

@router.get("/api/status")
async def api_status(request: Request):
    runtime = get_runtime(request)
    return {
        "mission": runtime.cfg.get("general", {}).get("mission", "maveric"),
        "mission_name": runtime.cfg.get("general", {}).get("mission_name", "MAVERIC"),
        "version": runtime.cfg.get("general", {}).get("version", ""),
        "zmq_rx": runtime.rx.status[0],
        "zmq_tx": runtime.tx.status[0],
        "uplink_mode": runtime.cfg.get("tx", {}).get("uplink_mode", "AX.25"),
        "frequency": runtime.cfg.get("tx", {}).get("frequency", ""),
        "schema_path": runtime.cfg.get("general", {}).get("command_defs_resolved", "")
            or runtime.cfg.get("general", {}).get("command_defs", ""),
        "schema_count": len(runtime.cmd_defs),
        "schema_warning": runtime.cfg.get("general", {}).get("command_defs_warning", ""),
        "auth_token": runtime.session_token,
        "log_dir": runtime.cfg.get("general", {}).get("log_dir", "logs"),
        "logging": runtime.rx.log is not None,
        "rx_log_text": runtime.rx.log.text_path if runtime.rx.log else None,
        "rx_log_json": runtime.rx.log.jsonl_path if runtime.rx.log else None,
        "tx_log_text": runtime.tx.log.text_path if runtime.tx.log else None,
        "tx_log_json": runtime.tx.log.jsonl_path if runtime.tx.log else None,
    }


@router.get("/api/selfcheck")
async def api_selfcheck(request: Request):
    """Lightweight diagnostic for verifying runtime environment."""
    runtime = get_runtime(request)
    general = runtime.cfg.get("general", {})

    # Resolve config file path
    from mav_gss_lib.config import _DEFAULT_GSS_PATH
    config_path = str(_DEFAULT_GSS_PATH)
    config_exists = os.path.isfile(config_path)

    # Resolve command schema path
    schema_resolved = general.get("command_defs_resolved", "")
    schema_exists = os.path.isfile(schema_resolved) if schema_resolved else False

    # Web build presence
    from .state import WEB_DIR
    web_build = (WEB_DIR / "index.html").is_file()
    asset_dir = (WEB_DIR / "assets").is_dir()

    return {
        "mission": general.get("mission", "maveric"),
        "mission_name": general.get("mission_name", ""),
        "version": general.get("version", ""),
        "config_path": config_path,
        "config_exists": config_exists,
        "schema_path": schema_resolved,
        "schema_exists": schema_exists,
        "schema_count": len(runtime.cmd_defs),
        "schema_warning": general.get("command_defs_warning", ""),
        "web_build": web_build,
        "web_assets": asset_dir,
        "zmq_rx_addr": runtime.cfg.get("rx", {}).get("zmq_addr", ""),
        "zmq_tx_addr": runtime.cfg.get("tx", {}).get("zmq_addr", ""),
        "zmq_rx_status": runtime.rx.status[0],
        "zmq_tx_status": runtime.tx.status[0],
        "log_dir": general.get("log_dir", "logs"),
        "uplink_mode": runtime.cfg.get("tx", {}).get("uplink_mode", ""),
    }


@router.get("/api/config")
async def api_config_get(request: Request):
    return get_runtime(request).cfg


@router.put("/api/config")
async def api_config_put(update: dict, request: Request):
    runtime = get_runtime(request)
    denied = require_api_token(request)
    if denied:
        return denied

    old_rx_addr = runtime.cfg.get("rx", {}).get("zmq_addr", "tcp://127.0.0.1:52001")
    old_tx_addr = runtime.cfg.get("tx", {}).get("zmq_addr", "tcp://127.0.0.1:52002")
    requested_rx_addr = update.get("rx", {}).get("zmq_addr", old_rx_addr) if isinstance(update.get("rx"), dict) else old_rx_addr
    requested_tx_addr = update.get("tx", {}).get("zmq_addr", old_tx_addr) if isinstance(update.get("tx"), dict) else old_tx_addr
    if runtime.tx.sending["active"] and (requested_rx_addr != old_rx_addr or requested_tx_addr != old_tx_addr):
        return JSONResponse(status_code=409, content={"error": "cannot change ZMQ addresses during active send"})

    # Mission selection is startup-only — strip it from runtime updates
    if isinstance(update.get("general"), dict):
        update["general"].pop("mission", None)

    with runtime.cfg_lock:
        deep_merge(runtime.cfg, update)
        # Save only the raw operator YAML + update, not platform defaults or mission data.
        # This prevents defaults from leaking into the operator's gss.yml.
        import yaml as _yaml
        from mav_gss_lib.config import _DEFAULT_GSS_PATH
        raw_operator = {}
        gss_path = str(_DEFAULT_GSS_PATH)
        if os.path.isfile(gss_path):
            with open(gss_path) as _f:
                raw_operator = _yaml.safe_load(_f) or {}
        deep_merge(raw_operator, update)
        save_gss_config(raw_operator)
        apply_csp(runtime.cfg, runtime.csp)
        apply_ax25(runtime.cfg, runtime.ax25)
        new_rx_addr = runtime.cfg.get("rx", {}).get("zmq_addr", old_rx_addr)
        new_tx_addr = runtime.cfg.get("tx", {}).get("zmq_addr", old_tx_addr)

    if new_tx_addr != old_tx_addr:
        runtime.tx.restart_pub(new_tx_addr)
        if runtime.tx.log:
            runtime.tx.log._zmq_addr = new_tx_addr
    if new_rx_addr != old_rx_addr:
        runtime.rx.restart_receiver()
        if runtime.rx.log:
            runtime.rx.log._zmq_addr = new_rx_addr
    return {"ok": True}


@router.get("/api/schema")
async def api_schema(request: Request):
    return get_runtime(request).cmd_defs


@router.get("/api/columns")
async def api_columns(request: Request):
    """Return adapter-provided column definitions for packet list rendering.

    Minimal enabler: same data as sent over /ws/rx on connect, exposed via
    REST so the log viewer can render rows from _rendering.row.
    """
    runtime = get_runtime(request)
    return runtime.adapter.packet_list_columns()


@router.get("/api/tx/capabilities")
async def api_tx_capabilities(request: Request):
    """Return TX capabilities for the loaded mission adapter."""
    from mav_gss_lib.mission_adapter import get_tx_capabilities
    runtime = get_runtime(request)
    return get_tx_capabilities(runtime.adapter)


@router.get("/api/tx-columns")
async def api_tx_columns(request: Request):
    """Return adapter-provided column definitions for TX queue/history rendering."""
    runtime = get_runtime(request)
    return runtime.adapter.tx_queue_columns()


# =============================================================================
#  QUEUE IMPORT / EXPORT
# =============================================================================

@router.get("/api/import-files")
async def list_import_files(request: Request):
    runtime = get_runtime(request)
    import_dir = runtime.generated_commands_dir()
    if not import_dir.exists():
        return []
    files = []
    for path in sorted(import_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        files.append({"name": path.name, "path": str(path), "size": path.stat().st_size})
    return files



@router.get("/api/import/{filename}/preview")
async def preview_import(filename: str, request: Request):
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


@router.post("/api/import/{filename}")
async def import_file(filename: str, request: Request):
    runtime = get_runtime(request)
    denied = require_api_token(request)
    if denied:
        return denied
    if runtime.tx.sending["active"]:
        return JSONResponse(status_code=409, content={"error": "cannot modify queue during send"})
    import_dir = runtime.generated_commands_dir().resolve()
    filepath = (import_dir / filename).resolve()
    if filepath.parent != import_dir:
        return JSONResponse(status_code=400, content={"error": "Invalid filename"})
    if not filepath.exists():
        return JSONResponse(status_code=404, content={"error": "File not found"})
    raw_items, skipped = parse_import_file(filepath, runtime=runtime)
    items, invalid = sanitize_queue_items(raw_items, runtime=runtime)
    skipped += invalid
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


@router.post("/api/export-queue")
async def export_queue(body: dict, request: Request):
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


# =============================================================================
#  LOG BROWSING / SESSION HELPERS
# =============================================================================

@router.get("/api/logs")
async def api_logs(request: Request):
    runtime = get_runtime(request)
    log_dir = Path(runtime.cfg.get("general", {}).get("log_dir", "logs")) / "json"
    if not log_dir.is_dir():
        return []
    sessions = []
    for path in log_dir.glob("*.jsonl"):
        stem = path.stem
        direction = "downlink" if stem.startswith("downlink") else "uplink" if stem.startswith("uplink") else "unknown"
        sessions.append(
            {
                "session_id": stem,
                "filename": path.name,
                "size": path.stat().st_size,
                "mtime": path.stat().st_mtime,
                "direction": direction,
            }
        )
    sessions.sort(key=lambda item: item["mtime"], reverse=True)
    return sessions


def parse_replay_entry(entry: dict, cmd_defs: dict, adapter=None) -> dict | None:
    """Normalize one JSONL log entry for replay.

    RX entries: platform envelope + _rendering passthrough.
    TX entries: unchanged legacy normalization.
    """
    # Timestamp extraction
    ts = entry.get("gs_ts", "") or entry.get("ts", "")
    if "T" in ts and ts.index("T") == 10:
        ts_time = ts.split("T")[1][:8]
    elif " " in ts:
        ts_time = ts.split(" ")[1] if len(ts.split(" ")) > 1 else ""
    else:
        ts_time = ts[:8]

    # RX vs TX: RX entries always have "pkt" (packet number)
    is_rx = "pkt" in entry

    if is_rx:
        normalized = {
            "num": entry.get("pkt", 0),
            "time": ts_time,
            "time_utc": ts,
            "frame": entry.get("frame_type", ""),
            "size": entry.get("raw_len", entry.get("payload_len", 0)),
            "is_dup": entry.get("duplicate", False),
            "is_echo": entry.get("uplink_echo", False),
            "is_unknown": entry.get("unknown", False),
            "raw_hex": entry.get("raw_hex", ""),
            "warnings": entry.get("warnings", []),
            "_rendering": entry.get("_rendering", {}),
        }
    else:
        # TX log entry normalization — consumes persisted display directly
        display = entry.get("display", {})
        normalized = {
            "num": entry.get("n", 0),
            "time": ts_time,
            "time_utc": ts,
            "frame": entry.get("uplink_mode", ""),
            "size": entry.get("raw_len", entry.get("len", 0)),
            "is_dup": False,
            "is_echo": False,
            "is_unknown": False,
            "is_tx": True,
            "raw_hex": entry.get("raw_hex", ""),
            "warnings": [],
            "_rendering": {
                "row": {"values": {
                    "num": entry.get("n", 0),
                    "time": ts_time,
                    "size": entry.get("raw_len", entry.get("len", 0)),
                    **display.get("row", {}),
                }, "_meta": {}},
                "detail_blocks": display.get("detail_blocks", []),
                "protocol_blocks": [],
                "integrity_blocks": [],
            },
        }

    return normalized


@router.get("/api/logs/{session_id}")
async def api_log_entries(
    session_id: str,
    request: Request,
    cmd: Optional[str] = None,
    time_from: Optional[str] = Query(None, alias="from"),
    time_to: Optional[str] = Query(None, alias="to"),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
):
    runtime = get_runtime(request)
    log_dir = (Path(runtime.cfg.get("general", {}).get("log_dir", "logs")) / "json").resolve()
    log_file = (log_dir / f"{session_id}.jsonl").resolve()
    if log_file.parent != log_dir:
        return JSONResponse(status_code=400, content={"error": "invalid session_id"})
    if not log_file.is_file():
        return JSONResponse(status_code=404, content={"error": "session not found"})

    entries = []
    has_more = False
    matched = 0
    with open(log_file) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            normalized = parse_replay_entry(entry, runtime.cmd_defs, adapter=runtime.adapter)
            if normalized is None:
                continue

            # Apply cmd filter — both RX and TX use _rendering.row.values.cmd
            if cmd:
                row_cmd = ""
                r = normalized.get("_rendering")
                if isinstance(r, dict):
                    row_vals = r.get("row", {})
                    if isinstance(row_vals, dict):
                        row_cmd = str(row_vals.get("values", {}).get("cmd", ""))
                if cmd.lower() not in row_cmd.lower():
                    continue
            # Apply time filters
            if time_from is not None and normalized["time"] < str(time_from):
                continue
            if time_to is not None and normalized["time"] > str(time_to):
                continue

            # Pagination: skip entries before offset, collect up to limit
            if matched < offset:
                matched += 1
                continue
            if len(entries) < limit:
                entries.append(normalized)
                matched += 1
            else:
                # One match past limit — there are more entries
                has_more = True
                break

    return {"entries": entries, "has_more": has_more, "offset": offset, "limit": limit}


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
    for sc in list(runtime.session_clients):
        try:
            await sc.send_text(event_text)
        except Exception:
            pass

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
    for sc in list(runtime.session_clients):
        try:
            await sc.send_text(event_text)
        except Exception:
            pass

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
