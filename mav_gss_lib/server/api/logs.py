"""
mav_gss_lib.server.api.logs -- Log Browsing Routes

Endpoints: api_logs, api_log_entries
Helpers:   parse_replay_entry

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..state import get_runtime

router = APIRouter()


def parse_replay_entry(entry: dict) -> dict | None:
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
        row = dict(display.get("row", {}))
        row.update({
            "num": {"value": entry.get("n", 0)},
            "time": {"value": ts_time, "monospace": True},
            "size": {"value": entry.get("raw_len", entry.get("len", 0))},
        })
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
                "row": row,
                "detail_blocks": display.get("detail_blocks", []),
                "protocol_blocks": [],
                "integrity_blocks": [],
            },
        }

    return normalized


@router.get("/api/logs")
async def api_logs(request: Request):
    runtime = get_runtime(request)
    log_dir = Path(runtime.log_dir) / "json"
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
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
):
    runtime = get_runtime(request)
    log_dir = (Path(runtime.log_dir) / "json").resolve()
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

            normalized = parse_replay_entry(entry)
            if normalized is None:
                continue

            # Apply cmd filter — RX and TX use v2 cell-shaped _rendering.row.cmd.
            if cmd:
                row_cmd = ""
                r = normalized.get("_rendering")
                if isinstance(r, dict):
                    row = r.get("row", {})
                    if isinstance(row, dict):
                        cmd_cell = row.get("cmd", {})
                        if isinstance(cmd_cell, dict):
                            row_cmd = str(cmd_cell.get("value", ""))
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
