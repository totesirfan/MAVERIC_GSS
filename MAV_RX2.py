"""
MAV_RX2 -- MAVERIC Ground Station Monitor (Curses Dashboard)

Curses-based downlink packet monitor for the MAVERIC CubeSat mission.
Subscribes to decoded PDUs from a GNU Radio / gr-satellites flowgraph
over ZMQ PUB/SUB and displays packets in a scrollable, interactive
dashboard.

Features:
  - Live packet list with auto-follow
  - Packet detail panel (Enter to toggle)
  - Hex/ASCII display toggle (t key)
  - Logging toggle (l key)
  - Help panel (? key)
  - Threaded ZMQ receiver (no packet loss)

The original MAV_RX.py (terminal/ANSI version) is unmodified.

Author:  Irfan Annuar - USC ISI SERC
"""

import argparse
import curses
import gc
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

from mav_gss_lib.protocol import init_nodes, load_command_defs
from mav_gss_lib.transport import (init_zmq_sub, receive_pdu,
                                   poll_monitor, _SUB_STATUS, zmq_cleanup)
from mav_gss_lib.parsing import RxPipeline, build_rx_log_record
from mav_gss_lib.logging import SessionLog
from mav_gss_lib.curses_common import (init_dashboard, draw_splash, edit_buffer,
                                       StatusMessage, check_terminal_size,
                                       navigate_config)
from mav_gss_lib.config import load_gss_config
from mav_gss_lib.curses_rx import (
    calculate_rx_layout,
    draw_rx_header, draw_packet_list, draw_packet_detail,
    draw_rx_input, draw_rx_help,
    draw_rx_config, rx_config_get_values, RX_CONFIG_FIELDS,
)

# -- Config -------------------------------------------------------------------

CFG = load_gss_config()
init_nodes(CFG)

VERSION = CFG["general"]["version"]
ZMQ_PORT = str(CFG["rx"]["zmq_port"])
ZMQ_ADDR = CFG["rx"]["zmq_addr"]
ZMQ_RECV_TIMEOUT_MS = 200
LOG_DIR = CFG["general"]["log_dir"]
CMD_DEFS_PATH = CFG["general"]["command_defs"]
DECODER_YML_PATH = CFG["general"]["decoder_yml"]
MAX_PACKETS = 500
MAX_SEEN_FPS = 10_000
GC_INTERVAL = 300
RECEIVING_TIMEOUT = 2.0

SPINNER = ["\u2588", "\u2593", "\u2592", "\u2591", "\u2592", "\u2593"]


def _load_tx_frequencies(path):
    """Load transmitter->frequency map from gr-satellites decoder YAML."""
    try:
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        tx_map = {}
        for name, info in data.get("transmitters", {}).items():
            freq_hz = info.get("frequency")
            if freq_hz is not None:
                freq_mhz = float(freq_hz) / 1e6
                tx_map[name] = f"{freq_mhz:.3f} MHz"
        return tx_map
    except Exception:
        return {}


# =============================================================================
#  STATE
# =============================================================================

@dataclass
class RxState:
    # Data / pipeline
    packets: list
    pipeline: RxPipeline
    log: SessionLog | None
    cmd_defs: dict
    # Timing
    session_start: float
    last_watchdog: float
    first_pkt_ts: str | None = None
    last_pkt_ts: str | None = None
    last_gc: float = 0.0
    # UI panels
    selected_idx: int = -1          # -1 = auto-follow
    scroll_offset: int = 0
    detail_open: bool = False
    help_open: bool = False
    config_open: bool = False
    config_focused: bool = False
    config_selected: int = 0
    show_hex: bool = True
    logging_enabled: bool = True
    receiving: bool = False
    frequency: str = "--"
    # Input
    input_buf: str = ""
    cursor_pos: int = 0
    # Status
    error_status: StatusMessage = field(default_factory=StatusMessage)
    status: StatusMessage = field(default_factory=StatusMessage)
    spin_idx: int = 0


