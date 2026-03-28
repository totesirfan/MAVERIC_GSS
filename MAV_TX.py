"""
MAV_TX -- MAVERIC Command Terminal (Textual Dashboard)

Author:  Irfan Annuar - USC ISI SERC
"""

import argparse
import json
import os
import tempfile
import threading
import time
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
                                    Hints, HelpPanel, ConfigScreen, ImportScreen, MavAppBase,
                                    dispatch_common, TS_SHORT,
                                    STATUS_BRIEF, STATUS_NORMAL, STATUS_LONG, STATUS_STARTUP)
from mav_gss_lib.config import (
    load_gss_config, apply_ax25, apply_csp, ax25_handle_msg, csp_handle_msg,
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
    tx_help_info,
)

CFG = load_gss_config()
init_nodes(CFG)
VERSION       = CFG["general"]["version"]
ZMQ_ADDR      = CFG["tx"]["zmq_addr"]
LOG_DIR       = CFG["general"]["log_dir"]
MAX_RS_PAYLOAD = 223
CMD_DEFS_PATH = CFG["general"]["command_defs"]
FREQUENCY     = CFG["tx"]["frequency"]
TX_DELAY_MS   = CFG["tx"]["delay_ms"]
UPLINK_MODE   = CFG["tx"].get("uplink_mode", "AX.25")
MAX_HISTORY   = 500
MAX_CMD_HISTORY = 500
QUEUE_FILE = os.path.join(LOG_DIR, ".pending_queue.jsonl")
IMPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_commands")

# -- Queue persistence --------------------------------------------------------

def _queue_entry_to_dict(entry):
    """Serialize a queue tuple to a JSON-safe dict for JSONL persistence."""
    src, dest, echo, ptype, cmd, args, raw_cmd = entry
    return {"src": src, "dest": dest, "echo": echo, "ptype": ptype,
            "cmd": cmd, "args": args, "raw_cmd": raw_cmd.hex()}

def _dict_to_queue_entry(d):
    """Deserialize a JSON dict back into a queue tuple."""
    return (d["src"], d["dest"], d["echo"], d["ptype"],
            d["cmd"], d["args"], bytes.fromhex(d["raw_cmd"]))

def _array_to_queue_entry(arr):
    """Convert a 6-element JSON array [src, dest, echo, ptype, cmd, args]
    (as exported by MAVERIC Command Generator) into a queue tuple."""
    src_s, dest_s, echo_s, ptype_s, cmd, args = arr
    src   = protocol.resolve_node(str(src_s))
    dest  = protocol.resolve_node(str(dest_s))
    echo  = protocol.resolve_node(str(echo_s))
    ptype = protocol.resolve_ptype(str(ptype_s))
    if None in (src, dest, echo, ptype):
        raise ValueError("unresolvable node/ptype in array entry")
    cmd = cmd.lower()
    raw_cmd = build_cmd_raw(dest, cmd, args, echo=echo, ptype=ptype, origin=src)
    return (src, dest, echo, ptype, cmd, args, raw_cmd)

def _save_queue(tx_queue):
    """Atomically write the full TX queue to .pending_queue.jsonl."""
    if not tx_queue:
        try: os.remove(QUEUE_FILE)
        except FileNotFoundError: pass
        return
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(QUEUE_FILE) or ".")
    try:
        with os.fdopen(fd, "w") as f:
            for e in tx_queue: f.write(json.dumps(_queue_entry_to_dict(e)) + "\n")
        os.replace(tmp, QUEUE_FILE)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise

def _append_queue(entry):
    """Append a single queue entry to .pending_queue.jsonl."""
    with open(QUEUE_FILE, "a") as f:
        f.write(json.dumps(_queue_entry_to_dict(entry)) + "\n")

