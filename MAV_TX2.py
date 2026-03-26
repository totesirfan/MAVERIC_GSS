"""
MAV_TX2 -- MAVERIC Command Terminal (Curses Dashboard)

Persistent curses-based uplink dashboard (CSP v1 + CRC-32C + AX.25 + ZMQ)
with a live display showing:
  - Header: AX.25 callsigns, CSP config, clock, ZMQ status, frequency
  - TX Queue: pending commands (scrollable)
  - Sent History: transmitted commands with full metadata (scrollable)
  - Input: command entry with cursor editing

All commands go to the queue first. Ctrl+S sends, Ctrl+X clears.

Author:  Irfan Annuar - USC ISI SERC
"""

import argparse
import curses
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

import mav_gss_lib.protocol as protocol
from mav_gss_lib.protocol import (
    init_nodes, node_label,
    build_cmd_raw, AX25Config, CSPConfig,
    load_command_defs, validate_args, parse_cmd_line,
)
from mav_gss_lib.transport import (init_zmq_pub, send_pdu,
                                   poll_monitor, _PUB_STATUS, zmq_cleanup)
from mav_gss_lib.logging import TXLog
from mav_gss_lib.curses_common import (init_dashboard, draw_splash, edit_buffer,
                                       StatusMessage, check_terminal_size,
                                       navigate_config)
from mav_gss_lib.config import (
    load_gss_config, apply_ax25, apply_csp,
    ax25_handle_msg, csp_handle_msg,
)
from mav_gss_lib.curses_tx import (
    calculate_layout,
    draw_header, draw_queue, draw_history, draw_input,
    draw_config, config_get_values, config_apply, CONFIG_FIELDS,
    draw_help,
)


# -- Config -------------------------------------------------------------------

CFG = load_gss_config()
init_nodes(CFG)

VERSION        = CFG["general"]["version"]
ZMQ_ADDR       = CFG["tx"]["zmq_addr"]
LOG_DIR        = CFG["general"]["log_dir"]
MAX_RS_PAYLOAD = 223
CMD_DEFS_PATH  = CFG["general"]["command_defs"]
FREQUENCY      = CFG["tx"]["frequency"]
TX_DELAY_MS    = CFG["tx"]["delay_ms"]
MAX_HISTORY      = 500
MAX_CMD_HISTORY  = 500


# -- Queue Persistence --------------------------------------------------------

QUEUE_FILE = os.path.join(CFG["general"]["log_dir"], ".pending_queue.jsonl")


def _queue_entry_to_dict(entry):
    """Convert a queue tuple to a JSON-serializable dict."""
    src, dest, echo, ptype, cmd, args, raw_cmd = entry
    return {"src": src, "dest": dest, "echo": echo, "ptype": ptype,
            "cmd": cmd, "args": args, "raw_cmd": raw_cmd.hex()}


def _dict_to_queue_entry(d):
    """Convert a dict back to the queue tuple format."""
    return (d["src"], d["dest"], d["echo"], d["ptype"],
            d["cmd"], d["args"], bytes.fromhex(d["raw_cmd"]))


def _save_queue(tx_queue):
    """Rewrite the entire queue file (used after pop/clear/send).
    Uses atomic write (temp file + os.replace) to prevent data loss
    if interrupted mid-write."""
    if not tx_queue:
        try:
            os.remove(QUEUE_FILE)
        except FileNotFoundError:
            pass
        return
    queue_dir = os.path.dirname(QUEUE_FILE) or "."
    fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=queue_dir)
    try:
        with os.fdopen(fd, "w") as f:
            for entry in tx_queue:
                f.write(json.dumps(_queue_entry_to_dict(entry)) + "\n")
        os.replace(tmp_path, QUEUE_FILE)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _append_queue(entry):
    """Append a single command to the queue file."""
    with open(QUEUE_FILE, "a") as f:
        f.write(json.dumps(_queue_entry_to_dict(entry)) + "\n")


