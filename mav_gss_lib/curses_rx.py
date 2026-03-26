"""
mav_gss_lib.curses_rx -- RX Monitor Panels

Panel rendering and layout for the RX monitor dashboard. Provides layout
calculation and draw functions for:
  - Header (ZMQ, toggles, clock)
  - Packet List (scrollable received packets)
  - Packet Detail (expanded view of selected packet)
  - Status Bar (silence timer, stats, key hints)
  - Help (side panel, reference)

Author:  Irfan Annuar - USC ISI SERC
"""

import curses
from datetime import datetime, timezone

import mav_gss_lib.protocol as protocol
from mav_gss_lib.protocol import node_label, ptype_label, format_arg_value
from mav_gss_lib.curses_common import (
    safe_addstr, draw_hline, draw_vline, render_input_line, draw_help_panel,
    CP_LABEL, CP_VALUE, CP_SUCCESS, CP_WARNING, CP_ERROR, CP_DIM,
    S_DIM, S_VALUE, S_SUCCESS,
    MIN_COLS,
)


# -- Layout -------------------------------------------------------------------

RX_HEADER_ROWS = 4    # title+clock + separator + ZMQ/toggles + queue depth
RX_INPUT_ROWS  = 4    # status + separator + prompt + hints
RX_MIN_LIST    = 5    # title + at least 4 data rows
RX_DETAIL_H    = 15   # detail panel height when open
RX_MIN_ROWS    = RX_HEADER_ROWS + RX_INPUT_ROWS + RX_MIN_LIST


def calculate_rx_layout(max_y, max_x, detail_open=False, side_panel=False):
    """Return panel regions as {name: (y, x, h, w)} dicts.

    When detail_open=True, the bottom portion becomes a detail panel.
    When side_panel=True, the packet list splits horizontally (left=list, right=side_panel).
    Returns None if terminal is too small.
    """
    if max_y < RX_MIN_ROWS or max_x < MIN_COLS:
        return None

    w = max_x
    remaining = max_y - RX_HEADER_ROWS - RX_INPUT_ROWS

    layout = {
        "header": (0, 0, RX_HEADER_ROWS, w),
        "input":  (max_y - RX_INPUT_ROWS, 0, RX_INPUT_ROWS, w),
    }

    if detail_open:
        detail_h = min(RX_DETAIL_H, remaining - RX_MIN_LIST)
        if detail_h < 4:
            detail_h = 0
        list_h = remaining - detail_h
        layout["packet_list"] = (RX_HEADER_ROWS, 0, list_h, w)
        if detail_h > 0:
            layout["detail"] = (RX_HEADER_ROWS + list_h, 0, detail_h, w)
    else:
        list_h = remaining
        layout["packet_list"] = (RX_HEADER_ROWS, 0, list_h, w)

    if side_panel:
        ly, lx, lh, lw = layout["packet_list"]
        side_w = lw * 4 // 10
        main_w = lw - side_w
        layout["packet_list"] = (ly, lx, lh, main_w)
        layout["side_panel"] = (ly, main_w, lh, side_w)

    return layout


# -- Header Panel -------------------------------------------------------------

