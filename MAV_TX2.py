"""
MAV_TX2 -- MAVERIC Command Terminal (Curses Dashboard)

Persistent curses-based dashboard for the MAVERIC CubeSat uplink.
Same protocol stack as MAV_TX.py (CSP v1 + CRC-32C + AX.25 + ZMQ),
but with a live dashboard showing:
  - Header: AX.25 callsigns, CSP config, clock, ZMQ status, frequency
  - TX Queue: pending commands (scrollable)
  - Sent History: transmitted commands with full metadata (scrollable)
  - Input: command entry with cursor editing

All commands go to the queue first. Ctrl+S sends, Ctrl+X clears.

Fallback: run MAV_TX.py for the original interactive CLI.

Author:  Irfan Annuar - USC ISI SERC
"""

import curses
import os
import json
import time
from datetime import datetime

from mav_gss_lib.protocol import (
    NODE_NAMES, NODE_IDS, GS_NODE,
    node_label, ptype_label, resolve_node,
    build_cmd_raw, AX25Config, CSPConfig,
    load_command_defs, validate_args,
)
from mav_gss_lib.transport import init_zmq_pub, send_pdu
from mav_gss_lib.curses_ui import (
    init_colors, calculate_layout,
    draw_header, draw_queue, draw_history, draw_input,
    draw_config, config_get_values, config_apply, CONFIG_FIELDS,
    draw_help, draw_splash,
    CP_ERROR, CP_WARNING, CP_SUCCESS, CP_DIM,
)


# -- Config -------------------------------------------------------------------

VERSION       = "1.0"
ZMQ_ADDR      = "tcp://127.0.0.1:52002"
LOG_DIR       = "logs"
MAX_RS_PAYLOAD = 223
CMD_DEFS_PATH  = "maveric_commands.yml"
FREQUENCY      = "437.25 MHz"
MAX_HISTORY    = 500


# -- Logging ------------------------------------------------------------------

def open_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(LOG_DIR, f"uplink_{ts}.jsonl")
    return open(path, "a"), path


def log_tx(f, n, dest, cmd, args, payload, csp_enabled):
    rec = {
        "n": n,
        "ts": datetime.now().astimezone().isoformat(),
        "dest": dest,
        "dest_lbl": NODE_NAMES.get(dest, "?"),
        "cmd": cmd,
        "args": args,
        "hex": payload.hex(),
        "len": len(payload),
        "csp": csp_enabled,
    }
    f.write(json.dumps(rec) + "\n")
    f.flush()


# -- Command Parsing ----------------------------------------------------------

def parse_cmd_line(line):
    parts = line.split(None, 2)
    if len(parts) < 2:
        return None
    dest = resolve_node(parts[0])
    if dest is None:
        return None
    return (dest, parts[1], parts[2] if len(parts) > 2 else "")


# -- Config Handlers (return status strings instead of printing) --------------

def ax25_handle_msg(ax25, args):
    """Handle AX.25 config command, return status message."""
    if not args:
        return (f"AX.25  Dest:{ax25.dest_call}-{ax25.dest_ssid}  "
                f"Src:{ax25.src_call}-{ax25.src_ssid}")
    parts = args.split()
    cmd = parts[0].lower()
    if cmd == 'dest' and len(parts) > 1:
        ax25.dest_call = parts[1].upper()[:6]
        if len(parts) > 2 and parts[2].isdigit():
            ax25.dest_ssid = int(parts[2]) & 0x0F
        return f"AX.25 dest = {ax25.dest_call}-{ax25.dest_ssid}"
    elif cmd == 'src' and len(parts) > 1:
        ax25.src_call = parts[1].upper()[:6]
        if len(parts) > 2 and parts[2].isdigit():
            ax25.src_ssid = int(parts[2]) & 0x0F
        return f"AX.25 src = {ax25.src_call}-{ax25.src_ssid}"
    return "ax25 [dest <call> [ssid]|src <call> [ssid]]"


def csp_handle_msg(csp, args):
    """Handle CSP config command, return status message."""
    if not args:
        hdr = csp.build_header()
        return (f"CSP  Prio:{csp.prio} Src:{csp.src} "
                f"Dest:{csp.dest} DPort:{csp.dport} SPort:{csp.sport} "
                f"Flags:0x{csp.flags:02X}  ({hdr.hex(' ')})")
    parts = args.split()
    cmd = parts[0].lower()
    if cmd in ('prio', 'src', 'dest', 'dport', 'sport', 'flags') and len(parts) > 1:
        try:
            val = int(parts[1], 0)
        except ValueError:
            return f"Invalid value: {parts[1]}"
        setattr(csp, cmd, val)
        return f"CSP {cmd} = {val}"
    return "csp [prio|src|dest|dport|sport|flags] [value]"


