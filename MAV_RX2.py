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
import threading
import time
from collections import OrderedDict
from datetime import datetime

from mav_gss_lib.protocol import init_nodes, load_command_defs
from mav_gss_lib.transport import init_zmq_sub, receive_pdu
from mav_gss_lib.parsing import process_rx_packet, build_rx_log_record
from mav_gss_lib.logging import SessionLog
from mav_gss_lib.curses_common import init_colors, draw_splash, edit_buffer
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
#  ZMQ RECEIVER THREAD
# =============================================================================

def _receiver_thread(sock, pkt_queue, stop_event, on_error=None):
    """Background thread: continuously drain ZMQ into a thread-safe queue."""
    while not stop_event.is_set():
        result = receive_pdu(sock, on_error=on_error)
        if result is not None:
            pkt_queue.put(result)


# =============================================================================
#  DASHBOARD
# =============================================================================

def rx_dashboard(stdscr, show_splash=True):
    curses.curs_set(0)
    curses.set_escdelay(25)  # fast Esc response (25ms instead of default 1000ms)
    init_colors()
    stdscr.keypad(True)
    tx_freq_map = _load_tx_frequencies(DECODER_YML_PATH)
    # Pick first frequency from decoder YAML for display
    rx_freq = next(iter(tx_freq_map.values()), "N/A")

    if show_splash:
        splash_lines = [
            ("Config",    "maveric_gss.yml"),
            ("ZMQ SUB",   ZMQ_ADDR),
            ("Frequency", rx_freq),
            ("Decoder",   DECODER_YML_PATH),
            ("Commands",  CMD_DEFS_PATH),
            ("Log Dir",   LOG_DIR),
        ]
        draw_splash(stdscr, subtitle=f"MAVERIC RX Monitor  v{VERSION}",
                     config_lines=splash_lines)
    curses.halfdelay(2)  # 200ms timeout for getch

    # -- Init ZMQ, logging, schema --
    context, sock = init_zmq_sub(ZMQ_ADDR, ZMQ_RECV_TIMEOUT_MS)
    cmd_defs = load_command_defs(CMD_DEFS_PATH)

    # -- State --
    packets = []
    packet_count = 0
    unknown_count = 0
    uplink_echo_count = 0
    last_arrival = None
    last_watchdog = time.time()
    session_start = time.time()
    first_pkt_ts = None
    last_pkt_ts = None
    seen_fps = OrderedDict()
    pkt_times = []
    last_gc = time.time()

    # UI state
    selected_idx = -1       # -1 = auto-follow
    scroll_offset = 0
    detail_open = False
    help_open = False
    config_open = False
    config_focused = False
    config_selected = 0
    show_hex = True
    logging_enabled = True
    frequency = "--"
    log = SessionLog(LOG_DIR, ZMQ_ADDR, version=VERSION)
    error_msg = ""
    error_expire = 0
    status_msg = ""
    status_expire = 0
    input_buf = ""
    cursor_pos = 0
    receiving = False       # True when packets arrived this cycle
    RECEIVING_TIMEOUT = 2.0 # seconds to show "Receiving" after last packet

    spinner = ["\u2588", "\u2593", "\u2592", "\u2591", "\u2592", "\u2593"]
    spin_idx = 0

    def toggle_logging():
        """Toggle logging on/off, returning a status message."""
        nonlocal logging_enabled, log
        if logging_enabled:
            logging_enabled = False
            if log:
                log.write_summary(packet_count, session_start,
                                  first_pkt_ts, last_pkt_ts,
                                  unique=len(seen_fps),
                                  duplicates=packet_count - len(seen_fps),
                                  unknown=unknown_count,
                                  uplink_echoes=uplink_echo_count)
                log.close()
                log = None
            return "Logging OFF", 2
        else:
            logging_enabled = True
            log = SessionLog(LOG_DIR, ZMQ_ADDR, version=VERSION)
            return f"Logging ON: {log.text_path}", 3

    # -- Start receiver thread --
    pkt_queue = queue.Queue()
    stop_event = threading.Event()

    def on_zmq_error(msg):
        nonlocal error_msg, error_expire
        error_msg = msg
        error_expire = time.time() + 5

    rx_thread = threading.Thread(
        target=_receiver_thread,
        args=(sock, pkt_queue, stop_event, on_zmq_error),
        daemon=True,
    )
    rx_thread.start()

    try:
        while True:
            # -- Phase A: Drain packet queue --
            batch = 0
            while True:
                try:
                    meta, raw = pkt_queue.get_nowait()
                except queue.Empty:
                    break

                last_watchdog = time.time()
                if first_pkt_ts is None:
                    first_pkt_ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

                # Process packet through library pipeline
                try:
                    pkt_record, counters = process_rx_packet(
                        meta, raw, cmd_defs, seen_fps, tx_freq_map,
                        last_arrival, packet_count, unknown_count,
                        uplink_echo_count, pkt_times, MAX_SEEN_FPS,
                    )
                except Exception as e:
                    error_msg = f"Packet error: {e}"
                    continue

                # Update state from counters
                packet_count = counters["packet_count"]
                unknown_count = counters["unknown_count"]
                uplink_echo_count = counters["uplink_echo_count"]
                last_arrival = counters["last_arrival"]
                if counters["frequency"] is not None:
                    frequency = counters["frequency"]
                last_pkt_ts = pkt_record["gs_ts"]

                # Log
                if logging_enabled and log:
                    try:
                        log_record = build_rx_log_record(pkt_record, VERSION, meta)
                        log.write_jsonl(log_record)
                        log.write_packet(pkt_record)
                    except Exception as e:
                        error_msg = f"Log error: {e}"

                # Store packet record for display
                packets.append(pkt_record)
                if len(packets) > MAX_PACKETS:
                    del packets[:len(packets) - MAX_PACKETS]

                # Auto-follow: advance selection to newest
                if selected_idx == -1:
                    pass  # auto-follow handled in draw
                elif selected_idx >= len(packets) - 1:
                    selected_idx = len(packets) - 1

                batch += 1

            # Update receiving state
            now_check = time.time()
            receiving = (now_check - last_watchdog) < RECEIVING_TIMEOUT

            # -- Phase B: Handle keyboard --
            try:
                ch = stdscr.getch()
            except KeyboardInterrupt:
                break

            if ch == curses.ERR:
                # Timeout — update spinner, gc check
                spin_idx = (spin_idx + 1) % len(spinner)
                now_idle = time.time()
                if now_idle - last_gc > GC_INTERVAL:
                    gc.collect()
                    last_gc = now_idle
            elif ch == curses.KEY_RESIZE:
                pass  # just redraw
            elif ch == 3:  # Ctrl+C
                if help_open:
                    help_open = False
                elif config_open:
                    config_open = False
                    config_focused = False
                else:
                    break
            elif ch == 27:  # Esc
                if help_open:
                    help_open = False
                elif config_open:
                    config_open = False
                    config_focused = False
                elif detail_open:
                    detail_open = False

            # Tab: toggle focus between config panel and input
            elif ch == 9 and config_open:  # Tab
                config_focused = not config_focused

            # Config panel navigation (when focused)
            elif config_focused and config_open and ch == curses.KEY_UP:
                config_selected = (config_selected - 1) % len(RX_CONFIG_FIELDS)
            elif config_focused and config_open and ch == curses.KEY_DOWN:
                config_selected = (config_selected + 1) % len(RX_CONFIG_FIELDS)
            elif config_focused and config_open and ch in (10, 13):  # Enter toggles
                key = RX_CONFIG_FIELDS[config_selected][1]
                if key == "show_hex":
                    show_hex = not show_hex
                    status_msg = f"HEX {'ON' if show_hex else 'OFF'}"
                    status_expire = time.time() + 2
                elif key == "logging":
                    status_msg, dur = toggle_logging()
                    status_expire = time.time() + dur

            elif ch == curses.KEY_UP:
                if selected_idx == -1:
                    selected_idx = len(packets) - 1 if packets else 0
                elif selected_idx > 0:
                    selected_idx -= 1
            elif ch == curses.KEY_DOWN:
                if selected_idx == -1:
                    pass  # already at bottom
                elif selected_idx < len(packets) - 1:
                    selected_idx += 1
                else:
                    selected_idx = -1  # re-enable auto-follow
            elif ch == curses.KEY_PPAGE:  # Page Up
                if selected_idx == -1:
                    selected_idx = len(packets) - 1 if packets else 0
                max_y, _ = stdscr.getmaxyx()
                page = max(1, max_y - 10)
                selected_idx = max(0, selected_idx - page)
            elif ch == curses.KEY_NPAGE:  # Page Down
                if selected_idx == -1:
                    pass
                else:
                    max_y, _ = stdscr.getmaxyx()
                    page = max(1, max_y - 10)
                    selected_idx = min(len(packets) - 1, selected_idx + page)
            elif ch in (10, 13):  # Enter
                line = input_buf.strip()
                input_buf = ""
                cursor_pos = 0

                if not line:
                    # No text — toggle detail panel
                    detail_open = not detail_open
                else:
                    low = line.lower()
                    if low in ('q', 'quit', 'exit'):
                        break
                    elif low == 'help':
                        help_open = not help_open
                        if help_open:
                            config_open = False
                            config_focused = False
                    elif low in ('cfg', 'config'):
                        config_open = not config_open
                        config_focused = config_open
                        if config_open:
                            help_open = False
                    elif low == 'hex':
                        show_hex = not show_hex
                        status_msg = f"HEX {'ON' if show_hex else 'OFF'}"
                        status_expire = time.time() + 2
                    elif low == 'log':
                        status_msg, dur = toggle_logging()
                        status_expire = time.time() + dur
                    elif low == 'detail':
                        detail_open = not detail_open
                    elif low == 'hclear':
                        if packets:
                            status_msg = f"Cleared {len(packets)} packets"
                            status_expire = time.time() + 2
                            packets.clear()
                            selected_idx = -1
                            scroll_offset = 0
                        else:
                            status_msg = "History already empty"
                            status_expire = time.time() + 2
                    elif low == 'live':
                        selected_idx = -1
                    else:
                        status_msg = f"Unknown command: {line}"
                        status_expire = time.time() + 3
            else:
                # Text editing
                input_buf, cursor_pos, _ = edit_buffer(ch, input_buf, cursor_pos)

            # Clear expired messages
            now_t = time.time()
            if error_msg and now_t >= error_expire:
                error_msg = ""
            if status_msg and now_t >= status_expire:
                status_msg = ""

            # -- Phase C: Redraw --
            max_y, max_x = stdscr.getmaxyx()
            stdscr.erase()

            side_open = help_open or config_open
            layout = calculate_rx_layout(max_y, max_x,
                                         detail_open=detail_open,
                                         side_panel=side_open)
            if layout is None:
                try:
                    stdscr.addstr(0, 0,
                                  f"Terminal too small (need 80x{20}, have {max_x}x{max_y})")
                except curses.error:
                    pass
                stdscr.refresh()
                continue

            # Compute auto-follow and actual selected index
            auto_follow = (selected_idx == -1)
            actual_selected = len(packets) - 1 if auto_follow and packets else selected_idx

            # Compute scroll offset for non-auto-follow mode
            if not auto_follow and packets:
                list_h = layout["packet_list"][2] - 2  # data rows
                if actual_selected < scroll_offset:
                    scroll_offset = actual_selected
                elif actual_selected >= scroll_offset + list_h:
                    scroll_offset = actual_selected - list_h + 1
                scroll_offset = max(0, scroll_offset)
            else:
                scroll_offset = 0

            # Silence timer
            silence_secs = time.time() - last_watchdog

            # Rate
            now_rate = time.time()
            rate_per_min = sum(1 for t in pkt_times if t > now_rate - 60.0)

            draw_rx_header(stdscr, layout["header"], ZMQ_ADDR,
                           freq=frequency, show_hex=show_hex,
                           logging_enabled=logging_enabled)
            draw_packet_list(stdscr, layout["packet_list"], packets,
                             actual_selected, scroll_offset,
                             auto_follow=auto_follow)

            if detail_open and "detail" in layout:
                detail_pkt = None
                if 0 <= actual_selected < len(packets):
                    detail_pkt = packets[actual_selected]
                draw_packet_detail(stdscr, layout["detail"], detail_pkt,
                                   show_hex=show_hex)

            draw_rx_input(stdscr, layout["input"], input_buf, cursor_pos,
                          silence_secs, packet_count, rate_per_min,
                          receiving=receiving,
                          spinner_char=spinner[spin_idx],
                          status_msg=status_msg, error_msg=error_msg)

            if help_open and "side_panel" in layout:
                draw_rx_help(stdscr, layout["side_panel"],
                             schema_count=len(cmd_defs),
                             schema_path=CMD_DEFS_PATH,
                             log_txt=log.text_path if log else "(disabled)",
                             log_jsonl=log.jsonl_path if log else "(disabled)",
                             version=VERSION)
            elif config_open and "side_panel" in layout:
                cfg_vals = rx_config_get_values(show_hex, logging_enabled)
                draw_rx_config(stdscr, layout["side_panel"], cfg_vals,
                               selected=config_selected,
                               focused=config_focused)

            stdscr.refresh()

    finally:
        stop_event.set()
        rx_thread.join(timeout=1)
        try:
            if log:
                log.write_summary(packet_count, session_start,
                                  first_pkt_ts, last_pkt_ts,
                                  unique=len(seen_fps),
                                  duplicates=packet_count - len(seen_fps),
                                  unknown=unknown_count,
                                  uplink_echoes=uplink_echo_count)
                log.close()
        except Exception:
            pass
        try:
            sock.close()
            context.term()
        except Exception:
            pass

    return {
        "packet_count": packet_count,
        "unique": len(seen_fps),
        "duplicates": packet_count - len(seen_fps),
        "unknown": unknown_count,
        "uplink_echoes": uplink_echo_count,
        "duration": time.time() - session_start,
        "log_txt": log.text_path if log else None,
        "log_jsonl": log.jsonl_path if log else None,
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