def draw_rx_header(stdscr, region, zmq_addr, freq="437.25 MHz",
                   show_hex=True, logging_enabled=True, queue_depth=0,
                   zmq_status="SUB"):
    """Draw the 4-row RX header with live clock, ZMQ, freq, toggles, queue."""
    y, x, h, w = region
    utc_now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    local_now = datetime.now().strftime("%H:%M:%S")
    time_str = f"UTC {utc_now}  Local {local_now}"

    # Row 0: title + clock
    title = "MAVERIC RX MONITOR"
    safe_addstr(stdscr, y, x + 1, title,
          S_SUCCESS)
    safe_addstr(stdscr, y, x + w - len(time_str) - 1, time_str,
          S_VALUE)

    # Row 1: separator
    draw_hline(stdscr, y + 1, x, w, S_DIM)

    # Row 2: ZMQ address + freq + toggle indicators
    safe_addstr(stdscr, y + 2, x + 1, "ZMQ",
          curses.color_pair(CP_LABEL))
    zmq_tag = f"[{zmq_status}]"
    if zmq_status == "LIVE":
        tag_attr = S_SUCCESS
    elif zmq_status == "DOWN":
        tag_attr = curses.color_pair(CP_ERROR) | curses.A_BOLD
    else:
        tag_attr = S_VALUE
    safe_addstr(stdscr, y + 2, x + 7,
          f"{zmq_addr} ",
          S_VALUE)
    safe_addstr(stdscr, y + 2, x + 7 + len(zmq_addr) + 1,
          zmq_tag, tag_attr)

    # Frequency (middle area)
    freq_str = f"Freq: {freq}"
    freq_x = x + 7 + len(zmq_addr) + 1 + len(zmq_tag) + 2
    safe_addstr(stdscr, y + 2, freq_x, freq_str,
          curses.color_pair(CP_WARNING))

    # Right side: HEX and LOG toggles
    hex_state = "ON" if show_hex else "OFF"
    log_state = "ON" if logging_enabled else "OFF"
    on_attr = curses.color_pair(CP_SUCCESS)
    off_attr = S_DIM
    hex_attr = on_attr if show_hex else off_attr
    log_attr = on_attr if logging_enabled else off_attr

    toggles = f"HEX:{hex_state}  LOG:{log_state}"
    toggle_x = x + w - len(toggles) - 1
    safe_addstr(stdscr, y + 2, toggle_x, "HEX:", curses.color_pair(CP_LABEL))
    safe_addstr(stdscr, y + 2, toggle_x + 4, hex_state, hex_attr)
    safe_addstr(stdscr, y + 2, toggle_x + 4 + len(hex_state) + 2, "LOG:",
          curses.color_pair(CP_LABEL))
    safe_addstr(stdscr, y + 2, toggle_x + 4 + len(hex_state) + 6, log_state,
          log_attr)

    # Row 3: RX queue depth
    safe_addstr(stdscr, y + 3, x + 1, "Q",
          curses.color_pair(CP_LABEL))
    safe_addstr(stdscr, y + 3, x + 7, str(queue_depth),
          S_VALUE)


# -- Packet List Panel --------------------------------------------------------

