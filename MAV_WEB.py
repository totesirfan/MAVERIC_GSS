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
import tempfile
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
import mav_gss_lib.protocol as protocol
from mav_gss_lib.protocol import (
    init_nodes, load_command_defs, parse_cmd_line, build_cmd_raw,
    resolve_node, resolve_ptype, validate_args,
    CSPConfig, AX25Config, node_name, ptype_name,
)
from mav_gss_lib.transport import (
    init_zmq_sub, init_zmq_pub, receive_pdu, send_pdu,
    poll_monitor, zmq_cleanup, SUB_STATUS, PUB_STATUS,
)
from mav_gss_lib.parsing import RxPipeline, Packet, build_rx_log_record
from mav_gss_lib.logging import SessionLog, TXLog
from mav_gss_lib.ax25 import build_ax25_gfsk_frame

try:
    from mav_gss_lib.golay import build_asm_golay_frame, _GR_RS_OK
    _GOLAY_OK = _GR_RS_OK
except ImportError:
    _GOLAY_OK = False

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

# ── RX state ──────────────────────────────────────────────────────
rx_packets: deque = deque(maxlen=MAX_PACKETS)
rx_queue: Queue = Queue()
rx_stop = threading.Event()
rx_clients: list[WebSocket] = []
rx_lock = threading.Lock()
rx_log: SessionLog | None = None

pipeline = RxPipeline(cmd_defs, {})

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


# =====================================================================
#  RX WEBSOCKET
# =====================================================================

def _rx_thread():
    """Background thread: ZMQ SUB -> rx_queue."""
    addr = cfg.get("rx", {}).get("zmq_addr", "tcp://127.0.0.1:52001")
    try:
        ctx, sock, monitor = init_zmq_sub(addr)
    except Exception as e:
        logging.error("RX ZMQ init failed: %s", e)
        return

    status = "OFFLINE"
    while not rx_stop.is_set():
        status = poll_monitor(monitor, SUB_STATUS, status)
        rx_status[0] = status
        result = receive_pdu(sock)
        if result is not None:
            rx_queue.put(result)

    zmq_cleanup(monitor, SUB_STATUS, status, sock, ctx)


def _packet_to_json(pkt: Packet) -> dict:
    """Convert a Packet dataclass to a JSON-serializable dict."""
    cmd = pkt.cmd
    d = {
        "num": pkt.pkt_num,
        "time": pkt.gs_ts,
        "time_utc": pkt.gs_ts,
        "frame": pkt.frame_type,
        "src": node_name(cmd["src"]) if cmd else "",
        "dest": node_name(cmd["dest"]) if cmd else "",
        "echo": node_name(cmd["echo"]) if cmd else "",
        "ptype": ptype_name(cmd["pkt_type"]) if cmd else "",
        "cmd": cmd["cmd_id"] if cmd else "",
        "args": "",
        "size": len(pkt.raw),
        "crc16_ok": cmd.get("crc_valid") if cmd else None,
        "crc32_ok": pkt.crc_status.get("csp_crc32_valid"),
        "is_echo": pkt.is_uplink_echo,
        "is_dup": pkt.is_dup,
        "is_unknown": pkt.is_unknown,
        "raw_hex": pkt.raw.hex(),
        "warnings": pkt.warnings,
        "csp_header": pkt.csp,
        "ax25_header": pkt.stripped_hdr,
    }
    # Format args
    if cmd and cmd.get("schema_match") and cmd.get("typed_args"):
        parts = []
        for ta in cmd["typed_args"]:
            if ta["type"] == "epoch_ms" and hasattr(ta["value"], "ms"):
                parts.append(str(ta["value"].ms))
            elif ta["type"] == "epoch_ms" and isinstance(ta["value"], dict) and "ms" in ta["value"]:
                parts.append(str(ta["value"]["ms"]))
            else:
                parts.append(str(ta["value"]))
        d["args"] = " ".join(parts)
    elif cmd:
        d["args"] = " ".join(cmd.get("args", []))
    return d