def _load_queue():
    """Load queue from JSONL file. Skips malformed lines.

    Returns (queue_list, skipped_count).
    """
    queue = []
    skipped = 0
    try:
        with open(QUEUE_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    queue.append(_dict_to_queue_entry(json.loads(line)))
                except (json.JSONDecodeError, KeyError, ValueError):
                    skipped += 1
    except FileNotFoundError:
        pass
    return queue, skipped


# =============================================================================
#  STATE
# =============================================================================

@dataclass
class TxState:
    # Protocol config (mutable via config panel)
    csp: CSPConfig
    ax25: AX25Config
    cmd_defs: dict
    # Data
    tx_queue: list
    history: list
    tx_log: TXLog
    tx_count: int = 0
    session_start: float = 0.0
    # Mutable config
    freq: str = ""
    zmq_addr_disp: str = ""
    tx_delay_ms: int = 0
    # Input
    input_buf: str = ""
    cursor_pos: int = 0
    cmd_history: list = field(default_factory=list)
    cmd_hist_idx: int = -1
    cmd_hist_save: str = ""
    # Scroll
    queue_scroll: int = 0
    hist_scroll: int = 0
    # Side panels
    help_open: bool = False
    config_open: bool = False
    config_focused: bool = False
    config_selected: int = 0
    config_editing: bool = False
    config_buf: str = ""
    config_cursor: int = 0
    config_values: dict = field(default_factory=dict)
    # Send thread
    send_abort: threading.Event = field(default_factory=threading.Event)
    send_lock: threading.Lock = field(default_factory=threading.Lock)
    sending: dict = field(default_factory=lambda: {
        "active": False, "idx": -1, "total": 0})
    # Status
    status: StatusMessage = field(default_factory=StatusMessage)


# =============================================================================
#  SEND THREAD
# =============================================================================

def _send_worker(state, snapshot, delay_ms, sock):
    """Background thread: sends queued commands, updates shared state.
    All mutations to `sending`, `history` are guarded by `send_lock`."""
    sent = 0
    for i, (src, dest, echo, ptype, cmd, args, raw_cmd) in enumerate(snapshot):
        if state.send_abort.is_set():
            break
        with state.send_lock:
            state.sending["idx"] = i
        if i > 0 and delay_ms > 0:
            remaining = delay_ms / 1000.0
            while remaining > 0 and not state.send_abort.is_set():
                time.sleep(min(0.05, remaining))
                remaining -= 0.05
            if state.send_abort.is_set():
                break
        payload = state.ax25.wrap(state.csp.wrap(raw_cmd))
        ok = send_pdu(sock, payload)
        if not ok:
            state.status.set("ZMQ send error — aborting send", 5)
            break
        state.tx_count += 1
        sent += 1
        state.tx_log.write_command(state.tx_count, src, dest, echo, ptype,
                                   cmd, args, raw_cmd, payload,
                                   state.ax25, state.csp)
        with state.send_lock:
            state.history.append({
                "n": state.tx_count,
                "ts": datetime.now().strftime("%H:%M:%S"),
                "src": src, "dest": dest,
                "cmd": cmd, "args": args,
                "echo": echo, "ptype": ptype,
                "payload_len": len(payload),
                "csp_enabled": state.csp.enabled,
            })
            state.hist_scroll = len(state.history) - 1
    # Remove sent commands from front of queue
    with state.send_lock:
        del state.tx_queue[:sent]
        _save_queue(state.tx_queue)
        if len(state.history) > MAX_HISTORY:
            del state.history[:len(state.history) - MAX_HISTORY]
        state.hist_scroll = max(0, len(state.history) - 1)
        total = state.sending["total"]
    if state.send_abort.is_set():
        state.status.set(
            f"Aborted: sent {sent}/{total}, {total - sent} remain in queue", 5)
    else:
        state.status.set(f"Sent {sent} command{'s' if sent != 1 else ''}")
    with state.send_lock:
        state.sending["active"] = False
        state.sending["idx"] = -1


def _start_send(state, sock):
    """Initiate async send of the current queue."""
    with state.send_lock:
        if state.sending["active"]:
            state.status.set("Send already in progress", 2)
            return
        if not state.tx_queue:
            state.status.set("Nothing queued", 2)
            return
        state.send_abort.clear()
        snapshot = list(state.tx_queue)
        state.sending["active"] = True
        state.sending["total"] = len(snapshot)
        state.sending["idx"] = 0
    state.queue_scroll = 0
    t = threading.Thread(target=_send_worker,
                         args=(state, snapshot, state.tx_delay_ms, sock),
                         daemon=True)
    t.start()


# =============================================================================
#  KEYBOARD DISPATCH
# =============================================================================

def _refresh_config_values(state):
    """Rebuild config_values from current protocol/config state."""
    state.config_values = config_get_values(
        state.csp, state.ax25, state.freq, state.zmq_addr_disp,
        state.tx_delay_ms, state.tx_log.text_path)


def _dispatch_tx_command(state, line, sock):
    """Handle a typed command. Returns 'break' to exit, True otherwise."""
    cmd_lower = line.lower()

    if cmd_lower in ('q', 'quit', 'exit'):
        return "break"

    if cmd_lower == 'send':
        _start_send(state, sock)
        return True

    if cmd_lower == 'clear':
        if state.tx_queue:
            state.status.set(
                f"Cleared {len(state.tx_queue)} commands", 2)
            state.tx_queue.clear()
            _save_queue(state.tx_queue)
            state.queue_scroll = 0
        else:
            state.status.set("Nothing to clear", 2)
        return True

    if cmd_lower in ('undo', 'pop'):
        if state.tx_queue:
            removed = state.tx_queue.pop()
            _save_queue(state.tx_queue)
            state.status.set(
                f"Removed: {removed[4]} ({len(state.tx_queue)} left)", 2)
        else:
            state.status.set("Queue is empty", 2)
        return True

    if cmd_lower == 'hclear':
        if state.history:
            state.status.set(
                f"Cleared {len(state.history)} history entries", 2)
            state.history.clear()
            state.hist_scroll = 0
        else:
            state.status.set("History already empty", 2)
        return True

    if cmd_lower == 'help':
        state.help_open = True
        return True

    if cmd_lower in ('config', 'cfg'):
        state.config_open = True
        state.config_focused = True
        state.config_selected = 0
        state.config_editing = False
        _refresh_config_values(state)
        return True

    if cmd_lower == 'nodes':
        names = ", ".join(f"{nid}={protocol.NODE_NAMES[nid]}"
                          for nid in sorted(protocol.NODE_NAMES))
        state.status.set(f"Nodes: {names}", 5)
        return True

    if cmd_lower == 'csp' or cmd_lower.startswith('csp '):
        msg = csp_handle_msg(state.csp,
                             line[3:].strip() if len(line) > 3 else "")
        state.status.set(msg, 4)
        return True

    if cmd_lower == 'ax25' or cmd_lower.startswith('ax25 '):
        msg = ax25_handle_msg(state.ax25,
                              line[4:].strip() if len(line) > 4 else "")
        state.status.set(msg, 4)
        return True

    # -- Parse as protocol command and queue --
    try:
        parsed = parse_cmd_line(line)
    except ValueError as e:
        state.status.set(f"Bad command: {e}", 3)
        return True

    src, dest, echo, ptype, cmd, args = parsed

    valid, issues = validate_args(cmd, args, state.cmd_defs)
    if not valid and issues:
        state.status.set(f"Rejected: {issues[0]}", 3)
        return True
    if state.cmd_defs and cmd not in state.cmd_defs:
        state.status.set(f"Rejected: '{cmd}' not in command schema", 3)
        return True

    raw_cmd = build_cmd_raw(dest, cmd, args, echo=echo, ptype=ptype,
                            origin=src)
    if (len(raw_cmd) + state.csp.overhead() + state.ax25.overhead()
            > MAX_RS_PAYLOAD):
        state.status.set("Command too large for RS payload", 3)
        return True

    entry = (src, dest, echo, ptype, cmd, args, raw_cmd)
    state.tx_queue.append(entry)
    _append_queue(entry)
    src_tag = (f"{node_label(src)}\u2192"
               if src != protocol.GS_NODE else "")
    state.status.set(
        f"Queued: {src_tag}{node_label(dest)} E:{echo} "
        f"{protocol.PTYPE_NAMES.get(ptype, '?')} {cmd} {args} "
        f"({len(raw_cmd)}B)", 2)
    return True


def handle_key_tx(ch, state, stdscr, sock):
    """Dispatch a keypress through layered TX handlers.

    Returns 'break' to exit the main loop, True otherwise.
    """
    # -- Layer 0: Ctrl+C --
    if ch == 3:
        if state.sending["active"]:
            state.send_abort.set()
            state.status.set("Aborting send...", 2)
            return True
        if state.help_open:
            state.help_open = False
            return True
        if state.config_open:
            state.config_open = False
            state.config_editing = False
            state.config_values = {}
            return True
        return "break"

    # -- Layer 0: Esc --
    if ch == 27:
        if state.sending["active"]:
            state.send_abort.set()
            state.status.set("Aborting send...", 2)
            return True
        if state.config_editing:
            state.config_editing = False
            return True
        if state.config_open:
            state.config_open = False
            state.config_focused = False
            state.config_values = {}
            return True
        if state.help_open:
            state.help_open = False
            return True
        return True

    # -- Layer 1: Config editing (captures all keys) --
    if state.config_open and state.config_editing:
        if ch in (10, 13):  # Enter — save field
            key = CONFIG_FIELDS[state.config_selected][1]
            state.config_values[key] = state.config_buf
            state.config_editing = False
            try:
                state.freq, state.zmq_addr_disp, state.tx_delay_ms = \
                    config_apply(state.config_values, state.csp, state.ax25)
                _refresh_config_values(state)
            except (ValueError, KeyError):
                state.status.set("Invalid value", 2)
                _refresh_config_values(state)
        else:
            state.config_buf, state.config_cursor, _ = edit_buffer(
                ch, state.config_buf, state.config_cursor)
        return True

    # -- Layer 2: Config navigation --
    if state.config_open and not state.config_editing:
        if ch == 9:  # Tab
            state.config_focused = not state.config_focused
            return True
        if state.config_focused:
            nav = navigate_config(ch, state.config_selected,
                                  len(CONFIG_FIELDS))
            if nav is not None:
                state.config_selected = nav
                return True
            if ch in (10, 13):  # Enter — edit field
                _label, key, editable = CONFIG_FIELDS[state.config_selected]
                if editable:
                    state.config_editing = True
                    state.config_buf = state.config_values.get(key, "")
                    state.config_cursor = len(state.config_buf)
                return True

    # -- Layer 3: Queue control --
    if ch == 19:  # Ctrl+S — send
        _start_send(state, sock)
        return True

    if ch == 26:  # Ctrl+Z — undo
        if state.tx_queue:
            removed = state.tx_queue.pop()
            _save_queue(state.tx_queue)
            state.status.set(
                f"Removed: {removed[4]} ({len(state.tx_queue)} left)", 2)
        else:
            state.status.set("Queue is empty", 2)
        return True

    if ch == 24:  # Ctrl+X — clear queue
        if state.tx_queue:
            state.status.set(
                f"Cleared {len(state.tx_queue)} "
                f"command{'s' if len(state.tx_queue) != 1 else ''}", 2)
            state.tx_queue.clear()
            _save_queue(state.tx_queue)
            state.queue_scroll = 0
        return True

    # -- Layer 4: History scroll --
    if ch == curses.KEY_PPAGE:  # Page Up
        layout_h = stdscr.getmaxyx()[0]  # approximate
        min_scroll = min(layout_h - 3, len(state.history) - 1)
        state.hist_scroll = max(min_scroll, state.hist_scroll - 5)
        return True

    if ch == curses.KEY_NPAGE:  # Page Down
        state.hist_scroll = min(len(state.history) - 1,
                                state.hist_scroll + 5)
        return True

    # -- Layer 5: Command history recall --
    if ch == curses.KEY_UP:
        if state.cmd_history:
            if state.cmd_hist_idx == -1:
                state.cmd_hist_save = state.input_buf
                state.cmd_hist_idx = 0
            elif state.cmd_hist_idx < len(state.cmd_history) - 1:
                state.cmd_hist_idx += 1
            state.input_buf = state.cmd_history[state.cmd_hist_idx]
            state.cursor_pos = len(state.input_buf)
        return True

    if ch == curses.KEY_DOWN:
        if state.cmd_hist_idx >= 0:
            state.cmd_hist_idx -= 1
            if state.cmd_hist_idx == -1:
                state.input_buf = state.cmd_hist_save
            else:
                state.input_buf = state.cmd_history[state.cmd_hist_idx]
            state.cursor_pos = len(state.input_buf)
        return True

    # -- Layer 6: Enter (command input) --
    if ch in (10, 13):
        line = state.input_buf.strip()
        state.input_buf = ""
        state.cursor_pos = 0
        state.cmd_hist_idx = -1
        if not line:
            return True
        # Save to command history (newest first)
        state.cmd_history.insert(0, line)
        if len(state.cmd_history) > MAX_CMD_HISTORY:
            del state.cmd_history[MAX_CMD_HISTORY:]
        return _dispatch_tx_command(state, line, sock)

    # -- Layer 7: Text editing fallback --
    state.input_buf, state.cursor_pos, _ = edit_buffer(
        ch, state.input_buf, state.cursor_pos)
    return True


# =============================================================================
#  RENDER
# =============================================================================

def _render_tx(stdscr, state, zmq_status):
    """Compute layout and draw all panels. Returns False if terminal too small."""
    max_y, max_x = stdscr.getmaxyx()
    stdscr.erase()

    side_open = state.config_open or state.help_open
    layout = calculate_layout(max_y, max_x, side_panel=side_open)
    if layout is None:
        check_terminal_size(stdscr, 80, 24)
        return False

    # Snapshot thread-shared state
    with state.send_lock:
        sending_snap = dict(state.sending)
        history_snap = list(state.history)

    draw_header(stdscr, layout["header"], state.csp, state.ax25,
                state.zmq_addr_disp, freq=state.freq,
                log_path=state.tx_log.text_path,
                zmq_status=zmq_status)

    draw_queue(stdscr, layout["queue"], state.tx_queue,
               scroll_offset=state.queue_scroll,
               sending_idx=(sending_snap["idx"]
                            if sending_snap["active"] else -1),
               tx_delay_ms=state.tx_delay_ms)

    draw_history(stdscr, layout["history"], history_snap,
                 scroll_offset=state.hist_scroll)

    draw_input(stdscr, layout["input"], state.input_buf, state.cursor_pos,
               len(state.tx_queue), state.status.text)

    if state.config_open and "side_panel" in layout:
        if not state.config_values:
            _refresh_config_values(state)
        draw_config(stdscr, layout["side_panel"], state.config_values,
                    state.config_selected, state.config_editing,
                    state.config_buf, state.config_cursor,
                    state.config_focused)
    elif state.help_open and "side_panel" in layout:
        draw_help(stdscr, layout["side_panel"],
                  version=VERSION, schema_count=len(state.cmd_defs),
                  schema_path=CMD_DEFS_PATH,
                  log_path=state.tx_log.text_path)

    stdscr.refresh()
    return True


# =============================================================================
#  DASHBOARD
# =============================================================================

def tx_dashboard(stdscr, *, show_splash=True):
    init_dashboard(stdscr)
    curses.raw()          # disable Ctrl+S/Ctrl+Q flow control so Ctrl+S works
    if show_splash:
        ax = CFG["ax25"]
        cs = CFG["csp"]
        splash_lines = [
            ("Config",    "maveric_gss.yml"),
            ("ZMQ PUB",   ZMQ_ADDR),
            ("Frequency", FREQUENCY),
            ("TX Delay",  f"{TX_DELAY_MS} ms"),
            ("AX.25",     f"GS:{ax['src_call']}-{ax['src_ssid']}"
                          f" -> SAT:{ax['dest_call']}-{ax['dest_ssid']}"),
            ("CSP Prio",  str(cs['priority'])),
            ("CSP Route", f"Src:{cs['source']} -> Dest:{cs['destination']}"),
            ("CSP Ports", f"SPort:{cs['src_port']} DPort:{cs['dest_port']}"),
            ("CSP Flags", f"0x{int(cs['flags']):02X}"),
            ("Commands",  CMD_DEFS_PATH),
            ("Log Text",  f"{LOG_DIR}/text"),
            ("Log JSON",  f"{LOG_DIR}/json"),
        ]
        draw_splash(stdscr, subtitle=f"MAVERIC TX Dashboard  v{VERSION}",
                     config_lines=splash_lines)
    curses.halfdelay(5)   # 500ms timeout for getch — drives clock updates

    csp  = CSPConfig()
    ax25 = AX25Config()
    apply_csp(CFG, csp)
    apply_ax25(CFG, ax25)
    cmd_defs, schema_warning = load_command_defs(CMD_DEFS_PATH)

    ctx, sock, zmq_monitor = init_zmq_pub(ZMQ_ADDR)
    zmq_status = "BOUND"

    # -- State --
    tx_queue, _q_skipped = _load_queue()
    state = TxState(
        csp=csp, ax25=ax25, cmd_defs=cmd_defs,
        tx_queue=tx_queue, history=[],
        tx_log=TXLog(LOG_DIR, ZMQ_ADDR, version=VERSION),
        session_start=time.time(),
        freq=FREQUENCY, zmq_addr_disp=ZMQ_ADDR, tx_delay_ms=TX_DELAY_MS,
    )
    if tx_queue or _q_skipped:
        parts = [f"Restored {len(tx_queue)} queued "
                 f"command{'s' if len(tx_queue) != 1 else ''}"]
        if _q_skipped:
            parts.append(f" ({_q_skipped} skipped — corrupt)")
        state.status.set("".join(parts), 5)
    if schema_warning:
        state.status.set(f"SCHEMA: {schema_warning}", 10)

    try:
        while True:
            state.status.check_expiry()
            zmq_status = poll_monitor(zmq_monitor, _PUB_STATUS, zmq_status)

            if not _render_tx(stdscr, state, zmq_status):
                # Terminal too small — wait for resize or Ctrl+C
                try:
                    ch = stdscr.getch()
                except KeyboardInterrupt:
                    break
                if ch == 3:
                    break
                continue

            try:
                ch = stdscr.getch()
            except KeyboardInterrupt:
                break
            if ch == curses.ERR or ch == curses.KEY_RESIZE:
                continue
            if handle_key_tx(ch, state, stdscr, sock) == "break":
                break

    finally:
        try:
            state.tx_log.write_summary(state.tx_count, state.session_start)
            state.tx_log.close()
        except Exception:
            pass
        zmq_cleanup(zmq_monitor, _PUB_STATUS, zmq_status, sock, ctx)

    return state.tx_count, state.tx_log.text_path


def main():
    parser = argparse.ArgumentParser(description="MAVERIC TX Dashboard")
    parser.add_argument("--nosplash", action="store_true",
                        help="skip the startup splash screen")
    args = parser.parse_args()

    tx_count, logpath = curses.wrapper(lambda stdscr: tx_dashboard(
        stdscr, show_splash=not args.nosplash))
    # Print session summary after curses restores the terminal
    print()
    print(f"  Session ended")
    print(f"  Transmitted:  {tx_count}")
    print(f"  Log:          {logpath}")
    print()


if __name__ == "__main__":
    main()