# =============================================================================
#  ZMQ RECEIVER THREAD
# =============================================================================

def _receiver_thread(sock, pkt_queue, stop_event, monitor, status_holder,
                     on_error=None):
    """Background thread: continuously drain ZMQ into a thread-safe queue."""
    while not stop_event.is_set():
        result = receive_pdu(sock, on_error=on_error)
        if result is not None:
            pkt_queue.put(result)
        status_holder[0] = poll_monitor(monitor, _SUB_STATUS, status_holder[0])


# =============================================================================
#  QUEUE DRAIN
# =============================================================================

def _drain_rx_queue(state, pkt_queue):
    """Drain all pending packets from the queue into state."""
    while True:
        try:
            meta, raw = pkt_queue.get_nowait()
        except queue.Empty:
            break

        state.last_watchdog = time.time()
        if state.first_pkt_ts is None:
            state.first_pkt_ts = datetime.now().astimezone().strftime(
                "%Y-%m-%d %H:%M:%S %Z")

        try:
            pkt_record = state.pipeline.process(meta, raw)
        except Exception as e:
            state.error_status.set(f"Packet error: {e}", 5)
            continue

        if state.pipeline.frequency is not None:
            state.frequency = state.pipeline.frequency
        state.last_pkt_ts = pkt_record["gs_ts"]

        if state.logging_enabled and state.log:
            try:
                log_record = build_rx_log_record(pkt_record, VERSION, meta)
                state.log.write_jsonl(log_record)
                state.log.write_packet(pkt_record)
            except Exception as e:
                state.error_status.set(f"Log error: {e}", 5)

        state.packets.append(pkt_record)
        if len(state.packets) > MAX_PACKETS:
            del state.packets[:len(state.packets) - MAX_PACKETS]

        if state.selected_idx == -1:
            pass  # auto-follow handled in render
        elif state.selected_idx >= len(state.packets) - 1:
            state.selected_idx = len(state.packets) - 1

    state.receiving = (time.time() - state.last_watchdog) < RECEIVING_TIMEOUT


# =============================================================================
#  LOGGING TOGGLE
# =============================================================================

def _toggle_logging(state):
    """Toggle logging on/off, returning a (message, duration) tuple."""
    if state.logging_enabled:
        state.logging_enabled = False
        if state.log:
            try:
                state.log.write_summary(
                    state.pipeline.packet_count, state.session_start,
                    state.first_pkt_ts, state.last_pkt_ts,
                    unique=len(state.pipeline.seen_fps),
                    duplicates=(state.pipeline.packet_count
                                - len(state.pipeline.seen_fps)),
                    unknown=state.pipeline.unknown_count,
                    uplink_echoes=state.pipeline.uplink_echo_count)
            except Exception:
                pass
            finally:
                try:
                    state.log.close()
                except Exception:
                    pass
                state.log = None
        return "Logging OFF", 2
    else:
        try:
            state.log = SessionLog(LOG_DIR, ZMQ_ADDR, version=VERSION)
        except Exception as e:
            state.logging_enabled = False
            state.log = None
            return f"Log error: {e}", 5
        state.logging_enabled = True
        return f"Logging ON: {state.log.text_path}", 3


# =============================================================================
#  KEYBOARD DISPATCH
# =============================================================================

def _dispatch_rx_command(state, line):
    """Handle a typed command. Returns 'break' to exit, True otherwise."""
    cmd = line.lower()

    if cmd in ('q', 'quit', 'exit'):
        return "break"

    if cmd == 'help':
        state.help_open = not state.help_open
        if state.help_open:
            state.config_open = False
            state.config_focused = False
    elif cmd in ('cfg', 'config'):
        state.config_open = not state.config_open
        state.config_focused = state.config_open
        if state.config_open:
            state.help_open = False
    elif cmd == 'hex':
        state.show_hex = not state.show_hex
        state.status.set(f"HEX {'ON' if state.show_hex else 'OFF'}", 2)
    elif cmd == 'log':
        msg, dur = _toggle_logging(state)
        state.status.set(msg, dur)
    elif cmd == 'detail':
        state.detail_open = not state.detail_open
    elif cmd == 'hclear':
        if state.packets:
            state.status.set(f"Cleared {len(state.packets)} packets", 2)
            state.packets.clear()
            state.selected_idx = -1
            state.scroll_offset = 0
        else:
            state.status.set("History already empty", 2)
    elif cmd == 'live':
        state.selected_idx = -1
    else:
        state.status.set(f"Unknown command: {line}", 3)

    return True