def draw_packet_list(stdscr, region, packets, selected_idx, scroll_offset,
                     auto_follow=True):
    """Draw the scrollable packet list.

    Each packet is one line: #N  HH:MM:SS  FRAME  src→dest  CMD_ID  sizeB  CRC  [DUP]
    The selected row is highlighted with A_REVERSE.
    Bottom-anchored when auto_follow is True.
    """
    y, x, h, w = region
    count = len(packets)

    # Separator above
    draw_hline(stdscr, y, x, w, S_DIM)

    # Title row
    title = f" PACKETS ({count})"
    safe_addstr(stdscr, y + 1, x, title,
          S_SUCCESS)

    if auto_follow:
        safe_addstr(stdscr, y + 1, x + len(title) + 2, "[LIVE]",
              curses.color_pair(CP_WARNING) | curses.A_BOLD)

    data_start = y + 2
    data_rows = h - 2

    if count == 0:
        safe_addstr(stdscr, data_start, x + 2,
              "(waiting for packets...)",
              S_DIM)
        return

    # Compute visible window
    if auto_follow:
        # Show newest at bottom
        end = count
        start = max(0, end - data_rows)
    else:
        start = scroll_offset
        end = min(count, start + data_rows)

    # Scroll indicator
    if count > data_rows:
        ind = f"[{start + 1}-{end}/{count}]"
        safe_addstr(stdscr, y + 1, x + w - len(ind) - 2, ind,
              S_DIM)

    visible = packets[start:end]
    for i, pkt in enumerate(visible):
        row_y = data_start + i
        if row_y >= y + h:
            break

        abs_idx = start + i
        is_selected = (abs_idx == selected_idx)

        # Build the line
        pkt_num = pkt.get("pkt_num", 0)
        ts_short = pkt.get("gs_ts_short", "??:??:??")
        frame_type = pkt.get("frame_type", "???")
        is_dup = pkt.get("is_dup", False)
        is_uplink_echo = pkt.get("is_uplink_echo", False)
        is_unknown = pkt.get("is_unknown", False)
        unknown_num = pkt.get("unknown_num")

        # Command fields
        cmd = pkt.get("cmd")
        if cmd:
            cmd_id = cmd["cmd_id"]
            cmd_src = node_label(cmd["src"])
            cmd_dest = node_label(cmd["dest"])
            cmd_echo = node_label(cmd["echo"])
            cmd_ptype = protocol.PTYPE_NAMES.get(cmd["pkt_type"], str(cmd["pkt_type"]))
            # Build args string
            if cmd.get("schema_match"):
                arg_parts = [format_arg_value(ta) for ta in cmd.get("typed_args", [])]
                arg_parts += [str(extra) for extra in cmd.get("extra_args", [])]
                args_str = " ".join(arg_parts)
            else:
                args_str = " ".join(str(a) for a in cmd.get("args", []))
        else:
            cmd_id = "--"
            cmd_src = cmd_dest = cmd_echo = cmd_ptype = "--"
            args_str = ""

        # Payload size
        inner = pkt.get("inner_payload", b"")
        size_str = f"{len(inner)}B"

        # CRC status — prefer CSP CRC-32C, fall back to cmd-level CRC-16
        crc_valid = pkt.get("crc_status", {}).get("csp_crc32_valid")
        if crc_valid is None and cmd:
            crc_valid = cmd.get("crc_valid")
        if crc_valid is True:
            crc_str = "CRC:OK"
        elif crc_valid is False:
            crc_str = "CRC:FAIL"
        else:
            crc_str = ""

        # Base attribute for selected row
        if is_selected:
            base_attr = curses.A_REVERSE
        else:
            base_attr = 0

        if is_selected:
            # Fill entire row with reverse for clean highlight
            safe_addstr(stdscr, row_y, x, " " * w, base_attr)

        col = x + 1

        # Packet number — unknown packets use U-N, valid packets use #N
        if is_unknown and unknown_num is not None:
            num_str = f"U-{unknown_num:<4}"
        else:
            num_str = f"#{pkt_num:<5}"
        safe_addstr(stdscr, row_y, col, num_str,
              base_attr | curses.color_pair(CP_ERROR if is_unknown else CP_DIM))
        col += len(num_str)

        # Timestamp
        safe_addstr(stdscr, row_y, col, ts_short,
              base_attr | curses.color_pair(CP_DIM))
        col += len(ts_short) + 1

        if is_unknown:
            # Unknown packet — just show UNKNOWN label and size
            safe_addstr(stdscr, row_y, col, "UNKNOWN",
                  base_attr | curses.color_pair(CP_ERROR) | curses.A_BOLD)
            col += 8
        else:
            # Frame type
            if frame_type == "AX.25":
                ft_attr = curses.color_pair(CP_WARNING)
            elif frame_type == "AX100":
                ft_attr = curses.color_pair(CP_SUCCESS)
            else:
                ft_attr = curses.color_pair(CP_ERROR)
            safe_addstr(stdscr, row_y, col, f"{frame_type:<6}",
                  base_attr | ft_attr)
            col += 7

            # Command src→dest
            route_str = f"{cmd_src} \u2192 {cmd_dest}"
            safe_addstr(stdscr, row_y, col, route_str,
                  base_attr | curses.color_pair(CP_LABEL))
            col += len(route_str) + 1

            # Echo
            echo_str = f"E:{cmd_echo}"
            safe_addstr(stdscr, row_y, col, echo_str,
                  base_attr | curses.color_pair(CP_DIM))
            col += len(echo_str) + 1

            # Packet type
            safe_addstr(stdscr, row_y, col, cmd_ptype,
                  base_attr | curses.color_pair(CP_LABEL))
            col += len(cmd_ptype) + 1

            # Command ID
            cmd_display = cmd_id[:14] if len(cmd_id) > 14 else cmd_id
            safe_addstr(stdscr, row_y, col, cmd_display,
                  base_attr | S_VALUE)
            col += len(cmd_display) + 1

        # Right-aligned block: args + size + CRC + DUP
        # Build right side first to know where it starts
        right_parts = []
        if crc_str:
            right_parts.append(crc_str)
        right_parts.append(size_str)
        if is_uplink_echo:
            right_parts.append("UL")
        if is_dup:
            right_parts.append("DUP")
        right_str = "  ".join(right_parts)
        right_x = x + w - len(right_str) - 2

        # Args — fill space between cmd_id and right block
        if args_str and col < right_x - 1:
            max_args_w = right_x - col - 1
            safe_addstr(stdscr, row_y, col, args_str[:max_args_w],
                  base_attr | curses.color_pair(CP_DIM))

        # Draw right-aligned block (left to right: CRC, size, UL, DUP)
        rx = right_x
        if crc_str:
            if "OK" in crc_str:
                crc_attr = curses.color_pair(CP_SUCCESS)
            else:
                crc_attr = curses.color_pair(CP_ERROR) | curses.A_BOLD
            safe_addstr(stdscr, row_y, rx, crc_str, base_attr | crc_attr)
            rx += len(crc_str) + 2
        safe_addstr(stdscr, row_y, rx, size_str,
              base_attr | curses.color_pair(CP_DIM))
        rx += len(size_str) + 2
        if is_uplink_echo:
            safe_addstr(stdscr, row_y, rx, "UL",
                  base_attr | curses.color_pair(CP_WARNING) | curses.A_BOLD)
            rx += 4
        if is_dup:
            safe_addstr(stdscr, row_y, rx, "DUP",
                  base_attr | curses.color_pair(CP_ERROR) | curses.A_BOLD)