# -- Dashboard ----------------------------------------------------------------

def dashboard(stdscr):
    curses.curs_set(0)
    curses.raw()          # disable Ctrl+S/Ctrl+Q flow control so Ctrl+S works
    curses.set_escdelay(25)  # fast Esc response (25ms instead of default 1000ms)
    init_colors()
    stdscr.keypad(True)   # enable KEY_LEFT, KEY_UP, etc.
    draw_splash(stdscr)
    curses.halfdelay(5)   # 500ms timeout for getch — drives clock updates

    csp  = CSPConfig()
    ax25 = AX25Config()
    cmd_defs = load_command_defs(CMD_DEFS_PATH)

    ctx, sock = init_zmq_pub(ZMQ_ADDR)
    logf, logpath = open_log()

    queue   = []       # list of (dest, cmd, args, raw_cmd)
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

    def send_queue():
        nonlocal n, queue_scroll
        if not queue:
            set_status("Nothing queued", 2)
            return
        count = len(queue)
        for dest, cmd, args, raw_cmd in queue:
            payload = ax25.wrap(csp.wrap(raw_cmd))
            n += 1
            send_pdu(sock, payload)
            log_tx(logf, n, dest, cmd, args, payload, csp.enabled)
            echo = raw_cmd[2]
            ptype = raw_cmd[3]
            history.insert(0, {
                "n": n,
                "ts": datetime.now().strftime("%H:%M:%S"),
                "dest": dest,
                "cmd": cmd,
                "args": args,
                "echo": echo,
                "ptype": ptype,
                "payload_len": len(payload),
                "csp_enabled": csp.enabled,
            })
        # Cap history
        if len(history) > MAX_HISTORY:
            del history[MAX_HISTORY:]
        queue.clear()
        queue_scroll = 0
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
                        freq=freq, log_path=logpath)
            draw_queue(stdscr, layout["queue"], queue,
                       scroll_offset=queue_scroll)
            draw_history(stdscr, layout["history"], history,
                         scroll_offset=hist_scroll)
            draw_input(stdscr, layout["input"], input_buf, cursor_pos,
                       len(queue), status_msg)

            # Side panels
            if config_open and "side_panel" in layout:
                if not config_values:
                    config_values = config_get_values(
                        csp, ax25, freq, zmq_addr_disp, logpath)
                draw_config(stdscr, layout["side_panel"], config_values,
                            config_selected, config_editing,
                            config_buf, config_cursor, config_focused)
            elif help_open and "side_panel" in layout:
                draw_help(stdscr, layout["side_panel"])

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
                        freq, zmq_addr_disp = config_apply(
                            config_values, csp, ax25)
                        config_values = config_get_values(
                            csp, ax25, freq, zmq_addr_disp, logpath)
                    except (ValueError, KeyError):
                        set_status("Invalid value", 2)
                        config_values = config_get_values(
                            csp, ax25, freq, zmq_addr_disp, logpath)
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    if config_cursor > 0:
                        config_buf = config_buf[:config_cursor - 1] + config_buf[config_cursor:]
                        config_cursor -= 1
                elif ch == curses.KEY_LEFT:
                    config_cursor = max(0, config_cursor - 1)
                elif ch == curses.KEY_RIGHT:
                    config_cursor = min(len(config_buf), config_cursor + 1)
                elif ch in (curses.KEY_HOME, 1):
                    config_cursor = 0
                elif ch in (curses.KEY_END, 5):
                    config_cursor = len(config_buf)
                elif ch == 21:  # Ctrl+U
                    config_buf = ""
                    config_cursor = 0
                elif 32 <= ch <= 126:
                    config_buf = config_buf[:config_cursor] + chr(ch) + config_buf[config_cursor:]
                    config_cursor += 1
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

            # Ctrl+X — clear queue
            if ch == 24:
                if queue:
                    set_status(f"Cleared {len(queue)} command{'s' if len(queue) != 1 else ''}", 2)
                    queue.clear()
                    queue_scroll = 0
                continue

            # Page Up — scroll history up
            if ch == curses.KEY_PPAGE:
                if hist_scroll > 0:
                    hist_scroll = max(0, hist_scroll - 5)
                continue

            # Page Down — scroll history down
            if ch == curses.KEY_NPAGE:
                hist_scroll = min(len(history) - 1, hist_scroll + 5)
                if hist_scroll < 0:
                    hist_scroll = 0
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

            # Backspace
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                if cursor_pos > 0:
                    input_buf = input_buf[:cursor_pos - 1] + input_buf[cursor_pos:]
                    cursor_pos -= 1
                continue

            # Delete key
            if ch == curses.KEY_DC:
                if cursor_pos < len(input_buf):
                    input_buf = input_buf[:cursor_pos] + input_buf[cursor_pos + 1:]
                continue

            # Left arrow
            if ch == curses.KEY_LEFT:
                cursor_pos = max(0, cursor_pos - 1)
                continue

            # Right arrow
            if ch == curses.KEY_RIGHT:
                cursor_pos = min(len(input_buf), cursor_pos + 1)
                continue

            # Home / Ctrl+A
            if ch in (curses.KEY_HOME, 1):
                cursor_pos = 0
                continue

            # End / Ctrl+E
            if ch in (curses.KEY_END, 5):
                cursor_pos = len(input_buf)
                continue

            # Ctrl+U — clear line
            if ch == 21:
                input_buf = ""
                cursor_pos = 0
                continue

            # Ctrl+K — kill to end of line
            if ch == 11:
                input_buf = input_buf[:cursor_pos]
                continue

            # Ctrl+W — delete word backwards
            if ch == 23:
                if cursor_pos > 0:
                    # Find start of previous word
                    p = cursor_pos - 1
                    while p > 0 and input_buf[p - 1] == ' ':
                        p -= 1
                    while p > 0 and input_buf[p - 1] != ' ':
                        p -= 1
                    input_buf = input_buf[:p] + input_buf[cursor_pos:]
                    cursor_pos = p
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

                low = line.lower()

                # Quit
                if low in ('q', 'quit', 'exit'):
                    break

                # Send
                if low == 'send':
                    send_queue()
                    continue

                # Clear
                if low == 'clear':
                    if queue:
                        set_status(f"Cleared {len(queue)} commands", 2)
                        queue.clear()
                        queue_scroll = 0
                    else:
                        set_status("Nothing to clear", 2)
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
                        csp, ax25, freq, zmq_addr_disp, logpath)
                    continue

                # Nodes
                if low == 'nodes':
                    names = ", ".join(f"{nid}={NODE_NAMES[nid]}"
                                     for nid in sorted(NODE_NAMES))
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

                # Raw hex
                if low.startswith('raw '):
                    try:
                        raw_bytes = bytes.fromhex(line[4:].replace(' ', ''))
                    except ValueError:
                        set_status("Bad hex", 2)
                        continue
                    n += 1
                    send_pdu(sock, raw_bytes)
                    set_status(f"Sent raw #{n}: {len(raw_bytes)}B", 3)
                    continue

                # Parse as command — queue it
                parsed = parse_cmd_line(line)
                if parsed is None:
                    set_status("Bad command: need <dest> <cmd> [args]", 3)
                    continue

                dest, cmd, args = parsed

                # Schema validation — reject invalid commands
                valid, issues = validate_args(cmd, args, cmd_defs)
                if not valid and issues:
                    set_status(f"Rejected: {issues[0]}", 3)
                    continue
                if cmd_defs and cmd not in cmd_defs:
                    set_status(f"Rejected: '{cmd}' not in command schema", 3)
                    continue

                raw_cmd = build_cmd_raw(dest, cmd, args)
                if len(raw_cmd) + csp.overhead() + ax25.overhead() > MAX_RS_PAYLOAD:
                    set_status("Command too large for RS payload", 3)
                    continue

                queue.append((dest, cmd, args, raw_cmd))
                set_status(f"Queued: {node_label(dest)} {cmd} {args} ({len(raw_cmd)}B)", 2)
                continue

            # Printable character
            if 32 <= ch <= 126:
                input_buf = input_buf[:cursor_pos] + chr(ch) + input_buf[cursor_pos:]
                cursor_pos += 1

    finally:
        logf.close()
        sock.close()
        ctx.term()

    return n, logpath


def main():
    n, logpath = curses.wrapper(dashboard)
    # Print session summary after curses restores the terminal
    print()
    print(f"  Session ended")
    print(f"  Transmitted:  {n}")
    print(f"  Log:          {logpath}")
    print()


if __name__ == "__main__":
    main()
