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
import time
from datetime import datetime

import mav_gss_lib.protocol as protocol
from mav_gss_lib.protocol import (
    init_nodes, node_label,
    build_cmd_raw, AX25Config, CSPConfig,
    load_command_defs, validate_args, parse_cmd_line,
)
from mav_gss_lib.transport import init_zmq_pub, send_pdu
from mav_gss_lib.logging import TXLog
from mav_gss_lib.curses_common import init_colors, draw_splash, edit_buffer
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


# -- Dashboard ----------------------------------------------------------------

def dashboard(stdscr, *, show_splash=True):
    curses.curs_set(0)
    curses.raw()          # disable Ctrl+S/Ctrl+Q flow control so Ctrl+S works
    curses.set_escdelay(25)  # fast Esc response (25ms instead of default 1000ms)
    init_colors()
    stdscr.keypad(True)   # enable KEY_LEFT, KEY_UP, etc.
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
            ("Log Dir",   LOG_DIR),
        ]
        draw_splash(stdscr, subtitle=f"MAVERIC TX Dashboard  v{VERSION}",
                     config_lines=splash_lines)
    curses.halfdelay(5)   # 500ms timeout for getch — drives clock updates

    csp  = CSPConfig()
    ax25 = AX25Config()
    apply_csp(CFG, csp)
    apply_ax25(CFG, ax25)
    cmd_defs = load_command_defs(CMD_DEFS_PATH)

    ctx, sock = init_zmq_pub(ZMQ_ADDR)
    tx_log = TXLog(LOG_DIR, ZMQ_ADDR, version=VERSION)
    session_start = time.time()

    queue   = []       # list of (src, dest, echo, ptype, cmd, args, raw_cmd)
    history = []       # list of dicts
    input_buf  = ""
    cursor_pos = 0
    n = 0              # TX counter
    status_msg    = ""
    status_expire = 0
    queue_scroll  = 0
    hist_scroll   = 0
    cmd_history   = []   # input history for up/down recall
    cmd_hist_idx  = -1   # -1 = not browsing history
    cmd_hist_save = ""   # saved current input when browsing
    freq          = FREQUENCY  # mutable so config panel can change it
    zmq_addr_disp = ZMQ_ADDR   # display value (port change needs restart)
    tx_delay_ms   = TX_DELAY_MS  # delay between queued commands (ms)

    # Side panel state
    help_open       = False
    config_open     = False
    config_focused  = False   # Tab toggles focus between config and input
    config_selected = 0
    config_editing  = False
    config_buf      = ""
    config_cursor   = 0
    config_values   = {}

    def set_status(msg, duration=3):
        nonlocal status_msg, status_expire
        status_msg = msg
        status_expire = time.time() + duration

    def redraw(sending_idx=-1):
        """Redraw all panels (used during send to show progress)."""
        max_y, max_x = stdscr.getmaxyx()
        stdscr.erase()
        side_open = config_open or help_open
        layout = calculate_layout(max_y, max_x, side_panel=side_open)
        if layout is None:
            return
        draw_header(stdscr, layout["header"], csp, ax25, zmq_addr_disp,
                    freq=freq, log_path=tx_log.text_path)
        draw_queue(stdscr, layout["queue"], queue,
                   scroll_offset=queue_scroll, sending_idx=sending_idx,
                   tx_delay_ms=tx_delay_ms)
        draw_history(stdscr, layout["history"], history,
                     scroll_offset=hist_scroll)
        draw_input(stdscr, layout["input"], input_buf, cursor_pos,
                   len(queue), status_msg)
        stdscr.refresh()

    def send_queue():
        nonlocal n, queue_scroll, hist_scroll
        if not queue:
            set_status("Nothing queued", 2)
            return
        count = len(queue)
        for i, (src, dest, echo, ptype, cmd, args, raw_cmd) in enumerate(queue):
            # Show this command as "SENDING", previous as "SENT"
            redraw(sending_idx=i)
            if i > 0 and tx_delay_ms > 0:
                curses.napms(tx_delay_ms)
            payload = ax25.wrap(csp.wrap(raw_cmd))
            n += 1
            send_pdu(sock, payload)
            tx_log.write_command(n, src, dest, echo, ptype, cmd, args,
                                 raw_cmd, payload, ax25, csp)
            history.append({
                "n": n,
                "ts": datetime.now().strftime("%H:%M:%S"),
                "src": src,
                "dest": dest,
                "cmd": cmd,
                "args": args,
                "echo": echo,
                "ptype": ptype,
                "payload_len": len(payload),
                "csp_enabled": csp.enabled,
            })
            hist_scroll = len(history) - 1  # keep history view on latest
        # Brief flash showing all as sent before clearing
        redraw(sending_idx=count)
        curses.napms(300)
        # Cap history (remove oldest from the front)
        if len(history) > MAX_HISTORY:
            del history[:len(history) - MAX_HISTORY]
        queue.clear()
        queue_scroll = 0
        hist_scroll = max(0, len(history) - 1)  # auto-scroll to bottom
        set_status(f"Sent {count} command{'s' if count != 1 else ''}")

    try:
        while True:
            # -- Layout --
            max_y, max_x = stdscr.getmaxyx()
            stdscr.erase()

            side_open = config_open or help_open
            layout = calculate_layout(max_y, max_x, side_panel=side_open)
            if layout is None:
                try:
                    stdscr.addstr(0, 0, f"Terminal too small (need 80x24, have {max_x}x{max_y})")
                except curses.error:
                    pass
                stdscr.refresh()
                try:
                    ch = stdscr.getch()
                except KeyboardInterrupt:
                    break
                if ch == 3:  # Ctrl+C
                    break
                continue

            # -- Clear status if expired --
            if status_msg and time.time() >= status_expire:
                status_msg = ""

            # -- Draw panels --
            draw_header(stdscr, layout["header"], csp, ax25, zmq_addr_disp,
                        freq=freq, log_path=tx_log.text_path)
            draw_queue(stdscr, layout["queue"], queue,
                       scroll_offset=queue_scroll, tx_delay_ms=tx_delay_ms)
            draw_history(stdscr, layout["history"], history,
                         scroll_offset=hist_scroll)
            draw_input(stdscr, layout["input"], input_buf, cursor_pos,
                       len(queue), status_msg)

            # Side panels
            if config_open and "side_panel" in layout:
                if not config_values:
                    config_values = config_get_values(
                        csp, ax25, freq, zmq_addr_disp, tx_delay_ms, tx_log.text_path)
                draw_config(stdscr, layout["side_panel"], config_values,
                            config_selected, config_editing,
                            config_buf, config_cursor, config_focused)
            elif help_open and "side_panel" in layout:
                draw_help(stdscr, layout["side_panel"],
                          version=VERSION, schema_count=len(cmd_defs),
                          schema_path=CMD_DEFS_PATH, log_path=tx_log.text_path)

            stdscr.refresh()

            # -- Input --
            try:
                ch = stdscr.getch()
            except KeyboardInterrupt:
                break

            if ch == curses.ERR:
                continue  # timeout — redraw for clock

            if ch == curses.KEY_RESIZE:
                continue

            if ch == 3:  # Ctrl+C
                if help_open:
                    help_open = False
                    continue
                if config_open:
                    config_open = False
                    config_editing = False
                    config_values = {}
                    continue
                break

            # -- Esc: close side panels --
            if ch == 27:
                if config_editing:
                    config_editing = False
                    continue
                if config_open:
                    config_open = False
                    config_focused = False
                    config_values = {}
                    continue
                if help_open:
                    help_open = False
                    continue

            # -- Config panel editing (only captures keys when actively editing a field) --
            if config_open and config_editing:
                if ch in (10, 13):  # Enter — save field
                    key = CONFIG_FIELDS[config_selected][1]
                    config_values[key] = config_buf
                    config_editing = False
                    try:
                        freq, zmq_addr_disp, tx_delay_ms = config_apply(
                            config_values, csp, ax25)
                        config_values = config_get_values(
                            csp, ax25, freq, zmq_addr_disp, tx_delay_ms, tx_log.text_path)
                    except (ValueError, KeyError):
                        set_status("Invalid value", 2)
                        config_values = config_get_values(
                            csp, ax25, freq, zmq_addr_disp, tx_delay_ms, tx_log.text_path)
                else:
                    config_buf, config_cursor, _ = edit_buffer(
                        ch, config_buf, config_cursor)
                continue

            # -- Config navigation (Tab toggles focus, Up/Down/Enter when focused) --
            if config_open and not config_editing:
                # Tab toggles focus between config panel and command input
                if ch == 9:  # Tab
                    config_focused = not config_focused
                    continue
                if config_focused:
                    if ch == curses.KEY_UP:
                        config_selected = (config_selected - 1) % len(CONFIG_FIELDS)
                        continue
                    if ch == curses.KEY_DOWN:
                        config_selected = (config_selected + 1) % len(CONFIG_FIELDS)
                        continue
                    if ch in (10, 13):  # Enter — edit field
                        _label, key, editable = CONFIG_FIELDS[config_selected]
                        if editable:
                            config_editing = True
                            config_buf = config_values.get(key, "")
                            config_cursor = len(config_buf)
                        continue

            # Ctrl+S — send queue
            if ch == 19:
                send_queue()
                continue

            # Ctrl+Z — remove last queued command
            if ch == 26:
                if queue:
                    removed = queue.pop()
                    set_status(f"Removed: {removed[4]} ({len(queue)} left)", 2)
                else:
                    set_status("Queue is empty", 2)
                continue

            # Ctrl+X — clear queue
            if ch == 24:
                if queue:
                    set_status(f"Cleared {len(queue)} command{'s' if len(queue) != 1 else ''}", 2)
                    queue.clear()
                    queue_scroll = 0
                continue

            # Page Up — scroll history up (show older)
            if ch == curses.KEY_PPAGE:
                # Minimum is data_rows-1 so a full page is visible
                layout_h = layout["history"][2]
                min_scroll = min(layout_h - 3, len(history) - 1)
                hist_scroll = max(min_scroll, hist_scroll - 5)
                continue

            # Page Down — scroll history down (show newer)
            if ch == curses.KEY_NPAGE:
                hist_scroll = min(len(history) - 1, hist_scroll + 5)
                continue

            # Up arrow — recall previous command
            if ch == curses.KEY_UP:
                if cmd_history:
                    if cmd_hist_idx == -1:
                        cmd_hist_save = input_buf
                        cmd_hist_idx = 0
                    elif cmd_hist_idx < len(cmd_history) - 1:
                        cmd_hist_idx += 1
                    input_buf = cmd_history[cmd_hist_idx]
                    cursor_pos = len(input_buf)
                continue

            # Down arrow — recall next command (or restore current input)
            if ch == curses.KEY_DOWN:
                if cmd_hist_idx >= 0:
                    cmd_hist_idx -= 1
                    if cmd_hist_idx == -1:
                        input_buf = cmd_hist_save
                    else:
                        input_buf = cmd_history[cmd_hist_idx]
                    cursor_pos = len(input_buf)
                continue

            # Enter
            if ch in (10, 13):
                line = input_buf.strip()
                input_buf = ""
                cursor_pos = 0
                cmd_hist_idx = -1

                if not line:
                    continue

                # Save to command history (newest first)
                cmd_history.insert(0, line)
                if len(cmd_history) > MAX_CMD_HISTORY:
                    del cmd_history[MAX_CMD_HISTORY:]

                low = line.lower()

                # Quit
                if low in ('q', 'quit', 'exit'):
                    break

                # Send
                if low == 'send':
                    send_queue()
                    continue

                # Clear queue
                if low == 'clear':
                    if queue:
                        set_status(f"Cleared {len(queue)} commands", 2)
                        queue.clear()
                        queue_scroll = 0
                    else:
                        set_status("Nothing to clear", 2)
                    continue

                # Remove last queued command
                if low in ('undo', 'pop'):
                    if queue:
                        removed = queue.pop()
                        set_status(f"Removed: {removed[4]} ({len(queue)} left)", 2)
                    else:
                        set_status("Queue is empty", 2)
                    continue

                # Clear sent history
                if low == 'hclear':
                    if history:
                        set_status(f"Cleared {len(history)} history entries", 2)
                        history.clear()
                        hist_scroll = 0
                    else:
                        set_status("History already empty", 2)
                    continue

                # Help
                if low == 'help':
                    help_open = True
                    continue

                # Config panel
                if low in ('config', 'cfg'):
                    config_open = True
                    config_focused = True
                    config_selected = 0
                    config_editing = False
                    config_values = config_get_values(
                        csp, ax25, freq, zmq_addr_disp, tx_delay_ms, tx_log.text_path)
                    continue

                # Nodes
                if low == 'nodes':
                    names = ", ".join(f"{nid}={protocol.NODE_NAMES[nid]}"
                                     for nid in sorted(protocol.NODE_NAMES))
                    set_status(f"Nodes: {names}", 5)
                    continue

                # CSP config (quick inline)
                if low == 'csp' or low.startswith('csp '):
                    msg = csp_handle_msg(csp, line[3:].strip() if len(line) > 3 else "")
                    set_status(msg, 4)
                    continue

                # AX.25 config (quick inline)
                if low == 'ax25' or low.startswith('ax25 '):
                    msg = ax25_handle_msg(ax25, line[4:].strip() if len(line) > 4 else "")
                    set_status(msg, 4)
                    continue

                # Parse as command — queue it
                parsed = parse_cmd_line(line)
                if parsed is None:
                    set_status("Bad command: need [src] <dest> <echo> <type> <cmd> [args]", 3)
                    continue

                src, dest, echo, ptype, cmd, args = parsed

                # Schema validation — reject invalid commands
                valid, issues = validate_args(cmd, args, cmd_defs)
                if not valid and issues:
                    set_status(f"Rejected: {issues[0]}", 3)
                    continue
                if cmd_defs and cmd not in cmd_defs:
                    set_status(f"Rejected: '{cmd}' not in command schema", 3)
                    continue

                raw_cmd = build_cmd_raw(dest, cmd, args, echo=echo, ptype=ptype,
                                        origin=src)
                if len(raw_cmd) + csp.overhead() + ax25.overhead() > MAX_RS_PAYLOAD:
                    set_status("Command too large for RS payload", 3)
                    continue

                queue.append((src, dest, echo, ptype, cmd, args, raw_cmd))
                src_tag = f"{node_label(src)}\u2192" if src != protocol.GS_NODE else ""
                set_status(f"Queued: {src_tag}{node_label(dest)} E:{echo} {protocol.PTYPE_NAMES.get(ptype, '?')} {cmd} {args} ({len(raw_cmd)}B)", 2)
                continue

            # Text editing (backspace, arrows, Ctrl+W, printable chars, etc.)
            input_buf, cursor_pos, _ = edit_buffer(ch, input_buf, cursor_pos)

    finally:
        try:
            tx_log.write_summary(n, session_start)
            tx_log.close()
        except Exception:
            pass
        try:
            sock.close()
            ctx.term()
        except Exception:
            pass

    return n, tx_log.text_path


def main():
    parser = argparse.ArgumentParser(description="MAVERIC TX Dashboard")
    parser.add_argument("--nosplash", action="store_true",
                        help="skip the startup splash screen")
    args = parser.parse_args()

    n, logpath = curses.wrapper(lambda stdscr: dashboard(
        stdscr, show_splash=not args.nosplash))
    # Print session summary after curses restores the terminal
    print()
    print(f"  Session ended")
    print(f"  Transmitted:  {n}")
    print(f"  Log:          {logpath}")
    print()


if __name__ == "__main__":
    main()