# -- Packet Detail Panel ------------------------------------------------------

def draw_packet_detail(stdscr, region, packet, show_hex=True):
    """Draw the expanded detail view of a selected packet."""
    y, x, h, w = region
    if not packet:
        return

    lbl = curses.color_pair(CP_LABEL)

    # Top separator + title
    draw_hline(stdscr, y, x, w, S_DIM)
    is_unknown = packet.get("is_unknown", False)
    unknown_num = packet.get("unknown_num")
    pkt_num = packet.get("pkt_num", 0)

    if is_unknown and unknown_num is not None:
        title = f" UNKNOWN PACKET U-{unknown_num}"
    else:
        title = f" PACKET #{pkt_num} DETAIL"
    safe_addstr(stdscr, y + 1, x, title,
          curses.color_pair(CP_ERROR if is_unknown else CP_WARNING) | curses.A_BOLD)

    row = y + 2
    max_row = y + h - 1  # leave last row empty

    # Unknown packets — only show HEX and ASCII, skip all protocol fields
    if is_unknown:
        # HEX dump
        if show_hex and row < max_row:
            raw = packet.get("raw", b"")
            if raw:
                hex_str = raw.hex(" ")
                safe_addstr(stdscr, row, x + 2, "HEX", lbl)
                hex_w = w - 16
                offset = 0
                while offset < len(hex_str) and row < max_row:
                    chunk = hex_str[offset:offset + hex_w]
                    safe_addstr(stdscr, row, x + 14, chunk, S_DIM)
                    offset += hex_w
                    row += 1

            text = packet.get("text", "")
            if text and row < max_row:
                safe_addstr(stdscr, row, x + 2, "ASCII", lbl)
                safe_addstr(stdscr, row, x + 14, text[:w - 16], S_DIM)
                row += 1

            inner = packet.get("inner_payload", b"")
            if inner and row < max_row:
                safe_addstr(stdscr, row, x + 2, "SIZE", lbl)
                safe_addstr(stdscr, row, x + 14, f"{len(inner)}B (raw {len(raw)}B)", S_DIM)
                row += 1
        return

    # Warnings
    for warning in packet.get("warnings", []):
        if row >= max_row:
            break
        safe_addstr(stdscr, row, x + 2,
              f"\u26a0 {warning}",
              curses.color_pair(CP_ERROR))
        row += 1

    # Uplink echo flag
    if packet.get("is_uplink_echo") and row < max_row:
        safe_addstr(stdscr, row, x + 2, "UL ECHO",
              curses.color_pair(CP_WARNING) | curses.A_BOLD)
        safe_addstr(stdscr, row, x + 14, "Uplink echo \u2014 dest/echo not addressed to GS",
              curses.color_pair(CP_WARNING))
        row += 1

    # AX.25 header
    stripped_hdr = packet.get("stripped_hdr")
    if stripped_hdr and row < max_row:
        safe_addstr(stdscr, row, x + 2, "AX.25 HDR", lbl)
        safe_addstr(stdscr, row, x + 14, stripped_hdr[:w - 16], S_DIM)
        row += 1

    # CSP
    csp = packet.get("csp")
    if csp and row < max_row:
        csp_plausible = packet.get("csp_plausible", False)
        tag = "CSP V1" if csp_plausible else "CSP V1 [?]"
        safe_addstr(stdscr, row, x + 2, tag, lbl)
        csp_str = (f"Prio:{csp['prio']}  Src:{csp['src']}  "
                   f"Dest:{csp['dest']}  DPort:{csp['dport']}  "
                   f"SPort:{csp['sport']}  Flags:0x{csp['flags']:02x}")
        safe_addstr(stdscr, row, x + 14, csp_str, S_VALUE)
        row += 1

    # SAT TIME
    ts_result = packet.get("ts_result")
    if row < max_row:
        safe_addstr(stdscr, row, x + 2, "SAT TIME", lbl)
        if ts_result:
            dt_utc, dt_local, raw_ms = ts_result
            ts_str = (f"{dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}  \u2502  "
                      f"{dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            safe_addstr(stdscr, row, x + 14, ts_str, S_VALUE)
        else:
            safe_addstr(stdscr, row, x + 14, "--", S_DIM)
        row += 1

    # Command
    cmd = packet.get("cmd")
    if cmd and row < max_row:
        safe_addstr(stdscr, row, x + 2, "CMD", lbl)
        cmd_info = (f"Src:{node_label(cmd['src'])}  "
                    f"Dest:{node_label(cmd['dest'])}  "
                    f"Echo:{node_label(cmd['echo'])}  "
                    f"Type:{ptype_label(cmd['pkt_type'])}")
        safe_addstr(stdscr, row, x + 14, cmd_info, S_VALUE)
        row += 1

        if row < max_row:
            safe_addstr(stdscr, row, x + 2, "CMD ID", lbl)
            safe_addstr(stdscr, row, x + 14, cmd["cmd_id"], S_VALUE)
            row += 1

        # Schema-matched args
        if cmd.get("schema_match") and row < max_row:
            for ta in cmd.get("typed_args", []):
                if row >= max_row:
                    break
                label = ta["name"].upper()
                value = format_arg_value(ta)
                safe_addstr(stdscr, row, x + 2, label[:12], lbl)
                safe_addstr(stdscr, row, x + 14, value[:w - 16], S_VALUE)
                row += 1
            for i, extra in enumerate(cmd.get("extra_args", [])):
                if row >= max_row:
                    break
                safe_addstr(stdscr, row, x + 2, f"ARG +{i}", lbl)
                safe_addstr(stdscr, row, x + 14, str(extra)[:w - 16], S_VALUE)
                row += 1
        elif not cmd.get("schema_match"):
            if cmd.get("schema_warning") and row < max_row:
                safe_addstr(stdscr, row, x + 2,
                      f"\u26a0 {cmd['schema_warning']}",
                      curses.color_pair(CP_WARNING))
                row += 1
            for i, arg in enumerate(cmd.get("args", [])):
                if row >= max_row:
                    break
                safe_addstr(stdscr, row, x + 2, f"ARG {i}", lbl)
                safe_addstr(stdscr, row, x + 14, str(arg)[:w - 16], S_VALUE)
                row += 1

    # CRC status (before hex — matches log order)
    if cmd and row < max_row:
        if cmd.get("crc") is not None:
            valid = cmd.get("crc_valid")
            tag = "OK" if valid else "FAIL"
            crc_attr = curses.color_pair(CP_SUCCESS) if valid else curses.color_pair(CP_ERROR)
            safe_addstr(stdscr, row, x + 2, "CRC-16", lbl)
            safe_addstr(stdscr, row, x + 14, f"0x{cmd['crc']:04x}  [{tag}]", crc_attr)
            row += 1

    crc_status = packet.get("crc_status", {})
    if crc_status.get("csp_crc32_valid") is not None and row < max_row:
        valid = crc_status["csp_crc32_valid"]
        tag = "OK" if valid else "FAIL"
        crc_attr = curses.color_pair(CP_SUCCESS) if valid else curses.color_pair(CP_ERROR)
        safe_addstr(stdscr, row, x + 2, "CRC-32C", lbl)
        safe_addstr(stdscr, row, x + 14,
              f"0x{crc_status['csp_crc32_rx']:08x}  [{tag}]", crc_attr)
        row += 1

    # HEX dump (toggleable)
    if show_hex and row < max_row:
        raw = packet.get("raw", b"")
        if raw:
            hex_str = raw.hex(" ")
            safe_addstr(stdscr, row, x + 2, "HEX", lbl)
            # Wrap hex across available lines
            hex_w = w - 16
            offset = 0
            while offset < len(hex_str) and row < max_row:
                chunk = hex_str[offset:offset + hex_w]
                safe_addstr(stdscr, row, x + 14, chunk, S_DIM)
                offset += hex_w
                row += 1

        # ASCII
        text = packet.get("text", "")
        if text and row < max_row:
            safe_addstr(stdscr, row, x + 2, "ASCII", lbl)
            safe_addstr(stdscr, row, x + 14, text[:w - 16], S_DIM)
            row += 1


# -- Input Panel --------------------------------------------------------------

def draw_rx_input(stdscr, region, buf, cursor_pos, silence_secs, pkt_count,
                  rate_per_min, receiving=False, spinner_char="\u2588",
                  status_msg="", error_msg=""):
    """Draw the 3-row input area: status line + separator + prompt/hints."""
    y, x, h, w = region

    # Row 0: status line (spinner + receiving/silence + stats)
    col = x + 1

    status_y = y
    if error_msg:
        safe_addstr(stdscr, status_y, col, error_msg[:w - 2],
              curses.color_pair(CP_ERROR))
    elif status_msg:
        safe_addstr(stdscr, status_y, col, status_msg[:w - 2],
              curses.color_pair(CP_WARNING))
    else:
        # Spinner
        safe_addstr(stdscr, status_y, col, spinner_char,
              curses.color_pair(CP_LABEL) | curses.A_BOLD)
        col += 2

        # Receiving / Silence
        if receiving:
            safe_addstr(stdscr, status_y, col, "Receiving",
                  S_SUCCESS)
            col += 11
        else:
            if silence_secs <= 10:
                silence_attr = curses.color_pair(CP_SUCCESS)
            elif silence_secs <= 30:
                silence_attr = curses.color_pair(CP_WARNING)
            else:
                silence_attr = curses.color_pair(CP_ERROR)
            silence_str = f"Silence: {silence_secs:05.1f}s"
            safe_addstr(stdscr, status_y, col, silence_str, silence_attr)
            col += len(silence_str) + 2

        # Packet count + rate
        stats = f"{pkt_count} pkts"
        if rate_per_min > 0:
            stats += f"  {rate_per_min:.0f} pkt/min"
        safe_addstr(stdscr, status_y, col, stats,
              S_DIM)

    # Row 1: separator
    draw_hline(stdscr, y + 1, x, w, S_DIM)

    # Row 2: prompt + input buffer + cursor
    render_input_line(stdscr, y + 2, x, w, buf, cursor_pos)

    # Row 3: hints
    hints = "Enter: detail | cfg | help | Ctrl+C: quit"
    safe_addstr(stdscr, y + 3, x + 1, hints,
          S_DIM)


# -- Help Side Panel ----------------------------------------------------------

RX_HELP_LINES = [
    ("KEYS", None),
    ("Up / Down", "Select packet"),
    ("PgUp / PgDn", "Scroll page"),
    ("Enter", "Toggle detail"),
    ("Ctrl+A / Ctrl+E", "Cursor start / end"),
    ("Ctrl+W / Ctrl+U", "Del word / clear input"),
    ("Ctrl+C", "Quit"),
    ("COMMANDS", None),
    ("cfg / help", "Toggle panels"),
    ("hclear", "Clear history"),
    ("hex / log", "Toggle hex / logging"),
    ("detail / live", "Toggle detail / follow"),
    ("q", "Exit"),
    ("INDICATORS", None),
    ("[LIVE]", "Auto-follow newest"),
    ("UL", "Uplink echo"),
    ("DUP", "Duplicate packet"),
    ("CRC:OK/FAIL", "Integrity check"),
]


# -- Config Side Panel --------------------------------------------------------

RX_CONFIG_FIELDS = [
    # (label, key, editable)
    ("Hex Display", "show_hex", True),
    ("Logging",     "logging",  True),
]


def rx_config_get_values(show_hex, logging_enabled):
    """Read current RX config into a dict."""
    return {
        "show_hex":     "ON" if show_hex else "OFF",
        "logging":      "ON" if logging_enabled else "OFF",
    }


def draw_rx_config(stdscr, region, values, selected=0, focused=False):
    """Draw the RX config panel in a side region."""
    y, x, h, w = region
    inner_w = w - 3

    # Vertical separator on the left edge
    draw_vline(stdscr, x, y, h, S_DIM)

    # Title
    title_attr = curses.color_pair(CP_WARNING) | curses.A_BOLD
    if not focused:
        title_attr = S_DIM
    safe_addstr(stdscr, y, x + 2, " CONFIGURATION ", title_attr)
    draw_hline(stdscr, y + 1, x + 1, w - 1, S_DIM)

    # Editable fields
    label_w = 14
    val_x = x + 2 + label_w + 1

    for i, (label, key, editable) in enumerate(RX_CONFIG_FIELDS):
        row = y + 2 + i
        if row >= y + h - 6:
            break
        is_selected = (i == selected and focused)

        marker = "\u25b6" if is_selected else " "
        marker_attr = S_SUCCESS if is_selected else S_DIM
        safe_addstr(stdscr, row, x + 1, marker, marker_attr)

        lbl_attr = curses.color_pair(CP_LABEL) if editable else S_DIM
        safe_addstr(stdscr, row, x + 3, label[:label_w], lbl_attr)

        val = values.get(key, "")
        if val == "ON":
            val_attr = S_SUCCESS
        elif val == "OFF":
            val_attr = S_DIM
        else:
            val_attr = S_VALUE
        safe_addstr(stdscr, row, val_x, val, val_attr)

    # Hints at bottom
    hints = "Tab:focus Up/Dn:select Enter:toggle"
    safe_addstr(stdscr, y + h - 1, x + 2, hints[:inner_w], S_DIM)


def draw_rx_help(stdscr, region, schema_count=0, schema_path="",
                 log_txt="", log_jsonl="", version=""):
    """Draw the RX help panel in a side region."""
    draw_help_panel(stdscr, region, RX_HELP_LINES, hint="Esc/?:close",
                    version=version, schema_count=schema_count,
                    schema_path=schema_path, log_path=log_txt)
