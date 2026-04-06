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
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from mav_gss_lib.config import (
    apply_ax25,
    apply_csp,
    get_command_defs_path,
    get_generated_commands_dir,
    save_gss_config,
)
from mav_gss_lib.protocol import node_name, ptype_name, resolve_node, resolve_ptype

from .state import MAX_QUEUE, get_runtime
from .runtime import deep_merge, make_cmd, make_delay, sanitize_queue_items
from .security import require_api_token
from .services import item_to_json

router = APIRouter()


# =============================================================================
#  STATUS / CONFIG / SCHEMA
# =============================================================================

@router.get("/api/status")
async def api_status(request: Request):
    runtime = get_runtime(request)
    cmd_path = get_command_defs_path(runtime.cfg)
    return {
        "mission_name": runtime.cfg.get("general", {}).get("mission_name", "MAVERIC"),
        "version": runtime.cfg.get("general", {}).get("version", ""),
        "zmq_rx": runtime.rx.status[0],
        "zmq_tx": runtime.tx.status[0],
        "uplink_mode": runtime.cfg.get("tx", {}).get("uplink_mode", "AX.25"),
        "frequency": runtime.cfg.get("tx", {}).get("frequency", ""),
        "schema_path": cmd_path,
        "schema_count": len(runtime.cmd_defs),
        "auth_token": runtime.session_token,
        "log_dir": runtime.cfg.get("general", {}).get("log_dir", "logs"),
        "logging": runtime.rx.log is not None,
        "rx_log_text": runtime.rx.log.text_path if runtime.rx.log else None,
        "rx_log_json": runtime.rx.log.jsonl_path if runtime.rx.log else None,
        "tx_log_text": runtime.tx.log.text_path if runtime.tx.log else None,
        "tx_log_json": runtime.tx.log.jsonl_path if runtime.tx.log else None,
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
        save_gss_config(runtime.cfg)
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


def parse_import_file(filepath, runtime=None):
    """Parse a queue import JSONL file into runtime queue items."""
    import re

    items = []
    skipped = 0
    for raw_line in filepath.read_text().strip().split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        in_str, escaped, out = False, False, []
        for index, ch in enumerate(line):
            if escaped:
                escaped = False
                out.append(ch)
                continue
            if ch == "\\" and in_str:
                escaped = True
                out.append(ch)
                continue
            if ch == '"':
                in_str = not in_str
                out.append(ch)
                continue
            if not in_str and ch == "/" and index + 1 < len(line) and line[index + 1] == "/":
                break
            out.append(ch)
        line = "".join(out).rstrip().rstrip(",")
        if not line:
            continue
        kvs = {}
        if line.startswith("["):
            kv_pattern = re.compile(r',\s*"(\w+)"\s*:\s*(true|false|null|\d+(?:\.\d+)?|"[^"]*")')
            for match in kv_pattern.finditer(line):
                key, raw = match.group(1), match.group(2)
                if raw == "true":
                    kvs[key] = True
                elif raw == "false":
                    kvs[key] = False
                elif raw.startswith('"'):
                    kvs[key] = raw[1:-1]
                else:
                    kvs[key] = int(raw) if "." not in raw else float(raw)
            if kvs:
                cleaned = kv_pattern.sub("", line).rstrip().rstrip(",").rstrip()
                if not cleaned.endswith("]"):
                    cleaned = cleaned.rstrip(",").rstrip() + "]"
                line = cleaned
        try:
            obj = json.loads(line)
            if isinstance(obj, list) and len(obj) >= 5:
                src_s, dest_s, echo_s, ptype_s, cmd_s = obj[:5]
                args_s = str(obj[5]) if len(obj) > 5 else ""
                src = resolve_node(str(src_s))
                dest = resolve_node(str(dest_s))
                echo = resolve_node(str(echo_s))
                ptype_val = resolve_ptype(str(ptype_s))
                if None in (src, dest, echo, ptype_val):
                    skipped += 1
                    continue
                items.append(
                    make_cmd(
                        src,
                        dest,
                        echo,
                        ptype_val,
                        cmd_s.lower(),
                        args_s,
                        bool(kvs.get("guard", False)),
                        runtime=runtime,
                    )
                )
            elif isinstance(obj, dict):
                if obj.get("type") == "delay":
                    items.append(make_delay(max(0, min(300_000, int(obj.get("delay_ms", 0))))))
                elif obj.get("type") == "cmd" or "cmd" in obj:
                    src = resolve_node(str(obj.get("src", "GS")))
                    dest = resolve_node(str(obj.get("dest", "GS")))
                    echo = resolve_node(str(obj.get("echo", "NONE")))
                    ptype_val = resolve_ptype(str(obj.get("ptype", "CMD")))
                    if None in (src, dest, echo, ptype_val):
                        skipped += 1
                        continue
                    items.append(
                        make_cmd(
                            src,
                            dest,
                            echo,
                            ptype_val,
                            obj["cmd"].lower(),
                            str(obj.get("args", "")),
                            bool(obj.get("guard", False)),
                            runtime=runtime,
                        )
                    )
                else:
                    skipped += 1
            else:
                skipped += 1
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            skipped += 1
    return items, skipped


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
        preview.append(
            {
                "type": "cmd",
                "src": node_name(item["src"]),
                "dest": node_name(item["dest"]),
                "echo": node_name(item["echo"]),
                "ptype": ptype_name(item["ptype"]),
                "cmd": item["cmd"],
                "args": item["args"],
                "guard": item.get("guard", False),
            }
        )
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
    lines = [json.dumps(item_to_json(item)) for item in items]
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


@router.get("/api/logs/{session_id}")
async def api_log_entries(
    session_id: str,
    request: Request,
    cmd: Optional[str] = None,
    time_from: Optional[str] = Query(None, alias="from"),
    time_to: Optional[str] = Query(None, alias="to"),
):
    runtime = get_runtime(request)
    log_dir = (Path(runtime.cfg.get("general", {}).get("log_dir", "logs")) / "json").resolve()
    log_file = (log_dir / f"{session_id}.jsonl").resolve()
    if log_file.parent != log_dir:
        return JSONResponse(status_code=400, content={"error": "invalid session_id"})
    if not log_file.is_file():
        return JSONResponse(status_code=404, content={"error": "session not found"})

    entries = []
    with open(log_file) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw_cmd = entry.get("cmd")
            is_rx = isinstance(raw_cmd, dict)
            is_tx = not is_rx and isinstance(raw_cmd, str)
            if is_rx:
                cmd_id = raw_cmd.get("cmd_id", "") if raw_cmd else ""
            elif is_tx:
                cmd_id = str(raw_cmd)
            else:
                cmd_id = str(entry.get("cmd_id", ""))
            if cmd and cmd.lower() not in cmd_id.lower():
                continue
            ts = entry.get("gs_ts", "") or entry.get("ts", "")
            if "T" in ts and ts.index("T") == 10:
                ts_time = ts.split("T")[1][:8]
            elif " " in ts:
                ts_time = ts.split(" ")[1] if len(ts.split(" ")) > 1 else ""
            else:
                ts_time = ts[:8]
            if time_from is not None and ts_time < str(time_from):
                continue
            if time_to is not None and ts_time > str(time_to):
                continue

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
                    "csp_header": entry.get("csp_candidate"),
                    "cmd": raw_cmd.get("cmd_id", "") if raw_cmd else "",
                    "src": node_name(raw_cmd.get("src", 0)) if raw_cmd else "",
                    "dest": node_name(raw_cmd.get("dest", 0)) if raw_cmd else "",
                    "echo": node_name(raw_cmd.get("echo", 0)) if raw_cmd else "",
                    "ptype": ptype_name(raw_cmd.get("pkt_type", 0)) if raw_cmd else "",
                    "crc16_ok": raw_cmd.get("crc_valid") if raw_cmd else None,
                    "warnings": entry.get("warnings", []),
                }
                typed = raw_cmd.get("typed_args") if raw_cmd else None
                raw_args = raw_cmd.get("args", {}) if raw_cmd else {}
                log_extra = [str(arg) for arg in (raw_cmd.get("extra_args") or [])] if raw_cmd else []
                if typed and isinstance(typed, list):
                    normalized["args_named"] = [
                        {
                            "name": ta["name"],
                            "value": ta.get("value", b"").hex()
                            if isinstance(ta.get("value"), (bytes, bytearray))
                            else str(ta.get("value", "")),
                            "important": bool(ta.get("important")),
                        }
                        for ta in typed
                    ]
                    normalized["args_extra"] = [
                        arg.hex() if isinstance(arg, (bytes, bytearray)) else str(arg)
                        for arg in (raw_cmd.get("extra_args") or [])
                    ]
                else:
                    all_values = []
                    if isinstance(raw_args, dict) and raw_args:
                        all_values.extend([str(value) for value in raw_args.values()])
                    elif isinstance(raw_args, list):
                        all_values.extend([str(arg) for arg in raw_args])
                    elif raw_args and not isinstance(raw_args, dict):
                        all_values.append(str(raw_args))
                    all_values.extend(log_extra)
                    defn = runtime.cmd_defs.get(cmd_id.lower(), {})
                    rx_defs = defn.get("rx_args", [])
                    named = []
                    for index, schema_arg in enumerate(rx_defs):
                        if schema_arg.get("type") == "blob":
                            blob_val = " ".join(all_values[index:])
                            named.append({"name": schema_arg["name"], "value": blob_val, "important": bool(schema_arg.get("important"))})
                            all_values = all_values[:index]
                            break
                        if index < len(all_values):
                            named.append({"name": schema_arg["name"], "value": all_values[index], "important": bool(schema_arg.get("important"))})
                    normalized["args_named"] = named
                    normalized["args_extra"] = all_values[len([arg for arg in rx_defs if arg.get("type") != "blob"]) :]
                crc_status = entry.get("csp_crc32")
                if isinstance(crc_status, dict):
                    normalized["crc32_ok"] = crc_status.get("valid")
            else:
                normalized = {
                    "num": entry.get("n", 0),
                    "time": ts_time,
                    "time_utc": ts,
                    "frame": entry.get("uplink_mode", ""),
                    "size": entry.get("raw_len", entry.get("len", 0)),
                    "is_dup": False,
                    "is_echo": False,
                    "is_unknown": False,
                    "raw_hex": entry.get("raw_hex", ""),
                    "csp_header": entry.get("csp"),
                    "cmd": str(entry.get("cmd", "")),
                    "src": str(entry.get("src_lbl", node_name(entry.get("src", 0)))),
                    "dest": str(entry.get("dest_lbl", node_name(entry.get("dest", 0)))),
                    "echo": str(entry.get("echo_lbl", node_name(entry.get("echo", 0)))),
                    "ptype": str(entry.get("ptype_lbl", ptype_name(entry.get("ptype", 0)))),
                    "args_named": runtime.tx.match_tx_args(str(entry.get("cmd", "")), str(entry.get("args", ""))),
                    "args_extra": runtime.tx.tx_extra_args(str(entry.get("cmd", "")), str(entry.get("args", ""))),
                    "warnings": [],
                }
            entries.append(normalized)
    return entries


@router.post("/api/logs/tag")
async def tag_session(body: dict, request: Request):
    runtime = get_runtime(request)
    denied = require_api_token(request)
    if denied:
        return denied
    tag = body.get("tag", "")
    if runtime.rx.log and tag:
        runtime.rx.log.rename(tag)
        return {"ok": True, "path": runtime.rx.log.jsonl_path}
    return JSONResponse(status_code=400, content={"error": "No active session or empty tag"})


@router.post("/api/logs/new")
async def new_session(body: dict, request: Request):
    runtime = get_runtime(request)
    denied = require_api_token(request)
    if denied:
        return denied
    tag = body.get("tag", "")
    if runtime.rx.log:
        runtime.rx.log.new_session(tag)
        return {"ok": True, "path": runtime.rx.log.jsonl_path}
    return JSONResponse(status_code=400, content={"error": "No active session"})