def _parse_jsonl_file(path):
    """Parse a JSONL file of queue entries (dict or array format).
    Returns (entries, skipped_count). Raises FileNotFoundError if missing."""
    entries, skipped = [], 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                obj = json.loads(line)
                if isinstance(obj, list):
                    entries.append(_array_to_queue_entry(obj))
                else:
                    entries.append(_dict_to_queue_entry(obj))
            except (json.JSONDecodeError, KeyError, ValueError): skipped += 1
    return entries, skipped

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

def _import_file(state, filename):
    """Import commands from a JSONL file into the TX queue.
    Returns (loaded_count, skipped_count) or raises FileNotFoundError."""
    entries, skipped = _parse_jsonl_file(os.path.join(IMPORT_DIR, filename))
    for e in entries:
        state.tx_queue.append(e)
        _append_queue(e)
    return len(entries), skipped

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
    zmq_status: str = "BOUND"
    tx_delay_ms: int = 0
    cmd_history: list = field(default_factory=list)
    cmd_hist_idx: int = -1
    cmd_hist_save: str = ""
    queue_scroll: int = 0
    hist_scroll: int = 0
    help_open: bool = False
    send_abort: threading.Event = field(default_factory=threading.Event)
    send_lock: threading.Lock = field(default_factory=threading.Lock)
    sending: dict = field(default_factory=lambda: {"active": False, "idx": -1, "total": 0})
    status: StatusMessage = field(default_factory=StatusMessage)
    uplink_mode: str = "AX.25"
    version: str = ""
    schema_count: int = 0
    schema_path: str = ""

# -- Send thread --------------------------------------------------------------

def _send_worker(state, snapshot, delay_ms, sock):
    """Background thread: send queued commands with inter-packet delay. Supports abort."""
    sent = 0
    for i, (src, dest, echo, ptype, cmd, args, raw_cmd) in enumerate(snapshot):
        if state.send_abort.is_set(): break
        with state.send_lock: state.sending["idx"] = i
        if i > 0 and delay_ms > 0:
            remaining = delay_ms / 1000.0
            while remaining > 0 and not state.send_abort.is_set():
                time.sleep(min(1/60, remaining)); remaining -= 1/60
            if state.send_abort.is_set(): break
        csp_packet = state.csp.wrap(raw_cmd)
        if state.uplink_mode == "ASM+Golay":
            payload = build_asm_golay_frame(csp_packet)
        else:
            ax25_frame = state.ax25.wrap(csp_packet)
            payload = build_ax25_gfsk_frame(ax25_frame)
        if not send_pdu(sock, payload):
            state.status.set("ZMQ send error — aborting send", STATUS_LONG); break
        state.tx_count += 1; sent += 1
        state.tx_log.write_command(state.tx_count, src, dest, echo, ptype,
                                   cmd, args, raw_cmd, payload, state.ax25, state.csp,
                                   uplink_mode=state.uplink_mode)
        with state.send_lock:
            state.history.append({"n": state.tx_count, "ts": datetime.now().strftime(TS_SHORT),
                "src": src, "dest": dest, "cmd": cmd, "args": args, "echo": echo,
                "ptype": ptype, "payload_len": len(payload), "csp_enabled": state.csp.enabled})
            state.hist_scroll = len(state.history) - 1
    with state.send_lock:
        del state.tx_queue[:sent]; _save_queue(state.tx_queue)
        if len(state.history) > MAX_HISTORY: del state.history[:len(state.history) - MAX_HISTORY]
        state.hist_scroll = max(0, len(state.history) - 1)
        total = state.sending["total"]
    if state.send_abort.is_set():
        state.status.set(f"Aborted: sent {sent}/{total}, {total-sent} remain", STATUS_LONG)
    else:
        state.status.set(f"Sent {sent} command{'s' if sent != 1 else ''}")
    with state.send_lock: state.sending["active"] = False; state.sending["idx"] = -1

