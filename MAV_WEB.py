#!/usr/bin/env python3
"""MAV_WEB — Web dashboard for MAVERIC GSS.

Serves a React SPA and bridges ZMQ ↔ WebSocket for real-time
RX packet monitoring and TX command queue management.
"""

import asyncio
import json
import logging
import os
import signal
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── mav_gss_lib imports ──────────────────────────────────────────
from mav_gss_lib.config import load_gss_config, save_gss_config, apply_ax25, apply_csp, update_cfg_from_state
from mav_gss_lib.protocol import (
    init_nodes, load_command_defs, parse_cmd_line, build_cmd_raw,
    resolve_node, resolve_ptype, validate_args,
    CSPConfig, AX25Config,
)
from mav_gss_lib.transport import (
    init_zmq_sub, init_zmq_pub, receive_pdu, send_pdu,
    poll_monitor, zmq_cleanup, SUB_STATUS, PUB_STATUS,
)
from mav_gss_lib.parsing import RxPipeline, Packet, build_rx_log_record
from mav_gss_lib.logging import SessionLog, TXLog

# ── Constants ─────────────────────────────────────────────────────
WEB_DIR = Path(__file__).parent / "web" / "dist"
HOST = "127.0.0.1"
PORT = 8080
MAX_PACKETS = 500
MAX_HISTORY = 500

# ── Global state ──────────────────────────────────────────────────
cfg = load_gss_config()
init_nodes(cfg)
cmd_defs, cmd_warn = load_command_defs(cfg["general"].get("command_defs", "maveric_commands.yml"))

# ── ZMQ status holders (mutable list so threads can update) ───────
rx_status = ["OFFLINE"]
tx_status = ["OFFLINE"]

# ── Protocol objects ──────────────────────────────────────────────
csp = CSPConfig()
ax25 = AX25Config()
apply_csp(cfg, csp)
apply_ax25(cfg, ax25)

app = FastAPI(title="MAVERIC GSS Web")

# ── Static asset mount ────────────────────────────────────────────
if WEB_DIR.exists() and (WEB_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")


# =====================================================================
#  REST ENDPOINTS
# =====================================================================

@app.get("/api/status")
async def api_status():
    """System status: version, ZMQ, uplink mode, frequency."""
    return {
        "version": cfg.get("general", {}).get("version", ""),
        "zmq_rx": rx_status[0],
        "zmq_tx": tx_status[0],
        "uplink_mode": cfg.get("tx", {}).get("uplink_mode", "AX.25"),
        "frequency": cfg.get("tx", {}).get("frequency", ""),
    }


@app.get("/api/config")
async def api_config_get():
    """Return full config dict."""
    return cfg


@app.put("/api/config")
async def api_config_put(update: dict):
    """Partial config update — deep-merge, save, re-apply protocol objects."""
    def _deep_merge(base, override):
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                _deep_merge(base[k], v)
            else:
                base[k] = v

    _deep_merge(cfg, update)
    save_gss_config(cfg)
    apply_csp(cfg, csp)
    apply_ax25(cfg, ax25)
    return {"ok": True}


@app.get("/api/schema")
async def api_schema():
    """Return command schema definitions."""
    return cmd_defs


@app.get("/api/logs")
async def api_logs():
    """List log sessions from logs/json/*.jsonl, sorted by mtime descending."""
    log_dir = Path(cfg.get("general", {}).get("log_dir", "logs")) / "json"
    if not log_dir.is_dir():
        return []
    sessions = []
    for p in log_dir.glob("*.jsonl"):
        sessions.append({
            "session_id": p.stem,
            "filename": p.name,
            "size": p.stat().st_size,
            "mtime": p.stat().st_mtime,
        })
    sessions.sort(key=lambda s: s["mtime"], reverse=True)
    return sessions


@app.get("/api/logs/{session_id}")
async def api_log_entries(
    session_id: str,
    cmd: Optional[str] = None,
    time_from: Optional[float] = Query(None, alias="from"),
    time_to: Optional[float] = Query(None, alias="to"),
):
    """Return filtered entries from a log session."""
    log_dir = Path(cfg.get("general", {}).get("log_dir", "logs")) / "json"
    log_file = log_dir / f"{session_id}.jsonl"
    if not log_file.is_file():
        return JSONResponse(status_code=404, content={"error": "session not found"})
    entries = []
    with open(log_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Filter by command name
            if cmd and entry.get("cmd", {}).get("cmd_id") != cmd.lower():
                continue
            # Filter by time range
            if time_from is not None or time_to is not None:
                ts = entry.get("gs_ts", "")
                try:
                    dt = datetime.strptime(ts.rsplit(" ", 1)[0], "%Y-%m-%d %H:%M:%S")
                    epoch = dt.timestamp()
                    if time_from is not None and epoch < time_from:
                        continue
                    if time_to is not None and epoch > time_to:
                        continue
                except (ValueError, IndexError):
                    pass
            entries.append(entry)
    return entries


# ── SPA catch-all (MUST be last) ─────────────────────────────────
if WEB_DIR.exists():
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve React SPA — all non-API routes return index.html."""
        file_path = WEB_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(WEB_DIR / "index.html")

# ── Entry point ───────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"MAVERIC GSS Web → http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
