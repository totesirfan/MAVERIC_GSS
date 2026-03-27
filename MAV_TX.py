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
                                    dispatch_common)
from mav_gss_lib.config import (
    load_gss_config, apply_ax25, apply_csp, ax25_handle_msg, csp_handle_msg,
    save_gss_config, update_cfg_from_state,
)
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
MAX_HISTORY   = 500
MAX_CMD_HISTORY = 500
QUEUE_FILE = os.path.join(LOG_DIR, ".pending_queue.jsonl")
IMPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_commands")

# -- Queue persistence --------------------------------------------------------

def _queue_entry_to_dict(entry):
    src, dest, echo, ptype, cmd, args, raw_cmd = entry
    return {"src": src, "dest": dest, "echo": echo, "ptype": ptype,
            "cmd": cmd, "args": args, "raw_cmd": raw_cmd.hex()}

def _dict_to_queue_entry(d):
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
    version: str = ""
    schema_count: int = 0
    schema_path: str = ""

# -- Send thread --------------------------------------------------------------

def _send_worker(state, snapshot, delay_ms, sock):
    sent = 0
    for i, (src, dest, echo, ptype, cmd, args, raw_cmd) in enumerate(snapshot):
        if state.send_abort.is_set(): break
        with state.send_lock: state.sending["idx"] = i
        if i > 0 and delay_ms > 0:
            remaining = delay_ms / 1000.0
            while remaining > 0 and not state.send_abort.is_set():
                time.sleep(min(0.05, remaining)); remaining -= 0.05
            if state.send_abort.is_set(): break
        payload = state.ax25.wrap(state.csp.wrap(raw_cmd))
        if not send_pdu(sock, payload):
            state.status.set("ZMQ send error — aborting send", 5); break
        state.tx_count += 1; sent += 1
        state.tx_log.write_command(state.tx_count, src, dest, echo, ptype,
                                   cmd, args, raw_cmd, payload, state.ax25, state.csp)
        with state.send_lock:
            state.history.append({"n": state.tx_count, "ts": datetime.now().strftime("%H:%M:%S"),
                "src": src, "dest": dest, "cmd": cmd, "args": args, "echo": echo,
                "ptype": ptype, "payload_len": len(payload), "csp_enabled": state.csp.enabled})
            state.hist_scroll = len(state.history) - 1
    with state.send_lock:
        del state.tx_queue[:sent]; _save_queue(state.tx_queue)
        if len(state.history) > MAX_HISTORY: del state.history[:len(state.history) - MAX_HISTORY]
        state.hist_scroll = max(0, len(state.history) - 1)
        total = state.sending["total"]
    if state.send_abort.is_set():
        state.status.set(f"Aborted: sent {sent}/{total}, {total-sent} remain", 5)
    else:
        state.status.set(f"Sent {sent} command{'s' if sent != 1 else ''}")
    with state.send_lock: state.sending["active"] = False; state.sending["idx"] = -1

def _start_send(state, sock):
    with state.send_lock:
        if state.sending["active"]: state.status.set("Send already in progress", 2); return
        if not state.tx_queue: state.status.set("Nothing queued", 2); return
        state.send_abort.clear()
        snapshot = list(state.tx_queue)
        state.sending.update(active=True, total=len(snapshot), idx=0)
    state.queue_scroll = 0
    threading.Thread(target=_send_worker, args=(state, snapshot, state.tx_delay_ms, sock), daemon=True).start()

# -- Command dispatch ---------------------------------------------------------

def _dispatch_tx_command(state, line, sock):
    cl = line.lower()
    common = dispatch_common(state, cl)
    if common is not None: return common
    if cl == 'send': _start_send(state, sock); return True
    if cl == 'clear':
        if state.tx_queue:
            state.status.set(f"Cleared {len(state.tx_queue)} commands", 2)
            state.tx_queue.clear(); _save_queue(state.tx_queue); state.queue_scroll = 0
        else: state.status.set("Nothing to clear", 2)
        return True
    if cl in ('undo', 'pop'):
        if state.tx_queue:
            r = state.tx_queue.pop(); _save_queue(state.tx_queue)
            state.status.set(f"Removed: {r[4]} ({len(state.tx_queue)} left)", 2)
        else: state.status.set("Queue is empty", 2)
        return True
    if cl == 'hclear':
        if state.history: state.status.set(f"Cleared {len(state.history)} entries", 2); state.history.clear(); state.hist_scroll = 0
        else: state.status.set("History already empty", 2)
        return True
    if cl == 'imp':
        return "open_import"
    if cl == 'nodes':
        state.status.set("Nodes: " + ", ".join(f"{n}={protocol.NODE_NAMES[n]}" for n in sorted(protocol.NODE_NAMES)), 5); return True
    if cl == 'csp' or cl.startswith('csp '):
        state.status.set(csp_handle_msg(state.csp, line[3:].strip() if len(line)>3 else ""), 4); return True
    if cl == 'ax25' or cl.startswith('ax25 '):
        state.status.set(ax25_handle_msg(state.ax25, line[4:].strip() if len(line)>4 else ""), 4); return True
    try: parsed = parse_cmd_line(line)
    except ValueError as e: state.status.set(f"Bad command: {e}", 3); return True
    src, dest, echo, ptype, cmd, args = parsed
    valid, issues = validate_args(cmd, args, state.cmd_defs)
    if not valid and issues: state.status.set(f"Rejected: {issues[0]}", 3); return True
    if state.cmd_defs and cmd not in state.cmd_defs: state.status.set(f"Rejected: '{cmd}' not in schema", 3); return True
    raw_cmd = build_cmd_raw(dest, cmd, args, echo=echo, ptype=ptype, origin=src)
    if len(raw_cmd) + state.csp.overhead() + state.ax25.overhead() > MAX_RS_PAYLOAD:
        state.status.set("Command too large for RS payload", 3); return True
    entry = (src, dest, echo, ptype, cmd, args, raw_cmd)
    state.tx_queue.append(entry); _append_queue(entry)
    src_tag = f"{node_label(src)}→" if src != protocol.GS_NODE else ""
    state.status.set(f"Queued: {src_tag}{node_label(dest)} E:{echo} "
                     f"{protocol.PTYPE_NAMES.get(ptype,'?')} {cmd} {args} ({len(raw_cmd)}B)", 2)
    return True