def _start_send(state, sock):
    """Start the send worker thread if queue is non-empty and no send is active."""
    with state.send_lock:
        if state.sending["active"]: state.status.set("Send already in progress", STATUS_BRIEF); return
        if not state.tx_queue: state.status.set("Nothing queued", STATUS_BRIEF); return
        state.send_abort.clear()
        snapshot = list(state.tx_queue)
        state.sending.update(active=True, total=len(snapshot), idx=0)
    state.queue_scroll = 0
    threading.Thread(target=_send_worker, args=(state, snapshot, state.tx_delay_ms, sock), daemon=True).start()

# -- Command dispatch ---------------------------------------------------------

def _cmd_send(state, line, sock):
    """Handler for 'send' command — start sending the queue."""
    _start_send(state, sock)

def _cmd_clear(state, line, sock):
    """Handler for 'clear' command — clear the TX queue."""
    if state.tx_queue:
        state.status.set(f"Cleared {len(state.tx_queue)} commands", STATUS_BRIEF)
        state.tx_queue.clear(); _save_queue(state.tx_queue); state.queue_scroll = 0
    else:
        state.status.set("Nothing to clear", STATUS_BRIEF)

def _cmd_undo(state, line, sock):
    """Handler for 'undo'/'pop' command — remove last queued command."""
    if state.tx_queue:
        r = state.tx_queue.pop(); _save_queue(state.tx_queue)
        state.status.set(f"Removed: {r[4]} ({len(state.tx_queue)} left)", STATUS_BRIEF)
    else:
        state.status.set("Queue is empty", STATUS_BRIEF)

def _cmd_hclear(state, line, sock):
    """Handler for 'hclear' command — clear sent history."""
    if state.history:
        state.status.set(f"Cleared {len(state.history)} entries", STATUS_BRIEF)
        state.history.clear(); state.hist_scroll = 0
    else:
        state.status.set("History already empty", STATUS_BRIEF)

def _cmd_imp(state, line, sock):
    """Handler for 'imp' command — open import file picker."""
    return "open_import"

def _cmd_nodes(state, line, sock):
    """Handler for 'nodes' command — display node ID table."""
    state.status.set("Nodes: " + ", ".join(
        f"{n}={protocol.NODE_NAMES[n]}" for n in sorted(protocol.NODE_NAMES)), STATUS_LONG)

def _cmd_csp(state, line, sock):
    """Handler for 'csp' command — show or set CSP header fields."""
    state.status.set(csp_handle_msg(state.csp, line[3:].strip() if len(line) > 3 else ""), STATUS_NORMAL)

def _cmd_ax25(state, line, sock):
    """Handler for 'ax25' command — show or set AX.25 callsign/SSID."""
    state.status.set(ax25_handle_msg(state.ax25, line[4:].strip() if len(line) > 4 else ""), STATUS_NORMAL)

def _cmd_mode(state, line, sock):
    """Handler for 'mode' command — show or switch uplink encoding mode."""
    arg = line[4:].strip() if len(line) > 4 else ""
    if not arg:
        state.status.set(f"Uplink mode: {state.uplink_mode}", STATUS_NORMAL)
    elif arg.upper() in ("AX.25", "AX25"):
        state.uplink_mode = "AX.25"
        state.status.set("Uplink mode: AX.25", STATUS_NORMAL)
    elif arg.upper() in ("ASM+GOLAY", "GOLAY", "ASM"):
        if not _GOLAY_OK:
            state.status.set("reedsolo not installed — cannot use ASM+Golay", STATUS_NORMAL)
        else:
            state.uplink_mode = "ASM+Golay"
            state.status.set("Uplink mode: ASM+Golay", STATUS_NORMAL)
    else:
        state.status.set("mode [AX.25 | ASM+Golay]", STATUS_NORMAL)

# Handler registry: command -> handler function
_TX_HANDLERS = {
    "send": _cmd_send, "clear": _cmd_clear,
    "undo": _cmd_undo, "pop": _cmd_undo,
    "hclear": _cmd_hclear, "imp": _cmd_imp, "nodes": _cmd_nodes,
}

# Prefix handlers: checked with startswith
_TX_PREFIX_HANDLERS = [
    ("csp",  _cmd_csp),
    ("ax25", _cmd_ax25),
    ("mode", _cmd_mode),
]

