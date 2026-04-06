"""
MAV_TX -- MAVERIC Command Terminal (Textual Dashboard)

STATUS: MAVERIC-only legacy. Backup Textual TUI for TX commanding.
Not on the platform/adapter migration path. The web UI (MAV_WEB.py)
is the primary operational interface.

Author:  Irfan Annuar - USC ISI SERC
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure mav_gss_lib is importable when running from backup_control/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Input

import mav_gss_lib.protocol as protocol
from mav_gss_lib.protocol import (
    init_nodes, node_label, build_cmd_raw, AX25Config, CSPConfig,
    load_command_defs, validate_args, parse_cmd_line,
)
from mav_gss_lib.transport import (init_zmq_pub, send_pdu,
                                   poll_monitor, PUB_STATUS, zmq_cleanup)
from mav_gss_lib.logging import TXLog
from mav_gss_lib.tui_common import (StatusMessage, SplashScreen,
                                    Hints, HelpScreen, ConfigScreen, ImportScreen, ConfirmScreen,
                                    MavAppBase, dispatch_common, TS_SHORT,
                                    STATUS_BRIEF, STATUS_NORMAL, STATUS_LONG, STATUS_STARTUP)
from mav_gss_lib.config import (
    load_gss_config, apply_ax25, apply_csp, ax25_handle_msg, csp_handle_msg,
    get_command_defs_path,
    get_generated_commands_dir,
    save_gss_config, update_cfg_from_state,
)
try:
    from mav_gss_lib.golay import build_asm_golay_frame, _GR_RS_OK
    _GOLAY_OK = _GR_RS_OK
except ImportError:
    _GOLAY_OK = False
from mav_gss_lib.ax25 import build_ax25_gfsk_frame
from mav_gss_lib.tui_tx import (
    TxHeader, TxQueue, SentHistory, TxStatusBar,
    HELP_LINES, CONFIG_FIELDS, config_get_values, config_apply,
    tx_help_info, build_guard_content,
)

CFG = load_gss_config()
init_nodes(CFG)
VERSION       = CFG["general"]["version"]
ZMQ_ADDR      = CFG["tx"]["zmq_addr"]
LOG_DIR       = CFG["general"]["log_dir"]
MAX_RS_PAYLOAD = 223
CMD_DEFS_PATH = get_command_defs_path(CFG)
FREQUENCY     = CFG["tx"]["frequency"]
TX_DELAY_MS   = CFG["tx"]["delay_ms"]
UPLINK_MODE   = CFG["tx"].get("uplink_mode", "AX.25")
MISSION_NAME  = CFG["general"].get("mission_name", "Mission")
TX_TITLE      = CFG["general"].get("tx_title", f"{MISSION_NAME} Uplink")
MAX_HISTORY   = 500
MAX_CMD_HISTORY = 500
QUEUE_FILE = os.path.join(LOG_DIR, ".pending_queue.jsonl")
IMPORT_DIR = str(get_generated_commands_dir(CFG))

# -- Queue item helpers -------------------------------------------------------

def _make_cmd(src, dest, echo, ptype, cmd, args, guard=False):
    """Create a command queue item dict with raw_cmd built from fields."""
    raw_cmd = build_cmd_raw(dest, cmd, args, echo=echo, ptype=ptype, origin=src)
    return {"type": "cmd", "src": src, "dest": dest, "echo": echo, "ptype": ptype,
            "cmd": cmd, "args": args, "guard": guard, "raw_cmd": raw_cmd}

def _renumber_queue(tx_queue):
    """Assign sequential numbers to cmd items in the queue."""
    n = 0
    for item in tx_queue:
        if item["type"] == "cmd":
            n += 1
            item["num"] = n

def _make_delay(delay_ms):
    """Create a delay queue item dict."""
    return {"type": "delay", "delay_ms": delay_ms}

# -- Queue persistence --------------------------------------------------------

def _item_to_json(item):
    """Serialize a queue item dict to a JSON-safe dict (no raw_cmd)."""
    d = {k: v for k, v in item.items() if k != "raw_cmd"}
    if d["type"] == "cmd" and not d.get("guard"):
        d.pop("guard", None)
    return d

def _json_to_items(d):
    """Deserialize a JSON dict into a queue item."""
    if d["type"] == "delay":
        return [_make_delay(d.get("delay_ms", 0))]
    return [_make_cmd(d["src"], d["dest"], d["echo"], d["ptype"],
                      d["cmd"], d.get("args", ""), bool(d.get("guard")))]

def _array_to_items(arr, kvs=None):
    """Convert a JSON array [src, dest, echo, ptype, cmd, ?args]
    into a cmd item. Optional kvs dict for hybrid format overrides (guard)."""
    if len(arr) < 5:
        raise ValueError("array too short: need at least [src, dest, echo, ptype, cmd]")
    src_s, dest_s, echo_s, ptype_s, cmd = arr[:5]
    args = arr[5] if len(arr) > 5 else ""
    guard = bool(kvs.get("guard", False)) if kvs else False
    src   = protocol.resolve_node(str(src_s))
    dest  = protocol.resolve_node(str(dest_s))
    echo  = protocol.resolve_node(str(echo_s))
    ptype = protocol.resolve_ptype(str(ptype_s))
    if None in (src, dest, echo, ptype):
        raise ValueError("unresolvable node/ptype in array entry")
    cmd = cmd.lower()
    return [_make_cmd(src, dest, echo, ptype, cmd, args, guard)]

def _save_queue(tx_queue):
    """Atomically write the full TX queue to .pending_queue.jsonl."""
    if not tx_queue:
        try: os.remove(QUEUE_FILE)
        except FileNotFoundError: pass
        return
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(QUEUE_FILE) or ".")
    try:
        with os.fdopen(fd, "w") as f:
            for item in tx_queue: f.write(json.dumps(_item_to_json(item)) + "\n")
        os.replace(tmp, QUEUE_FILE)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise

def _append_queue(item):
    """Append a single queue item to .pending_queue.jsonl."""
    with open(QUEUE_FILE, "a") as f:
        f.write(json.dumps(_item_to_json(item)) + "\n")

def _normalize_jsonl_line(line):
    """Normalize a JSONL line: strip comments, fix hybrid array+dict syntax."""
    import re
    line = line.strip()
    if not line or line.startswith("//"):
        return None
    # Strip inline // comments (outside strings)
    in_str, escaped, out = False, False, []
    for i, ch in enumerate(line):
        if escaped: escaped = False; out.append(ch); continue
        if ch == '\\' and in_str: escaped = True; out.append(ch); continue
        if ch == '"': in_str = not in_str; out.append(ch); continue
        if not in_str and ch == '/' and i + 1 < len(line) and line[i + 1] == '/':
            break
        out.append(ch)
    line = "".join(out).rstrip().rstrip(",")
    if not line:
        return None
    if line.startswith("["):
        kv_pattern = re.compile(r',\s*"(\w+)"\s*:\s*(true|false|null|\d+(?:\.\d+)?|"[^"]*")')
        kvs = {}
        for m in kv_pattern.finditer(line):
            key = m.group(1)
            raw = m.group(2)
            if raw == "true": kvs[key] = True
            elif raw == "false": kvs[key] = False
            elif raw == "null": kvs[key] = None
            elif raw.startswith('"'): kvs[key] = raw[1:-1]
            elif "." in raw: kvs[key] = float(raw)
            else: kvs[key] = int(raw)
        if kvs:
            cleaned = kv_pattern.sub("", line)
            cleaned = cleaned.rstrip().rstrip(",").rstrip()
            if not cleaned.endswith("]"):
                cleaned = cleaned.rstrip(",").rstrip() + "]"
            try:
                arr = json.loads(cleaned)
                return ("hybrid", arr, kvs)
            except json.JSONDecodeError:
                pass
    return ("raw", line)

def _parse_jsonl_file(path):
    """Parse a JSONL file of queue items (dict, array, or hybrid format).
    Supports // comments, hybrid arrays, and legacy 9-tuple dicts.
    Returns (items_list, skipped_count). Raises FileNotFoundError if missing."""
    items, skipped = [], 0
    with open(path) as f:
        for line in f:
            result = _normalize_jsonl_line(line)
            if result is None: continue
            try:
                if result[0] == "hybrid":
                    _, arr, kvs = result
                    items.extend(_array_to_items(arr, kvs))
                else:
                    obj = json.loads(result[1])
                    if isinstance(obj, list):
                        items.extend(_array_to_items(obj))
                    else:
                        items.extend(_json_to_items(obj))
            except (json.JSONDecodeError, KeyError, ValueError):
                skipped += 1
    return items, skipped

def _load_queue():
    """Load the persisted TX queue from .pending_queue.jsonl, if it exists."""
    try:
        return _parse_jsonl_file(QUEUE_FILE)
    except FileNotFoundError:
        return [], 0

# -- Import from generated_commands/ ------------------------------------------

def _list_import_files():
    """Return .jsonl files in IMPORT_DIR sorted newest-first by mtime."""
    try:
        files = [f for f in os.listdir(IMPORT_DIR) if f.endswith(".jsonl")]
    except FileNotFoundError:
        return []
    files.sort(key=lambda f: os.path.getmtime(os.path.join(IMPORT_DIR, f)), reverse=True)
    return files

def _frame_overhead(state):
    """Total protocol overhead (CSP + optional AX.25) for the current uplink mode."""
    return state.csp.overhead() if state.uplink_mode == "ASM+Golay" else state.csp.overhead() + state.ax25.overhead()

def _perform_undo(state):
    """Pop the last TX queue item and persist. Returns True if an item was removed."""
    if state.tx_queue:
        r = state.tx_queue.pop(); _save_queue(state.tx_queue)
        _renumber_queue(state.tx_queue); state._queue_dirty = True
        if state.queue_sel >= len(state.tx_queue): state.queue_sel = len(state.tx_queue) - 1
        label = r["cmd"] if r["type"] == "cmd" else f"{r['delay_ms']}ms"
        state.status.set(f"Removed: {label} ({len(state.tx_queue)} left)", STATUS_BRIEF)
        return True
    state.status.set("Queue is empty", STATUS_BRIEF)
    return False

def _import_file(state, filename):
    """Import items from a JSONL file into the TX queue.
    Returns (loaded_count, skipped_count) or raises FileNotFoundError."""
    new_items, skipped = _parse_jsonl_file(os.path.join(IMPORT_DIR, filename))
    overhead = _frame_overhead(state)
    accepted = []
    for item in new_items:
        if item["type"] == "cmd" and len(item["raw_cmd"]) + overhead > MAX_RS_PAYLOAD:
            skipped += 1
            continue
        state.tx_queue.append(item)
        _append_queue(item)
        accepted.append(item)
    if accepted:
        _renumber_queue(state.tx_queue); state._queue_dirty = True
    return len(accepted), skipped

# -- State (widgets read directly) --------------------------------------------

@dataclass
class TxState:
    """All mutable state for the TX uplink command dashboard.

    Tracks the command queue, send thread status, sent history, command
    input history, and config modal state. The queue is persisted to
    .pending_queue.jsonl across sessions. Widgets read this dataclass
    directly via a shared reference.
    """
    csp: CSPConfig
    ax25: AX25Config
    cmd_defs: dict
    tx_queue: list
    history: list
    tx_log: TXLog
    tx_count: int = 0
    session_start: float = 0.0
    freq: str = ""
    zmq_addr_disp: str = ""
    zmq_status: str = "OFFLINE"
    tx_delay_ms: int = 0
    cmd_history: deque = field(default_factory=lambda: deque(maxlen=MAX_CMD_HISTORY))
    cmd_hist_idx: int = -1
    cmd_hist_save: str = ""
    queue_scroll: int = 0
    hist_scroll: int = 0
    send_abort: threading.Event = field(default_factory=threading.Event)
    send_guard: threading.Event = field(default_factory=threading.Event)      # worker sets: guard reached
    send_guard_ok: threading.Event = field(default_factory=threading.Event)   # UI sets: user confirmed
    send_lock: threading.Lock = field(default_factory=threading.Lock)
    sending: dict = field(default_factory=lambda: {"active": False, "idx": -1, "total": 0, "guarding": False, "sent_at": 0.0, "delay_end": 0.0, "waiting": False})
    status: StatusMessage = field(default_factory=StatusMessage)
    uplink_mode: str = "AX.25"
    version: str = ""
    schema_count: int = 0
    schema_path: str = ""
    tx_title: str = "Mission Uplink"
    queue_sel: int = -1       # selected row in queue (-1 = none)
    _queue_dirty: bool = False
    _queue_save: bool = False  # trigger persistence from widget delay edits
    _hist_dirty: bool = False
    _send_thread: threading.Thread = None

# -- Send thread --------------------------------------------------------------

def _timed_wait(state, duration_ms):
    """Sleep with abort check, updating sending state for UI countdown.
    Returns True if aborted."""
    if duration_ms <= 0: return False
    with state.send_lock:
        state.sending["waiting"] = True
        state.sending["delay_end"] = time.time() + duration_ms / 1000.0
    aborted = state.send_abort.wait(timeout=duration_ms / 1000.0)
    with state.send_lock:
        state.sending["waiting"] = False
        state.sending["delay_end"] = 0.0
    return aborted

def _send_worker(state, total, default_delay_ms, sock):
    """Background thread: process queue items from the front. Removes each after processing."""
    sent = 0
    prev_was_cmd = False
    while not state.send_abort.is_set():
        with state.send_lock:
            if not state.tx_queue:
                break
            item = state.tx_queue[0]
            state.sending["idx"] = 0
            state.sending["waiting"] = False
            state.sending["delay_end"] = 0.0

        if item["type"] == "delay":
            with state.send_lock: state.sending["sent_at"] = 0.0
            prev_was_cmd = False
            if _timed_wait(state, item["delay_ms"]): break
            with state.send_lock:
                if state.tx_queue: state.tx_queue.pop(0)
                state._queue_dirty = True
            continue

        # cmd item — apply default delay if two cmds are adjacent
        if prev_was_cmd and _timed_wait(state, default_delay_ms): break

        if item.get("guard"):
            with state.send_lock: state.sending["guarding"] = True
            state.send_guard_ok.clear()
            state.send_guard.set()
            while not state.send_guard_ok.is_set():
                if state.send_abort.wait(timeout=0.1): break
            state.send_guard.clear()
            with state.send_lock: state.sending["guarding"] = False
            if state.send_abort.is_set(): break

        raw_cmd = item["raw_cmd"]
        csp_packet = state.csp.wrap(raw_cmd)
        if state.uplink_mode == "ASM+Golay":
            payload = build_asm_golay_frame(csp_packet)
        else:
            ax25_frame = state.ax25.wrap(csp_packet)
            payload = build_ax25_gfsk_frame(ax25_frame)
        if not send_pdu(sock, payload):
            state.status.set("ZMQ send error — aborting send", STATUS_LONG); break
        with state.send_lock:
            state.sending["sent_at"] = time.time()
        state.tx_count += 1; sent += 1
        src, dest, echo, ptype = item["src"], item["dest"], item["echo"], item["ptype"]
        state.tx_log.write_command(state.tx_count, src, dest, echo, ptype,
                                   item["cmd"], item["args"], raw_cmd, payload,
                                   state.ax25, state.csp, uplink_mode=state.uplink_mode)
        with state.send_lock:
            state.history.append({"n": state.tx_count, "ts": datetime.now().strftime(TS_SHORT),
                "src": src, "dest": dest, "cmd": item["cmd"], "args": item["args"], "echo": echo,
                "ptype": ptype, "payload_len": len(payload), "csp_enabled": state.csp.enabled})
            state.hist_scroll = len(state.history) - 1
        # Flash for 1s then remove (abort-aware)
        state.send_abort.wait(timeout=1.0)
        with state.send_lock:
            if state.tx_queue: state.tx_queue.pop(0)
            state.sending["sent_at"] = 0.0
            state._queue_dirty = True
        prev_was_cmd = True

    with state.send_lock:
        _save_queue(state.tx_queue)
        if len(state.history) > MAX_HISTORY: del state.history[:len(state.history) - MAX_HISTORY]
        state.hist_scroll = max(0, len(state.history) - 1)
        state.queue_scroll = 0
        state.queue_sel = min(state.queue_sel, len(state.tx_queue) - 1)
        state._queue_dirty = True
    remaining = len(state.tx_queue)
    if state.send_abort.is_set():
        state.status.set(f"Aborted: sent {sent}, {remaining} remain", STATUS_LONG)
    else:
        state.status.set(f"Sent {sent} command{'s' if sent != 1 else ''}")
    with state.send_lock:
        state.sending.update(active=False, idx=-1, sent_at=0.0, waiting=False, delay_end=0.0, guarding=False)

def _start_send(state, sock):
    """Start the send worker thread if queue is non-empty and no send is active."""
    with state.send_lock:
        if state.sending["active"]: state.status.set("Send already in progress", STATUS_BRIEF); return
        if not state.tx_queue: state.status.set("Nothing queued", STATUS_BRIEF); return
        state.send_abort.clear()
        state.send_guard.clear()
        state.send_guard_ok.clear()
        total = len(state.tx_queue)
        state.sending.update(active=True, total=total, idx=0)
    state.queue_scroll = 0
    state._send_thread = threading.Thread(target=_send_worker, args=(state, total, state.tx_delay_ms, sock), daemon=True)
    state._send_thread.start()

# -- Command dispatch ---------------------------------------------------------

def _cmd_mode(state, line):
    """Show or switch uplink encoding mode."""
    arg = line[4:].strip() if len(line) > 4 else ""
    if not arg:
        state.status.set(f"Uplink mode: {state.uplink_mode}", STATUS_NORMAL)
    elif arg.upper() in ("AX.25", "AX25"):
        state.uplink_mode = "AX.25"
        state.status.set("Uplink mode: AX.25", STATUS_NORMAL)
    elif arg.upper() in ("ASM+GOLAY", "GOLAY", "ASM"):
        if not _GOLAY_OK:
            state.status.set("libfec not found — cannot use ASM+GOLAY", STATUS_NORMAL)
        else:
            state.uplink_mode = "ASM+Golay"
            state.status.set("Uplink mode: ASM+GOLAY", STATUS_NORMAL)
    else:
        state.status.set("mode [AX.25 | ASM+GOLAY]", STATUS_NORMAL)

def _queue_command(state, line):
    """Parse a command line and add to the TX queue.

    Supports two input forms:
      Shorthand:  CMD [ARGS]         — uses schema routing defaults (dest required in schema)
      Full form:  [SRC] DEST ECHO TYPE CMD [ARGS]  — explicit routing, always works
    """
    parts = line.split()
    if not parts:
        return True
    candidate = parts[0].lower()

    # Shorthand: first token is a known TX command with a dest default
    defn = state.cmd_defs.get(candidate)
    if defn and not defn.get("rx_only") and defn.get("dest") is not None:
        cmd = candidate
        args = " ".join(parts[1:])
        src, dest = protocol.GS_NODE, defn["dest"]
        echo, ptype = defn["echo"], defn["ptype"]
    else:
        # Full-form parsing (also handles known commands without routing defaults)
        try:
            src, dest, echo, ptype, cmd, args = parse_cmd_line(line)
        except ValueError as e:
            if defn and defn.get("rx_only"):
                state.status.set(f"Rejected: '{candidate}' is receive-only", STATUS_NORMAL)
            else:
                state.status.set(f"Bad command: {e}", STATUS_NORMAL)
            return True

    valid, issues = validate_args(cmd, args, state.cmd_defs)
    if not valid:
        state.status.set(f"Rejected: {issues[0]}", STATUS_NORMAL); return True
    if state.cmd_defs and cmd not in state.cmd_defs:
        state.status.set(f"Rejected: '{cmd}' not in schema", STATUS_NORMAL); return True
    item = _make_cmd(src, dest, echo, ptype, cmd, args)
    if len(item["raw_cmd"]) + _frame_overhead(state) > MAX_RS_PAYLOAD:
        state.status.set("Command too large for RS payload", STATUS_NORMAL); return True
    state.tx_queue.append(item); _append_queue(item)
    _renumber_queue(state.tx_queue); state._queue_dirty = True
    src_tag = f"{node_label(src)}→" if src != protocol.GS_NODE else ""
    state.status.set(f"Queued: {src_tag}{node_label(dest)} E:{echo} "
                     f"{protocol.PTYPE_NAMES.get(ptype,'?')} {cmd} {args} ({len(item['raw_cmd'])}B)", STATUS_BRIEF)
    return True

def _dispatch_tx_command(state, line, sock):
    """Dispatch a TX command: try common → exact → prefix → queue as uplink command."""
    cl = line.lower()
    common = dispatch_common(state, cl)
    if isinstance(common, tuple) and common[0] == "tag":
        tag = common[1]
        if not tag.strip():
            state.status.set("Usage: tag <name>", STATUS_NORMAL); return True
        state.tx_log.rename(tag)
        state.status.set(f"Log tagged: {tag}", STATUS_BRIEF)
        return True
    if isinstance(common, tuple) and common[0] == "log":
        tag = common[1]
        state.tx_log.write_summary(state.tx_count, state.session_start)
        state.tx_log.new_session(tag)
        state.tx_count = 0; state.session_start = time.time()
        state.status.set(f"New log: {os.path.basename(state.tx_log.text_path)}", STATUS_BRIEF)
        return True
    if common is not None:
        return common
    if cl == "send": return "confirm_send"
    if cl == "clear": return "confirm_clear"
    if cl in ("undo", "pop"):
        _perform_undo(state); return True
    if cl == "hclear":
        if state.history:
            state.status.set(f"Cleared {len(state.history)} entries", STATUS_BRIEF)
            state.history.clear(); state.hist_scroll = 0; state._hist_dirty = True
        else:
            state.status.set("History already empty", STATUS_BRIEF)
        return True
    if cl == "imp": return "open_import"
    if cl == "nodes":
        state.status.set("Nodes: " + ", ".join(
            f"{n}={protocol.NODE_NAMES[n]}" for n in sorted(protocol.NODE_NAMES)), STATUS_LONG)
        return True
    if cl == "csp" or cl.startswith("csp "):
        state.status.set(csp_handle_msg(state.csp, line[3:].strip() if len(line) > 3 else ""), STATUS_NORMAL)
        return True
    if cl == "ax25" or cl.startswith("ax25 "):
        state.status.set(ax25_handle_msg(state.ax25, line[4:].strip() if len(line) > 4 else ""), STATUS_NORMAL)
        return True
    if cl == "mode" or cl.startswith("mode "):
        _cmd_mode(state, line); return True
    if cl.startswith("wait"):
        arg = cl[4:].strip()
        try:
            ms = int(arg) if arg else state.tx_delay_ms
        except ValueError:
            state.status.set("Usage: wait [ms]", STATUS_NORMAL); return True
        item = _make_delay(max(0, ms))
        state.tx_queue.append(item); _append_queue(item); state._queue_dirty = True
        state.status.set(f"Queued delay: {ms/1000:.1f}s", STATUS_BRIEF)
        return True
    return _queue_command(state, line)

# =============================================================================
#  APP
# =============================================================================

class MavTxApp(MavAppBase):
    """Textual app for uplink command queuing and transmission.

    Queues operator commands, validates against maveric_commands.yml
    schema, and publishes encoded frames via ZMQ to GNU Radio.
    Supports AX.25 and ASM+Golay uplink modes, queue persistence,
    command import from generated_commands/, and async send with abort.
    """
    CSS = """
    Screen { background: black; padding-right: 1; }
    SplashScreen { background: rgba(0, 0, 0, 0.5); }
    SplashScreen * { background: transparent; }
    #main-area { height: 1fr; }
    #content-area { width: 1fr; }
    #bottom-bar { dock: bottom; height: 3; }
    #tx-input { height: 1; border: none; padding: 0; }
    #tx-input:focus .input--cursor { background: #00bfff; color: #000000; }
    TxQueue { border-top: solid #555555; border-left: solid black; border-right: solid black; border-bottom: solid black; }
    TxQueue:focus { border: solid #00bfff; }
    SentHistory { border-top: solid #555555; border-left: solid black; border-right: solid black; border-bottom: solid black; }
    SentHistory:focus { border: solid #00bfff; }
    """
    _WIDGET_QUERY = "TxHeader, TxQueue, SentHistory, TxStatusBar"
    _INPUT_ID = "tx-input"
    BINDINGS = [
        Binding("ctrl+c", "quit_or_close", "Quit", priority=True),
        Binding("escape", "close_or_cancel", "Close", show=False),
        Binding("ctrl+s", "send_queue", "Send", show=False),
        Binding("ctrl+z", "undo_queue", "Undo", show=False),
        Binding("ctrl+x", "clear_queue", "Clear", show=False, priority=True),
        Binding("up", "history_prev", "Up", show=False),
        Binding("down", "history_next", "Down", show=False),
        Binding("tab", "focus_next_widget", "Tab", show=False),
    ]
    _FOCUS_CYCLE = ["#tx-input", "#tx-queue", "#sent-history"]

    def __init__(self, show_splash=True):
        super().__init__()
        self._show_splash = show_splash
        csp, ax25 = CSPConfig(), AX25Config()
        apply_csp(CFG, csp); apply_ax25(CFG, ax25)
        cmd_defs, self._schema_warning = load_command_defs(CMD_DEFS_PATH)
        self._zmq_ctx, self._sock, self._zmq_monitor = init_zmq_pub(ZMQ_ADDR)
        tx_queue, q_skipped = _load_queue()
        _renumber_queue(tx_queue)
        self.state = TxState(
            csp=csp, ax25=ax25, cmd_defs=cmd_defs, tx_queue=tx_queue, history=[],
            tx_log=TXLog(LOG_DIR, ZMQ_ADDR, version=VERSION), session_start=time.time(),
            freq=FREQUENCY, zmq_addr_disp=ZMQ_ADDR, tx_delay_ms=TX_DELAY_MS,
            uplink_mode=UPLINK_MODE,
            version=VERSION, schema_count=len(cmd_defs), schema_path=CMD_DEFS_PATH,
            tx_title=TX_TITLE,
        )
        if tx_queue or q_skipped:
            parts = [f"Restored {len(tx_queue)} queued command{'s' if len(tx_queue)!=1 else ''}"]
            if q_skipped: parts.append(f" ({q_skipped} skipped — corrupt)")
            self.state.status.set("".join(parts), STATUS_LONG)
        if self._schema_warning: self.state.status.set(f"SCHEMA: {self._schema_warning}", STATUS_STARTUP)

    def compose(self) -> ComposeResult:
        s = self.state
        yield TxHeader(s, id="tx-header")
        with Horizontal(id="main-area"):
            with Vertical(id="content-area"):
                yield TxQueue(s, id="tx-queue")
                yield SentHistory(s, id="sent-history")
        with Vertical(id="bottom-bar"):
            yield TxStatusBar(s, id="status-bar")
            yield Input(id="tx-input")
            yield Hints(self._hint_text)

    def on_mount(self):
        if self._show_splash:
            ax, cs = CFG["ax25"], CFG["csp"]
            self.push_screen(SplashScreen(subtitle=f"{TX_TITLE}  v{VERSION}",
                config_lines=[("Config", "maveric_gss.yml"), ("ZMQ PUB", ZMQ_ADDR),
                    ("Frequency", FREQUENCY), ("Uplink Mode", UPLINK_MODE), ("TX Delay", f"{TX_DELAY_MS} ms"),
                    ("AX.25", f"GS:{ax['src_call']}-{ax['src_ssid']} -> SAT:{ax['dest_call']}-{ax['dest_ssid']}"),
                    ("CSP", f"Prio:{cs['priority']} Src:{cs['source']} Dest:{cs['destination']}"),
                    ("Commands", CMD_DEFS_PATH), ("Log", f"{LOG_DIR}/text")]))
        self.set_interval(1/60, self._tick)
        self._last_header_sec = -1
        self._last_send_idx = -1
        self._guard_shown = False
        self.query_one("#tx-input").focus()

    def _tick(self):
        s = self.state
        # Thread watchdog: detect dead send thread with active flag stuck
        if s._send_thread is not None and not s._send_thread.is_alive():
            with s.send_lock:
                if s.sending["active"]:
                    remaining = len(s.tx_queue)
                    s.sending.update(active=False, idx=-1, sent_at=0.0, waiting=False, delay_end=0.0, guarding=False)
                    s.status.set(f"SEND THREAD DIED — {remaining} in queue", STATUS_LONG)
                    print("WARNING: TX send thread died unexpectedly", file=sys.stderr)
            s._send_thread = None
        if s.tx_log and not s.tx_log._writer.is_alive() and not getattr(s, '_log_dead', False):
            s._log_dead = True
            s.status.set("TX LOG WRITER DEAD — logging stopped", STATUS_LONG)
            print("WARNING: TX log writer thread died", file=sys.stderr)
        old_zmq = s.zmq_status
        s.zmq_status = poll_monitor(self._zmq_monitor, PUB_STATUS, s.zmq_status)
        status_dirty = s.status.check_expiry() or (s.zmq_status != old_zmq)
        # Detect send-thread progress (idx changes while sending)
        with s.send_lock:
            cur_idx = s.sending["idx"]
            send_active = s.sending["active"]
        send_dirty = (cur_idx != self._last_send_idx)
        self._last_send_idx = cur_idx
        # Guard: show confirmation dialog when send worker is waiting
        if s.send_guard.is_set() and not self._guard_shown:
            self._guard_shown = True
            idx = s.sending["idx"]
            total = s.sending["total"]
            item = s.tx_queue[idx] if 0 <= idx < len(s.tx_queue) else None
            if item and item["type"] == "cmd":
                cmd_name = item["cmd"]
                num = item.get('num', idx + 1)
                content = build_guard_content(item, num, total)
            else:
                cmd_name, content = "?", None
            self.push_screen(
                ConfirmScreen("Send guarded command?", "Send", caution=True, content=content),
                self._on_guard_done)
        if not s.send_guard.is_set():
            self._guard_shown = False
        # Selective refresh: only redraw widgets whose data actually changed
        now_sec = int(time.time())
        zmq_offline = s.zmq_status != "ONLINE"
        if now_sec != self._last_header_sec or status_dirty or zmq_offline:
            self._last_header_sec = now_sec
            self.query_one("#tx-header").refresh()
        if s._queue_save:
            s._queue_save = False; _renumber_queue(s.tx_queue); _save_queue(s.tx_queue)
        if s._queue_dirty or send_active:
            s._queue_dirty = False
            self.query_one("#tx-queue").refresh()
        if s._hist_dirty or send_active:
            s._hist_dirty = False
            self.query_one("#sent-history").refresh()
        if status_dirty or send_dirty:
            self.query_one("#status-bar").refresh()
            self.query_one("Hints").refresh()

    def _on_guard_done(self, confirmed):
        s = self.state
        if confirmed:
            s.send_guard_ok.set()
        else:
            s.send_abort.set()
        self._act()

    def action_quit_or_close(self):
        s = self.state
        with s.send_lock:
            active = s.sending["active"]
        if active: s.send_abort.set(); s.status.set("Aborting send...", STATUS_BRIEF); self._act(); return
        self._cleanup(); self.exit()

    def action_close_or_cancel(self):
        s = self.state
        with s.send_lock:
            active = s.sending["active"]
        if active: s.send_abort.set(); s.status.set("Aborting send...", STATUS_BRIEF)
        self._act()

    def action_send_queue(self):
        s = self.state
        if not s.tx_queue: s.status.set("Nothing queued", STATUS_BRIEF); self._act(); return
        with s.send_lock:
            active = s.sending["active"]
        if active: s.status.set("Send already in progress", STATUS_BRIEF); self._act(); return
        n = len(s.tx_queue)
        def _on_confirm(confirmed):
            if confirmed: _start_send(self.state, self._sock); self._act()
        cmds = sum(1 for e in s.tx_queue if e["type"] == "cmd")
        guards = sum(1 for e in s.tx_queue if e.get("guard"))
        delays = sum(1 for e in s.tx_queue if e["type"] == "delay")
        details = [("Commands", str(cmds))]
        if delays: details.append(("Delays", str(delays)))
        if guards: details.append(("Guards", str(guards)))
        details.append(("Mode", s.uplink_mode))
        self.push_screen(ConfirmScreen(f"Send {n} command{'s' if n != 1 else ''}?", "Send", details=details), _on_confirm)

    def action_undo_queue(self):
        _perform_undo(self.state)
        self._act()

    def action_clear_queue(self):
        s = self.state
        if not s.tx_queue: return
        n = len(s.tx_queue)
        def _on_confirm(confirmed):
            if confirmed and s.tx_queue:
                s.status.set(f"Cleared {len(s.tx_queue)} command{'s' if len(s.tx_queue)!=1 else ''}", STATUS_BRIEF)
                s.tx_queue.clear(); _save_queue(s.tx_queue); s.queue_scroll = 0; s.queue_sel = -1; s._queue_dirty = True
                self._act()
        self.push_screen(ConfirmScreen(f"Clear {n} command{'s' if n != 1 else ''}?", "Clear",
                                       destructive=True, details=[("Commands", str(n))]), _on_confirm)

    def _cycle_focus(self, direction):
        cycle = self._FOCUS_CYCLE
        default = 0 if direction == 1 else len(cycle) - 1
        idx = default
        for i, sel in enumerate(cycle):
            if self.focused is self.query_one(sel):
                idx = (i + direction) % len(cycle); break
        self.query_one(cycle[idx]).focus()

    def action_focus_next_widget(self): self._cycle_focus(1)

    def on_descendant_focus(self, event):
        self.query_one("Hints").refresh()

    _TAB_LABELS = {"#tx-input": "queue", "#tx-queue": "history", "#sent-history": "input"}

    def _hint_text(self):
        s = self.state
        sending = s.sending.get("active", False)
        f = self.focused
        if isinstance(f, TxQueue):
            ctx = [("␣", "guard"), ("w", "delay"), ("⌫", "remove")]
        elif isinstance(f, SentHistory):
            ctx = [("↑↓", "scroll")]
        else:
            ctx = [("^S", "send"), ("^X", "clear"), ("cfg", "")]
        # Tab label: show the next widget in the focus cycle
        tab_next = "next"
        for sel, label in self._TAB_LABELS.items():
            if f is self.query_one(sel):
                idx = self._FOCUS_CYCLE.index(sel)
                nxt = self._FOCUS_CYCLE[(idx + 1) % len(self._FOCUS_CYCLE)]
                tab_next = self._TAB_LABELS.get(nxt, "next")
                break
        pinned = [("⇥", tab_next), ("?", "help"), ("^C", "abort" if sending else "quit")]
        return ctx, pinned

    def action_history_prev(self):
        # Only recall command history when input is focused
        if not isinstance(self.focused, Input): return
        s = self.state
        inp = self.query_one("#tx-input", Input)
        if s.cmd_history:
            if s.cmd_hist_idx == -1: s.cmd_hist_save = inp.value; s.cmd_hist_idx = 0
            elif s.cmd_hist_idx < len(s.cmd_history) - 1: s.cmd_hist_idx += 1
            inp.value = s.cmd_history[s.cmd_hist_idx]; inp.cursor_position = len(inp.value)

    def action_history_next(self):
        if not isinstance(self.focused, Input): return
        s = self.state
        inp = self.query_one("#tx-input", Input)
        if s.cmd_hist_idx >= 0:
            s.cmd_hist_idx -= 1
            inp.value = s.cmd_hist_save if s.cmd_hist_idx == -1 else s.cmd_history[s.cmd_hist_idx]
            inp.cursor_position = len(inp.value)

    def _pre_dispatch(self, line):
        s = self.state
        s.cmd_hist_idx = -1
        s.cmd_history.appendleft(line)

    def _dispatch(self, line):
        return _dispatch_tx_command(self.state, line, self._sock)

    def _open_help(self):
        v, sc, sp, lp = tx_help_info(self.state)
        self.push_screen(HelpScreen(HELP_LINES, version=v,
                                    schema_count=sc, schema_path=sp, log_path=lp))

    def _open_config(self):
        s = self.state
        vals = config_get_values(s.csp, s.ax25, s.freq, s.zmq_addr_disp, s.tx_delay_ms, s.uplink_mode)
        self.push_screen(ConfigScreen(CONFIG_FIELDS, vals), self._on_config_done)

    def _handle_result(self, result):
        if result == "open_import":
            files = _list_import_files()
            if not files:
                self.state.status.set("No .jsonl files in generated_commands/", STATUS_NORMAL)
            else:
                self.push_screen(ImportScreen(files), self._on_import_done)
            self._act(); return True
        if result == "confirm_send":
            self.action_send_queue(); return True
        if result == "confirm_clear":
            self.action_clear_queue(); return True
        return False

    def _on_config_done(self, values):
        s = self.state
        try:
            s.freq, s.zmq_addr_disp, s.tx_delay_ms, s.uplink_mode = config_apply(values, s.csp, s.ax25)
            s.status.set("Config saved", STATUS_BRIEF)
        except (ValueError, KeyError):
            s.status.set("Invalid config value — reverted", STATUS_NORMAL)
        self._act()

    def _on_import_done(self, filename):
        if not filename: self._act(); return
        s = self.state
        try:
            first_new = len(s.tx_queue)
            loaded, skipped = _import_file(s, filename)
            s.queue_scroll = first_new; s.queue_sel = first_new
            msg = f"Loaded {loaded} command{'s' if loaded != 1 else ''} from {filename}"
            if skipped: msg += f" ({skipped} skipped)"
            s.status.set(msg, STATUS_LONG)
        except FileNotFoundError:
            s.status.set(f"Not found: {filename}", STATUS_NORMAL)
        except Exception as e:
            s.status.set(f"Import error: {e}", STATUS_LONG)
        self._act()

    def _cleanup(self):
        s = self.state
        try: s.tx_log.write_summary(s.tx_count, s.session_start); s.tx_log.close()
        except Exception as e:
            print(f"WARNING: failed to close TX session log: {e}", file=sys.stderr)
        try:
            update_cfg_from_state(CFG, s.csp, s.ax25, s.freq, s.zmq_addr_disp, s.tx_delay_ms,
                                 uplink_mode=s.uplink_mode)
            save_gss_config(CFG)
        except Exception as e:
            print(f"WARNING: failed to save config: {e}", file=sys.stderr)
        zmq_cleanup(self._zmq_monitor, PUB_STATUS, s.zmq_status, self._sock, self._zmq_ctx)


def main():
    parser = argparse.ArgumentParser(description="MAVERIC TX Dashboard")
    parser.add_argument("--nosplash", action="store_true")
    args = parser.parse_args()
    app = MavTxApp(show_splash=not args.nosplash)
    app.run()
    if app.return_value == "restart":
        print("\n  Restarting...\n")
        argv = sys.argv[:]
        if "--nosplash" not in argv: argv.append("--nosplash")
        os.execv(sys.executable, [sys.executable] + argv)
    print(f"\n  Session ended\n  Transmitted: {app.state.tx_count}\n  Log: {app.state.tx_log.text_path}\n")


if __name__ == "__main__":
    main()