# =============================================================================
#  APP
# =============================================================================

class MavTxApp(MavAppBase):
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
        Binding("shift+tab", "focus_prev_widget", "Shift+Tab", show=False),
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
            version=VERSION, schema_count=len(cmd_defs), schema_path=CMD_DEFS_PATH,
        )
        if tx_queue or q_skipped:
            parts = [f"Restored {len(tx_queue)} queued command{'s' if len(tx_queue)!=1 else ''}"]
            if q_skipped: parts.append(f" ({q_skipped} skipped — corrupt)")
            self.state.status.set("".join(parts), 5)
        if self._schema_warning: self.state.status.set(f"SCHEMA: {self._schema_warning}", 10)

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
            yield Input(id="tx-input", placeholder="> ")
            yield Hints(" Enter: queue | cfg | help | imp | Ctrl+C: quit")

    def on_mount(self):
        if self._show_splash:
            ax, cs = CFG["ax25"], CFG["csp"]
            self.push_screen(SplashScreen(subtitle=f"MAVERIC TX Dashboard  v{VERSION}",
                config_lines=[("Config", "maveric_gss.yml"), ("ZMQ PUB", ZMQ_ADDR),
                    ("Frequency", FREQUENCY), ("TX Delay", f"{TX_DELAY_MS} ms"),
                    ("AX.25", f"GS:{ax['src_call']}-{ax['src_ssid']} -> SAT:{ax['dest_call']}-{ax['dest_ssid']}"),
                    ("CSP", f"Prio:{cs['priority']} Src:{cs['source']} Dest:{cs['destination']}"),
                    ("Commands", CMD_DEFS_PATH), ("Log", f"{LOG_DIR}/text")]))
        self.set_interval(0.1, self._tick)
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
        if s.sending["active"]: s.send_abort.set(); s.status.set("Aborting send...", 2); self._act(); return
        if s.help_open: s.help_open = False; self._act(); return
        self._cleanup(); self.exit()

    def action_close_or_cancel(self):
        s = self.state
        if s.sending["active"]: s.send_abort.set(); s.status.set("Aborting send...", 2)
        elif s.help_open: s.help_open = False
        self._act()

    def action_send_queue(self): _start_send(self.state, self._sock); self._act()

    def action_undo_queue(self):
        s = self.state
        if s.tx_queue:
            r = s.tx_queue.pop(); _save_queue(s.tx_queue)
            s.status.set(f"Removed: {r[4]} ({len(s.tx_queue)} left)", 2)
        else: s.status.set("Queue is empty", 2)
        self._act()

    def action_clear_queue(self):
        s = self.state
        if s.tx_queue:
            s.status.set(f"Cleared {len(s.tx_queue)} command{'s' if len(s.tx_queue)!=1 else ''}", 2)
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
    def action_focus_prev_widget(self): self._cycle_focus(-1)

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
        vals = config_get_values(s.csp, s.ax25, s.freq, s.zmq_addr_disp, s.tx_delay_ms)
        self.push_screen(ConfigScreen(CONFIG_FIELDS, vals), self._on_config_done)

    def _handle_result(self, result):
        if result == "open_import":
            files = _list_import_files()
            if not files:
                self.state.status.set("No .jsonl files in generated_commands/", 3)
            else:
                self.push_screen(ImportScreen(files), self._on_import_done)
            self._act(); return True
        return False

    def _on_config_done(self, values):
        s = self.state
        try:
            s.freq, s.zmq_addr_disp, s.tx_delay_ms = config_apply(values, s.csp, s.ax25)
            s.status.set("Config saved", 2)
        except (ValueError, KeyError):
            s.status.set("Invalid config value — reverted", 3)
        self._act()

    def _on_import_done(self, filename):
        if not filename: self._act(); return
        s = self.state
        try:
            loaded, skipped = _import_file(s, filename)
            msg = f"Loaded {loaded} command{'s' if loaded != 1 else ''} from {filename}"
            if skipped: msg += f" ({skipped} skipped)"
            s.status.set(msg, 5)
        except FileNotFoundError:
            s.status.set(f"Not found: {filename}", 3)
        except Exception as e:
            s.status.set(f"Import error: {e}", 5)
        self._act()

    def _cleanup(self):
        s = self.state
        try: s.tx_log.write_summary(s.tx_count, s.session_start); s.tx_log.close()
        except Exception: pass
        try:
            update_cfg_from_state(CFG, s.csp, s.ax25, s.freq, s.zmq_addr_disp, s.tx_delay_ms)
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