def _queue_command(state, line):
    """Parse a command line and add to the TX queue."""
    try:
        parsed = parse_cmd_line(line)
    except ValueError as e:
        state.status.set(f"Bad command: {e}", STATUS_NORMAL); return True
    src, dest, echo, ptype, cmd, args = parsed
    valid, issues = validate_args(cmd, args, state.cmd_defs)
    if not valid and issues:
        state.status.set(f"Rejected: {issues[0]}", STATUS_NORMAL); return True
    if state.cmd_defs and cmd not in state.cmd_defs:
        state.status.set(f"Rejected: '{cmd}' not in schema", STATUS_NORMAL); return True
    raw_cmd = build_cmd_raw(dest, cmd, args, echo=echo, ptype=ptype, origin=src)
    overhead = state.csp.overhead() if state.uplink_mode == "ASM+Golay" else state.csp.overhead() + state.ax25.overhead()
    if len(raw_cmd) + overhead > MAX_RS_PAYLOAD:
        state.status.set("Command too large for RS payload", STATUS_NORMAL); return True
    entry = (src, dest, echo, ptype, cmd, args, raw_cmd)
    state.tx_queue.append(entry); _append_queue(entry)
    src_tag = f"{node_label(src)}→" if src != protocol.GS_NODE else ""
    state.status.set(f"Queued: {src_tag}{node_label(dest)} E:{echo} "
                     f"{protocol.PTYPE_NAMES.get(ptype,'?')} {cmd} {args} ({len(raw_cmd)}B)", STATUS_BRIEF)
    return True