async def _rx_broadcast():
    """Async coroutine: drain rx_queue, process via pipeline, broadcast JSON."""
    last_status_push = 0.0
    while True:
        drained = 0
        while True:
            try:
                meta, raw = rx_queue.get_nowait()
            except Empty:
                break
            pkt = pipeline.process(meta, raw)
            pkt_json = _packet_to_json(pkt)
            rx_packets.append(pkt_json)
            msg = json.dumps({"type": "packet", "data": pkt_json})
            with rx_lock:
                dead = []
                for ws in rx_clients:
                    try:
                        await ws.send_text(msg)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    rx_clients.remove(ws)
            drained += 1

        # Periodic status push (every 2 seconds when idle)
        now = time.time()
        if drained == 0 and now - last_status_push > 2.0:
            last_status_push = now
            status_msg = json.dumps({
                "type": "status",
                "data": {
                    "zmq_rx": rx_status[0],
                    "zmq_tx": tx_status[0],
                    "packet_count": pipeline.packet_count,
                    "unknown_count": pipeline.unknown_count,
                    "echo_count": pipeline.uplink_echo_count,
                },
            })
            with rx_lock:
                dead = []
                for ws in rx_clients:
                    try:
                        await ws.send_text(status_msg)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    rx_clients.remove(ws)

        await asyncio.sleep(0.05)


@app.websocket("/ws/rx")
async def ws_rx(websocket: WebSocket):
    """RX WebSocket: send packet backlog, then stream live updates."""
    await websocket.accept()
    # Send backlog
    for pkt_json in list(rx_packets):
        try:
            await websocket.send_text(json.dumps({"type": "packet", "data": pkt_json}))
        except Exception:
            return
    with rx_lock:
        rx_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep-alive / client pings
    except WebSocketDisconnect:
        pass
    finally:
        with rx_lock:
            if websocket in rx_clients:
                rx_clients.remove(websocket)


# =====================================================================
#  TX WEBSOCKET
# =====================================================================

# ── TX state ──────────────────────────────────────────────────────
tx_queue: list = []
tx_history: list = []
tx_clients: list[WebSocket] = []
tx_lock = threading.Lock()
tx_log: TXLog | None = None
tx_count = 0
tx_sending = {
    "active": False, "idx": -1, "total": 0,
    "guarding": False, "sent_at": 0, "waiting": False,
}
tx_abort = threading.Event()
tx_guard_event = threading.Event()
tx_guard_ok = threading.Event()
tx_send_lock = threading.Lock()

QUEUE_FILE = Path(cfg.get("general", {}).get("log_dir", "logs")) / ".pending_queue.jsonl"

# ── Queue item helpers ────────────────────────────────────────────

def _make_cmd(src, dest, echo, ptype, cmd, args, guard=False):
    """Create a command queue item dict with raw_cmd built from fields."""
    raw_cmd = build_cmd_raw(dest, cmd, args, echo=echo, ptype=ptype, origin=src)
    return {"type": "cmd", "src": src, "dest": dest, "echo": echo, "ptype": ptype,
            "cmd": cmd, "args": args, "guard": guard, "raw_cmd": raw_cmd}


def _make_delay(delay_ms):
    """Create a delay queue item dict."""
    return {"type": "delay", "delay_ms": delay_ms}


# ── Queue persistence ─────────────────────────────────────────────

def _item_to_json(item):
    """Serialize a queue item dict to a JSON-safe dict (no raw_cmd)."""
    d = {k: v for k, v in item.items() if k != "raw_cmd"}
    if d["type"] == "cmd" and not d.get("guard"):
        d.pop("guard", None)
    return d


def _json_to_item(d):
    """Deserialize a JSON dict into a queue item, rebuilding raw_cmd."""
    if d["type"] == "delay":
        return _make_delay(d.get("delay_ms", 0))
    return _make_cmd(d["src"], d["dest"], d["echo"], d["ptype"],
                     d["cmd"], d.get("args", ""), bool(d.get("guard")))