def handle_key_rx(ch, state, stdscr):
    """Dispatch a keypress through layered RX handlers.

    Returns 'break' to exit the main loop, True otherwise.
    """
    # -- Layer 0: Global overrides (Ctrl+C, Esc) --
    if ch == 3:  # Ctrl+C
        if state.help_open:
            state.help_open = False
        elif state.config_open:
            state.config_open = False
            state.config_focused = False
        else:
            return "break"
        return True

    if ch == 27:  # Esc
        if state.help_open:
            state.help_open = False
        elif state.config_open:
            state.config_open = False
            state.config_focused = False
        elif state.detail_open:
            state.detail_open = False
        return True

    # -- Layer 1: Config panel focused keys --
    if state.config_focused and state.config_open:
        if ch in (curses.KEY_UP, curses.KEY_DOWN):
            nav = navigate_config(ch, state.config_selected,
                                  len(RX_CONFIG_FIELDS))
            if nav is not None:
                state.config_selected = nav
            return True
        if ch in (10, 13):  # Enter toggles config field
            key = RX_CONFIG_FIELDS[state.config_selected][1]
            if key == "show_hex":
                state.show_hex = not state.show_hex
                state.status.set(
                    f"HEX {'ON' if state.show_hex else 'OFF'}", 2)
            elif key == "logging":
                msg, dur = _toggle_logging(state)
                state.status.set(msg, dur)
            return True

    # -- Layer 2: Tab (config focus toggle) --
    if ch == 9 and state.config_open:
        state.config_focused = not state.config_focused
        return True

    # -- Layer 3: Packet navigation --
    if ch == curses.KEY_UP:
        if state.selected_idx == -1:
            state.selected_idx = (len(state.packets) - 1
                                  if state.packets else 0)
        elif state.selected_idx > 0:
            state.selected_idx -= 1
        return True

    if ch == curses.KEY_DOWN:
        if state.selected_idx == -1:
            pass  # already at bottom
        elif state.selected_idx < len(state.packets) - 1:
            state.selected_idx += 1
        else:
            state.selected_idx = -1  # re-enable auto-follow
        return True

    if ch == curses.KEY_PPAGE:  # Page Up
        if state.selected_idx == -1:
            state.selected_idx = (len(state.packets) - 1
                                  if state.packets else 0)
        max_y, _ = stdscr.getmaxyx()
        page = max(1, max_y - 10)
        state.selected_idx = max(0, state.selected_idx - page)
        return True

    if ch == curses.KEY_NPAGE:  # Page Down
        if state.selected_idx != -1:
            max_y, _ = stdscr.getmaxyx()
            page = max(1, max_y - 10)
            state.selected_idx = min(len(state.packets) - 1,
                                     state.selected_idx + page)
        return True

    # -- Layer 4: Enter (command input) --
    if ch in (10, 13):
        line = state.input_buf.strip()
        state.input_buf = ""
        state.cursor_pos = 0
        if not line:
            state.detail_open = not state.detail_open
            return True
        return _dispatch_rx_command(state, line)

    # -- Layer 5: Text editing fallback --
    state.input_buf, state.cursor_pos, _ = edit_buffer(
        ch, state.input_buf, state.cursor_pos)
    return True


# =============================================================================
#  RENDER
# =============================================================================