def _dispatch_tx_command(state, line, sock):
    """Dispatch a TX command: try common → exact → prefix → queue as uplink command."""
    cl = line.lower()
    common = dispatch_common(state, cl)
    if common is not None:
        return common
    # Exact match
    handler = _TX_HANDLERS.get(cl)
    if handler:
        result = handler(state, line, sock)
        return result if result else True
    # Prefix match (e.g. "csp prio 2", "mode AX.25")
    for prefix, handler in _TX_PREFIX_HANDLERS:
        if cl == prefix or cl.startswith(prefix + " "):
            result = handler(state, line, sock)
            return result if result else True
    # Fall through: parse as a command to queue
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
    TxQueue { border-top: solid #555555; border-left: solid black; border-right: solid black; border-bottom: solid black; }
    TxQueue:focus { border: solid #00bfff; }
    SentHistory { border-top: solid #555555; border-left: solid black; border-right: solid black; border-bottom: solid black; }
    SentHistory:focus { border: solid #00bfff; }
    """
    _WIDGET_QUERY = "TxHeader, TxQueue, SentHistory, TxStatusBar, HelpPanel"
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
        self.state = TxState(
            csp=csp, ax25=ax25, cmd_defs=cmd_defs, tx_queue=tx_queue, history=[],
            tx_log=TXLog(LOG_DIR, ZMQ_ADDR, version=VERSION), session_start=time.time(),
            freq=FREQUENCY, zmq_addr_disp=ZMQ_ADDR, tx_delay_ms=TX_DELAY_MS,
            uplink_mode=UPLINK_MODE,
            version=VERSION, schema_count=len(cmd_defs), schema_path=CMD_DEFS_PATH,
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
            yield HelpPanel(s, HELP_LINES, "Esc: close", tx_help_info, id="help-panel")
        with Vertical(id="bottom-bar"):
            yield TxStatusBar(s, id="status-bar")
            yield Input(id="tx-input")
            yield Hints(" Tab: focus | Enter: queue | cfg | help | imp | Ctrl+C: quit")

    def on_mount(self):
        if self._show_splash:
            ax, cs = CFG["ax25"], CFG["csp"]
            self.push_screen(SplashScreen(subtitle=f"MAVERIC TX Dashboard  v{VERSION}",
                config_lines=[("Config", "maveric_gss.yml"), ("ZMQ PUB", ZMQ_ADDR),
                    ("Frequency", FREQUENCY), ("Uplink Mode", UPLINK_MODE), ("TX Delay", f"{TX_DELAY_MS} ms"),
                    ("AX.25", f"GS:{ax['src_call']}-{ax['src_ssid']} -> SAT:{ax['dest_call']}-{ax['dest_ssid']}"),
                    ("CSP", f"Prio:{cs['priority']} Src:{cs['source']} Dest:{cs['destination']}"),
                    ("Commands", CMD_DEFS_PATH), ("Log", f"{LOG_DIR}/text")]))
        self.set_interval(1/60, self._tick)
        self.query_one("#tx-input").focus()

    def _tick(self):
        s = self.state
        s.zmq_status = poll_monitor(self._zmq_monitor, PUB_STATUS, s.zmq_status)
        s.status.check_expiry()
        self.query_one("#help-panel").display = s.help_open
        for w in self.query("TxHeader, TxQueue, SentHistory, TxStatusBar, HelpPanel"):
            w.refresh()

    def action_quit_or_close(self):
        s = self.state
        if s.sending["active"]: s.send_abort.set(); s.status.set("Aborting send...", STATUS_BRIEF); self._act(); return
        if s.help_open: s.help_open = False; self._act(); return
        self._cleanup(); self.exit()

    def action_close_or_cancel(self):
        s = self.state
        if s.sending["active"]: s.send_abort.set(); s.status.set("Aborting send...", STATUS_BRIEF)
        elif s.help_open: s.help_open = False
        self._act()

    def action_send_queue(self): _start_send(self.state, self._sock); self._act()

    def action_undo_queue(self):
        s = self.state
        if s.tx_queue:
            r = s.tx_queue.pop(); _save_queue(s.tx_queue)
            s.status.set(f"Removed: {r[4]} ({len(s.tx_queue)} left)", STATUS_BRIEF)
        else: s.status.set("Queue is empty", STATUS_BRIEF)
        self._act()

    def action_clear_queue(self):
        s = self.state
        if s.tx_queue:
            s.status.set(f"Cleared {len(s.tx_queue)} command{'s' if len(s.tx_queue)!=1 else ''}", STATUS_BRIEF)
            s.tx_queue.clear(); _save_queue(s.tx_queue); s.queue_scroll = 0
        self._act()

    def _cycle_focus(self, direction):
        cycle = self._FOCUS_CYCLE
        default = 0 if direction == 1 else len(cycle) - 1
        idx = default
        for i, sel in enumerate(cycle):
            if self.focused is self.query_one(sel):
                idx = (i + direction) % len(cycle); break
        self.query_one(cycle[idx]).focus()

    def action_focus_next_widget(self): self._cycle_focus(1)

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
        s.cmd_history.insert(0, line)
        if len(s.cmd_history) > MAX_CMD_HISTORY: del s.cmd_history[MAX_CMD_HISTORY:]

    def _dispatch(self, line):
        return _dispatch_tx_command(self.state, line, self._sock)

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
            loaded, skipped = _import_file(s, filename)
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
        except Exception: pass
        try:
            update_cfg_from_state(CFG, s.csp, s.ax25, s.freq, s.zmq_addr_disp, s.tx_delay_ms,
                                 uplink_mode=s.uplink_mode)
            save_gss_config(CFG)
        except Exception: pass
        zmq_cleanup(self._zmq_monitor, PUB_STATUS, s.zmq_status, self._sock, self._zmq_ctx)


def main():
    parser = argparse.ArgumentParser(description="MAVERIC TX Dashboard")
    parser.add_argument("--nosplash", action="store_true")
    args = parser.parse_args()
    app = MavTxApp(show_splash=not args.nosplash)
    app.run()
    print(f"\n  Session ended\n  Transmitted: {app.state.tx_count}\n  Log: {app.state.tx_log.text_path}\n")


if __name__ == "__main__":
    main()