def _save_queue():
    """Atomically write the full TX queue to .pending_queue.jsonl."""
    if not tx_queue:
        try:
            os.remove(QUEUE_FILE)
        except FileNotFoundError:
            pass
        return
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=str(QUEUE_FILE.parent))
    try:
        with os.fdopen(fd, "w") as f:
            for item in tx_queue:
                f.write(json.dumps(_item_to_json(item)) + "\n")
        os.replace(tmp, str(QUEUE_FILE))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_queue():
    """Load the persisted TX queue from .pending_queue.jsonl, if it exists."""
    if not QUEUE_FILE.is_file():
        return []
    items = []
    with open(QUEUE_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                items.append(_json_to_item(d))
            except (json.JSONDecodeError, KeyError, ValueError):
                pass
    return items


def _renumber_queue():
    """Assign sequential numbers to cmd items in the queue."""
    n = 0
    for item in tx_queue:
        if item["type"] == "cmd":
            n += 1
            item["num"] = n


def _queue_summary():
    """Return {cmds, guards, est_time_s} for current queue."""
    cmds = sum(1 for i in tx_queue if i["type"] == "cmd")
    guards = sum(1 for i in tx_queue if i.get("guard"))
    delay_total = sum(i.get("delay_ms", 0) for i in tx_queue if i["type"] == "delay")
    default_delay = cfg.get("tx", {}).get("delay_ms", 500)
    inter_cmd_ms = default_delay * max(cmds - 1, 0)
    est_time_s = (delay_total + inter_cmd_ms) / 1000.0
    return {"cmds": cmds, "guards": guards, "est_time_s": round(est_time_s, 1)}


def _queue_items_json():
    """Serialize queue items, resolving node/ptype IDs to names."""
    result = []
    for item in tx_queue:
        if item["type"] == "delay":
            result.append({"type": "delay", "delay_ms": item["delay_ms"]})
        else:
            result.append({
                "type": "cmd",
                "num": item.get("num", 0),
                "src": node_name(item["src"]),
                "dest": node_name(item["dest"]),
                "echo": node_name(item["echo"]),
                "ptype": ptype_name(item["ptype"]),
                "cmd": item["cmd"],
                "args": item["args"],
                "guard": item.get("guard", False),
                "size": len(item.get("raw_cmd", b"")),
            })
    return result


async def _tx_broadcast(msg):
    """Send a JSON message to all connected TX WebSocket clients."""
    text = json.dumps(msg) if isinstance(msg, dict) else msg
    with tx_lock:
        dead = []
        for ws in tx_clients:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            tx_clients.remove(ws)


async def _send_queue_update():
    """Broadcast full queue state to all TX clients."""
    await _tx_broadcast({
        "type": "queue_update",
        "items": _queue_items_json(),
        "summary": _queue_summary(),
        "sending": tx_sending.copy(),
    })


# ── TX Send Task ──────────────────────────────────────────────────

async def _run_send():
    """Async send task: iterate queue front-to-back, build frames, send via ZMQ."""
    global tx_count

    addr = cfg.get("tx", {}).get("zmq_addr", "tcp://127.0.0.1:52002")
    try:
        ctx, sock, monitor = init_zmq_pub(addr)
    except Exception as e:
        logging.error("TX ZMQ PUB init failed: %s", e)
        await _tx_broadcast({"type": "send_error", "error": str(e)})
        with tx_send_lock:
            tx_sending.update(active=False, idx=-1, total=0, guarding=False, sent_at=0, waiting=False)
        await _send_queue_update()
        return

    uplink_mode = cfg.get("tx", {}).get("uplink_mode", "AX.25")
    default_delay = cfg.get("tx", {}).get("delay_ms", 500)
    log_dir = cfg.get("general", {}).get("log_dir", "logs")
    version = cfg.get("general", {}).get("version", "")
    zmq_addr = cfg.get("tx", {}).get("zmq_addr", "tcp://127.0.0.1:52002")

    global tx_log
    if tx_log is None:
        tx_log = TXLog(log_dir, zmq_addr, version=version)

    sent = 0
    prev_was_cmd = False

    try:
        while not tx_abort.is_set():
            with tx_send_lock:
                if not tx_queue:
                    break
                item = tx_queue[0]
                tx_sending["idx"] = 0
                tx_sending["waiting"] = False

            await _send_queue_update()

            # Handle delay items
            if item["type"] == "delay":
                with tx_send_lock:
                    tx_sending["sent_at"] = 0
                    tx_sending["waiting"] = True
                prev_was_cmd = False
                remaining_ms = item["delay_ms"]
                while remaining_ms > 0 and not tx_abort.is_set():
                    await asyncio.sleep(0.1)
                    remaining_ms -= 100
                with tx_send_lock:
                    tx_sending["waiting"] = False
                if tx_abort.is_set():
                    break
                with tx_send_lock:
                    if tx_queue:
                        tx_queue.pop(0)
                    _renumber_queue()
                    _save_queue()
                continue

            # Inter-command delay (between consecutive cmds)
            if prev_was_cmd and default_delay > 0:
                with tx_send_lock:
                    tx_sending["waiting"] = True
                remaining_ms = default_delay
                while remaining_ms > 0 and not tx_abort.is_set():
                    await asyncio.sleep(0.1)
                    remaining_ms -= 100
                with tx_send_lock:
                    tx_sending["waiting"] = False
                if tx_abort.is_set():
                    break

            # Guard check
            if item.get("guard"):
                with tx_send_lock:
                    tx_sending["guarding"] = True
                tx_guard_ok.clear()
                await _tx_broadcast({
                    "type": "guard_confirm",
                    "item": {
                        "num": item.get("num", 0),
                        "cmd": item["cmd"],
                        "args": item["args"],
                        "dest": node_name(item["dest"]),
                    },
                })
                # Wait for approval or abort
                while not tx_guard_ok.is_set() and not tx_abort.is_set():
                    await asyncio.sleep(0.1)
                tx_guard_event.clear()
                with tx_send_lock:
                    tx_sending["guarding"] = False
                if tx_abort.is_set():
                    break

            # Build and send frame
            raw_cmd = item["raw_cmd"]
            csp_packet = csp.wrap(raw_cmd)
            if uplink_mode == "ASM+Golay" and _GOLAY_OK:
                payload = build_asm_golay_frame(csp_packet)
            else:
                ax25_frame = ax25.wrap(csp_packet)
                payload = build_ax25_gfsk_frame(ax25_frame)

            ok = send_pdu(sock, payload)
            if not ok:
                await _tx_broadcast({"type": "send_error", "error": "ZMQ send failed"})
                break

            with tx_send_lock:
                tx_sending["sent_at"] = time.time()
            tx_count += 1
            sent += 1

            # Log
            src, dest, echo, ptype_val = item["src"], item["dest"], item["echo"], item["ptype"]
            tx_log.write_command(tx_count, src, dest, echo, ptype_val,
                                item["cmd"], item["args"], raw_cmd, payload,
                                ax25, csp, uplink_mode=uplink_mode)

            # Append to history
            hist_entry = {
                "n": tx_count,
                "ts": datetime.now().strftime("%H:%M:%S"),
                "src": node_name(src),
                "dest": node_name(dest),
                "echo": node_name(echo),
                "ptype": ptype_name(ptype_val),
                "cmd": item["cmd"],
                "args": item["args"],
                "payload_len": len(payload),
            }
            tx_history.append(hist_entry)
            if len(tx_history) > MAX_HISTORY:
                del tx_history[:len(tx_history) - MAX_HISTORY]

            await _tx_broadcast({"type": "sent", "data": hist_entry})

            # Brief pause for UI flash, then pop
            await asyncio.sleep(0.5)
            with tx_send_lock:
                if tx_queue:
                    tx_queue.pop(0)
                tx_sending["sent_at"] = 0
                _renumber_queue()
                _save_queue()
            prev_was_cmd = True

    finally:
        # Cleanup
        zmq_cleanup(monitor, PUB_STATUS, "OFFLINE", sock, ctx)
        with tx_send_lock:
            _save_queue()
            tx_sending.update(active=False, idx=-1, total=0, guarding=False, sent_at=0, waiting=False)

        remaining = len(tx_queue)
        if tx_abort.is_set():
            await _tx_broadcast({"type": "send_aborted", "sent": sent, "remaining": remaining})
        else:
            await _tx_broadcast({"type": "send_complete", "sent": sent})

        await _send_queue_update()
        await _tx_broadcast({"type": "history", "items": tx_history[-MAX_HISTORY:]})


# ── TX WebSocket Endpoint ─────────────────────────────────────────

@app.websocket("/ws/tx")
async def ws_tx(websocket: WebSocket):
    """TX WebSocket: queue management, send control, and live updates."""
    await websocket.accept()

    # Send current state on connect
    try:
        await websocket.send_text(json.dumps({
            "type": "queue_update",
            "items": _queue_items_json(),
            "summary": _queue_summary(),
            "sending": tx_sending.copy(),
        }))
        await websocket.send_text(json.dumps({
            "type": "history",
            "items": tx_history[-MAX_HISTORY:],
        }))
    except Exception:
        return

    with tx_lock:
        tx_clients.append(websocket)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "error": "invalid JSON"}))
                continue

            action = msg.get("action", "")

            if action == "queue":
                # Parse CLI input and add to queue
                line = msg.get("input", "").strip()
                if not line:
                    await websocket.send_text(json.dumps({"type": "error", "error": "empty input"}))
                    continue
                try:
                    parts = line.split()
                    candidate = parts[0].lower()
                    defn = cmd_defs.get(candidate)
                    if defn and not defn.get("rx_only") and defn.get("dest") is not None:
                        cmd_id = candidate
                        args = " ".join(parts[1:])
                        src, dest = protocol.GS_NODE, defn["dest"]
                        echo, ptype_val = defn["echo"], defn["ptype"]
                    else:
                        src, dest, echo, ptype_val, cmd_id, args = parse_cmd_line(line)
                    # Validate
                    valid, issues = validate_args(cmd_id, args, cmd_defs)
                    if not valid:
                        await websocket.send_text(json.dumps({
                            "type": "error", "error": "; ".join(issues),
                        }))
                        continue
                    item = _make_cmd(src, dest, echo, ptype_val, cmd_id, args)
                    tx_queue.append(item)
                    _renumber_queue()
                    _save_queue()
                    await _send_queue_update()
                except ValueError as e:
                    await websocket.send_text(json.dumps({"type": "error", "error": str(e)}))

            elif action == "queue_built":
                # From visual builder — fields already resolved
                try:
                    src = resolve_node(str(msg.get("src", "GS")))
                    dest = resolve_node(str(msg["dest"]))
                    echo = resolve_node(str(msg.get("echo", "NONE")))
                    ptype_val = resolve_ptype(str(msg.get("ptype", "CMD")))
                    if None in (src, dest, echo, ptype_val):
                        raise ValueError("unresolvable node/ptype")
                    cmd_id = msg["cmd"].lower()
                    args = msg.get("args", "")
                    guard = bool(msg.get("guard", False))
                    valid, issues = validate_args(cmd_id, args, cmd_defs)
                    if not valid:
                        await websocket.send_text(json.dumps({
                            "type": "error", "error": "; ".join(issues),
                        }))
                        continue
                    item = _make_cmd(src, dest, echo, ptype_val, cmd_id, args, guard=guard)
                    tx_queue.append(item)
                    _renumber_queue()
                    _save_queue()
                    await _send_queue_update()
                except (ValueError, KeyError) as e:
                    await websocket.send_text(json.dumps({"type": "error", "error": str(e)}))

            elif action == "delete":
                idx = msg.get("index")
                if isinstance(idx, int) and 0 <= idx < len(tx_queue):
                    tx_queue.pop(idx)
                    _renumber_queue()
                    _save_queue()
                    await _send_queue_update()

            elif action == "clear":
                tx_queue.clear()
                _save_queue()
                await _send_queue_update()

            elif action == "undo":
                if tx_queue:
                    tx_queue.pop()
                    _renumber_queue()
                    _save_queue()
                    await _send_queue_update()

            elif action == "guard":
                idx = msg.get("index")
                if isinstance(idx, int) and 0 <= idx < len(tx_queue):
                    item = tx_queue[idx]
                    if item["type"] == "cmd":
                        item["guard"] = not item.get("guard", False)
                        _save_queue()
                        await _send_queue_update()

            elif action == "reorder":
                order = msg.get("order", [])
                if isinstance(order, list) and len(order) == len(tx_queue):
                    try:
                        new_queue = [tx_queue[i] for i in order]
                        tx_queue[:] = new_queue
                        _renumber_queue()
                        _save_queue()
                        await _send_queue_update()
                    except (IndexError, TypeError):
                        pass

            elif action == "add_delay":
                delay_ms = msg.get("delay_ms", 1000)
                idx = msg.get("index")  # optional insert position
                item = _make_delay(int(delay_ms))
                if isinstance(idx, int) and 0 <= idx <= len(tx_queue):
                    tx_queue.insert(idx, item)
                else:
                    tx_queue.append(item)
                _renumber_queue()
                _save_queue()
                await _send_queue_update()

            elif action == "edit_delay":
                idx = msg.get("index")
                delay_ms = msg.get("delay_ms")
                if (isinstance(idx, int) and 0 <= idx < len(tx_queue)
                        and tx_queue[idx]["type"] == "delay"
                        and isinstance(delay_ms, (int, float))):
                    tx_queue[idx]["delay_ms"] = int(delay_ms)
                    _save_queue()
                    await _send_queue_update()

            elif action == "send":
                with tx_send_lock:
                    if tx_sending["active"]:
                        await websocket.send_text(json.dumps({
                            "type": "error", "error": "send already in progress",
                        }))
                        continue
                    if not tx_queue:
                        await websocket.send_text(json.dumps({
                            "type": "error", "error": "queue is empty",
                        }))
                        continue
                    tx_abort.clear()
                    tx_guard_event.clear()
                    tx_guard_ok.clear()
                    tx_sending.update(active=True, total=len(tx_queue), idx=0,
                                      guarding=False, sent_at=0, waiting=False)
                asyncio.create_task(_run_send())

            elif action == "abort":
                tx_abort.set()

            elif action == "guard_approve":
                tx_guard_ok.set()

            elif action == "guard_reject":
                tx_abort.set()

    except WebSocketDisconnect:
        pass
    finally:
        with tx_lock:
            if websocket in tx_clients:
                tx_clients.remove(websocket)


# =====================================================================
#  STARTUP
# =====================================================================

@app.on_event("startup")
async def on_startup():
    """Start RX ZMQ thread, broadcast coroutine, and load TX queue."""
    global tx_queue
    tx_queue = _load_queue()
    _renumber_queue()

    t = threading.Thread(target=_rx_thread, daemon=True)
    t.start()
    asyncio.create_task(_rx_broadcast())


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