def _render_rx(stdscr, state, pkt_queue, zmq_status):
    """Compute layout and draw all panels."""
    max_y, max_x = stdscr.getmaxyx()
    stdscr.erase()

    side_open = state.help_open or state.config_open
    layout = calculate_rx_layout(max_y, max_x,
                                 detail_open=state.detail_open,
                                 side_panel=side_open)
    if layout is None:
        check_terminal_size(stdscr, 80, 20)
        return

    # Auto-follow and scroll
    auto_follow = (state.selected_idx == -1)
    actual_selected = (len(state.packets) - 1
                       if auto_follow and state.packets
                       else state.selected_idx)

    if not auto_follow and state.packets:
        list_h = layout["packet_list"][2] - 2
        if actual_selected < state.scroll_offset:
            state.scroll_offset = actual_selected
        elif actual_selected >= state.scroll_offset + list_h:
            state.scroll_offset = actual_selected - list_h + 1
        state.scroll_offset = max(0, state.scroll_offset)
    else:
        state.scroll_offset = 0

    silence_secs = time.time() - state.last_watchdog

    now_rate = time.time()
    rate_per_min = sum(1 for t in state.pipeline.pkt_times
                       if t > now_rate - 60.0)

    # -- Draw panels --
    draw_rx_header(stdscr, layout["header"], ZMQ_ADDR,
                   freq=state.frequency, show_hex=state.show_hex,
                   logging_enabled=state.logging_enabled,
                   queue_depth=pkt_queue.qsize(),
                   zmq_status=zmq_status)

    draw_packet_list(stdscr, layout["packet_list"], state.packets,
                     actual_selected, state.scroll_offset,
                     auto_follow=auto_follow)

    if state.detail_open and "detail" in layout:
        detail_pkt = None
        if 0 <= actual_selected < len(state.packets):
            detail_pkt = state.packets[actual_selected]
        draw_packet_detail(stdscr, layout["detail"], detail_pkt,
                           show_hex=state.show_hex)

    draw_rx_input(stdscr, layout["input"],
                  state.input_buf, state.cursor_pos,
                  silence_secs, state.pipeline.packet_count, rate_per_min,
                  receiving=state.receiving,
                  spinner_char=SPINNER[state.spin_idx],
                  status_msg=state.status.text,
                  error_msg=state.error_status.text)

    if state.help_open and "side_panel" in layout:
        draw_rx_help(stdscr, layout["side_panel"],
                     schema_count=len(state.cmd_defs),
                     schema_path=CMD_DEFS_PATH,
                     log_txt=(state.log.text_path
                              if state.log else "(disabled)"),
                     log_jsonl=(state.log.jsonl_path
                                if state.log else "(disabled)"),
                     version=VERSION)
    elif state.config_open and "side_panel" in layout:
        cfg_vals = rx_config_get_values(state.show_hex,
                                        state.logging_enabled)
        draw_rx_config(stdscr, layout["side_panel"], cfg_vals,
                       selected=state.config_selected,
                       focused=state.config_focused)

    stdscr.refresh()


# =============================================================================
#  DASHBOARD
# =============================================================================

def rx_dashboard(stdscr, show_splash=True):
    init_dashboard(stdscr)
    tx_freq_map = _load_tx_frequencies(DECODER_YML_PATH)
    rx_freq = next(iter(tx_freq_map.values()), "N/A")

    if show_splash:
        splash_lines = [
            ("Config",    "maveric_gss.yml"),
            ("ZMQ SUB",   ZMQ_ADDR),
            ("Frequency", rx_freq),
            ("Decoder",   DECODER_YML_PATH),
            ("Commands",  CMD_DEFS_PATH),
            ("Log Text",  f"{LOG_DIR}/text"),
            ("Log JSON",  f"{LOG_DIR}/json"),
        ]
        draw_splash(stdscr, subtitle=f"MAVERIC RX Monitor  v{VERSION}",
                     config_lines=splash_lines)
    curses.halfdelay(2)  # 200ms timeout for getch

    # -- Init ZMQ, logging, schema --
    context, sock, zmq_monitor = init_zmq_sub(ZMQ_ADDR, ZMQ_RECV_TIMEOUT_MS)
    cmd_defs, _schema_warning = load_command_defs(CMD_DEFS_PATH)

    # -- State --
    now = time.time()
    pipeline = RxPipeline(cmd_defs, tx_freq_map, MAX_SEEN_FPS)
    state = RxState(
        packets=[], pipeline=pipeline,
        log=SessionLog(LOG_DIR, ZMQ_ADDR, version=VERSION),
        cmd_defs=cmd_defs,
        session_start=now, last_watchdog=now, last_gc=now,
    )
    if _schema_warning:
        state.error_status.set(f"SCHEMA: {_schema_warning}", 10)

    # -- Receiver thread --
    pkt_queue = queue.Queue()
    stop_event = threading.Event()
    zmq_status = ["SUB"]

    def on_zmq_error(msg):
        state.error_status.set(msg, 5)

    rx_thread = threading.Thread(
        target=_receiver_thread,
        args=(sock, pkt_queue, stop_event, zmq_monitor, zmq_status,
              on_zmq_error),
        daemon=True,
    )
    rx_thread.start()

    try:
        while True:
            _drain_rx_queue(state, pkt_queue)

            try:
                ch = stdscr.getch()
            except KeyboardInterrupt:
                break

            if ch == curses.ERR:
                state.spin_idx = (state.spin_idx + 1) % len(SPINNER)
                if time.time() - state.last_gc > GC_INTERVAL:
                    gc.collect()
                    state.last_gc = time.time()
            elif ch != curses.KEY_RESIZE:
                if handle_key_rx(ch, state, stdscr) == "break":
                    break

            state.error_status.check_expiry()
            state.status.check_expiry()
            _render_rx(stdscr, state, pkt_queue, zmq_status[0])

    finally:
        stop_event.set()
        rx_thread.join(timeout=1)
        if rx_thread.is_alive():
            print("WARNING: RX thread did not terminate cleanly",
                  file=sys.stderr)
        try:
            if state.log:
                state.log.write_summary(
                    state.pipeline.packet_count, state.session_start,
                    state.first_pkt_ts, state.last_pkt_ts,
                    unique=len(state.pipeline.seen_fps),
                    duplicates=(state.pipeline.packet_count
                                - len(state.pipeline.seen_fps)),
                    unknown=state.pipeline.unknown_count,
                    uplink_echoes=state.pipeline.uplink_echo_count)
                state.log.close()
        except Exception:
            pass
        zmq_cleanup(zmq_monitor, _SUB_STATUS, zmq_status[0], sock, context)

    return {
        "packet_count": state.pipeline.packet_count,
        "unique": len(state.pipeline.seen_fps),
        "duplicates": (state.pipeline.packet_count
                       - len(state.pipeline.seen_fps)),
        "unknown": state.pipeline.unknown_count,
        "uplink_echoes": state.pipeline.uplink_echo_count,
        "duration": time.time() - state.session_start,
        "log_txt": state.log.text_path if state.log else None,
        "log_jsonl": state.log.jsonl_path if state.log else None,
    }


# =============================================================================
#  MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="MAV_RX2 -- MAVERIC Ground Station Monitor (Curses)")
    parser.add_argument("--nosplash", action="store_true",
                        help="skip the startup splash screen")
    args = parser.parse_args()

    result = curses.wrapper(lambda stdscr: rx_dashboard(
        stdscr, show_splash=not args.nosplash))

    # Post-curses summary
    print()
    print(f"  Session ended")
    print(f"  Packets:    {result['packet_count']}  "
          f"({result['unique']} unique, {result['duplicates']} duplicate, "
          f"{result['unknown']} unknown, {result['uplink_echoes']} uplink echo)")
    print(f"  Duration:   {result['duration']:.0f}s "
          f"({result['duration']/60:.1f} min)")
    if result.get("log_txt"):
        print(f"  Log (txt):  {result['log_txt']}")
        print(f"  Log (json): {result['log_jsonl']}")
    print()


if __name__ == "__main__":
    main()
