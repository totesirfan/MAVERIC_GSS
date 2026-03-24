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

from mav_gss_lib.protocol import NODE_NAMES, node_label, ptype_label
from mav_gss_lib.curses_common import (
    _safe, _hline, _vline,
    CP_LABEL, CP_VALUE, CP_SUCCESS, CP_WARNING, CP_ERROR, CP_DIM,
    MIN_COLS,
)


def _compact_node(node_id):
    """Compact node label: '2(EPS)' or '99' if unknown."""
    name = NODE_NAMES.get(node_id)
    return f"{node_id}({name})" if name else str(node_id)


# -- Layout -------------------------------------------------------------------

RX_HEADER_ROWS = 3    # title+clock + separator + ZMQ/toggles
RX_INPUT_ROWS  = 2    # status line + prompt/hints line
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
        half = lw // 2
        layout["packet_list"] = (ly, lx, lh, half)
        layout["side_panel"] = (ly, half, lh, lw - half)

    return layout


# -- Header Panel -------------------------------------------------------------

def draw_rx_header(stdscr, region, zmq_addr, freq="437.25 MHz",
                   show_hex=True, logging_enabled=True):
    """Draw the 3-row RX header with live clock, ZMQ, freq, and toggles."""
    y, x, h, w = region
    utc_now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    local_now = datetime.now().strftime("%H:%M:%S")
    time_str = f"UTC {utc_now}  Local {local_now}"

    # Row 0: title + clock
    title = "MAVERIC RX MONITOR"
    _safe(stdscr, y, x + 1, title,
          curses.color_pair(CP_SUCCESS) | curses.A_BOLD)
    _safe(stdscr, y, x + w - len(time_str) - 1, time_str,
          curses.color_pair(CP_VALUE) | curses.A_BOLD)

    # Row 1: separator
    _hline(stdscr, y + 1, x, w, curses.color_pair(CP_DIM) | curses.A_DIM)

    # Row 2: ZMQ address + freq + toggle indicators
    _safe(stdscr, y + 2, x + 1, "ZMQ",
          curses.color_pair(CP_LABEL))
    _safe(stdscr, y + 2, x + 5,
          f"{zmq_addr} [SUB]",
          curses.color_pair(CP_VALUE) | curses.A_BOLD)

    # Frequency (middle area)
    freq_str = f"Freq: {freq}"
    freq_x = x + 5 + len(zmq_addr) + 8
    _safe(stdscr, y + 2, freq_x, freq_str,
          curses.color_pair(CP_WARNING))

    # Right side: HEX and LOG toggles
    hex_state = "ON" if show_hex else "OFF"
    log_state = "ON" if logging_enabled else "OFF"
    on_attr = curses.color_pair(CP_SUCCESS)
    off_attr = curses.color_pair(CP_DIM) | curses.A_DIM
    hex_attr = on_attr if show_hex else off_attr
    log_attr = on_attr if logging_enabled else off_attr

    toggles = f"HEX:{hex_state}  LOG:{log_state}"
    toggle_x = x + w - len(toggles) - 1
    _safe(stdscr, y + 2, toggle_x, "HEX:", curses.color_pair(CP_LABEL))
    _safe(stdscr, y + 2, toggle_x + 4, hex_state, hex_attr)
    _safe(stdscr, y + 2, toggle_x + 4 + len(hex_state) + 2, "LOG:",
          curses.color_pair(CP_LABEL))
    _safe(stdscr, y + 2, toggle_x + 4 + len(hex_state) + 6, log_state,
          log_attr)


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
    _hline(stdscr, y, x, w, curses.color_pair(CP_DIM) | curses.A_DIM)

    # Title row
    title = f" PACKETS ({count})"
    _safe(stdscr, y + 1, x, title,
          curses.color_pair(CP_SUCCESS) | curses.A_BOLD)

    if auto_follow:
        _safe(stdscr, y + 1, x + len(title) + 2, "[LIVE]",
              curses.color_pair(CP_WARNING) | curses.A_BOLD)

    data_start = y + 2
    data_rows = h - 2

    if count == 0:
        _safe(stdscr, data_start, x + 2,
              "(waiting for packets...)",
              curses.color_pair(CP_DIM) | curses.A_DIM)
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
        _safe(stdscr, y + 1, x + w - len(ind) - 2, ind,
              curses.color_pair(CP_DIM) | curses.A_DIM)

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

        # Command fields
        cmd = pkt.get("cmd")
        if cmd:
            cmd_id = cmd["cmd_id"]
            cmd_src = _compact_node(cmd["src"])
            cmd_dest = _compact_node(cmd["dest"])
            cmd_echo = _compact_node(cmd["echo"])
            cmd_type = ptype_label(cmd["pkt_type"])
            # Build args string
            if cmd.get("schema_match"):
                arg_parts = []
                for ta in cmd.get("typed_args", []):
                    if ta["type"] == "epoch_ms" and isinstance(ta["value"], dict):
                        arg_parts.append(str(ta["value"]["ms"]))
                    else:
                        arg_parts.append(str(ta["value"]))
                for extra in cmd.get("extra_args", []):
                    arg_parts.append(str(extra))
                args_str = " ".join(arg_parts)
            else:
                args_str = " ".join(str(a) for a in cmd.get("args", []))
        else:
            cmd_id = "--"
            cmd_src = cmd_dest = cmd_echo = cmd_type = "--"
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
            _safe(stdscr, row_y, x, " " * w, base_attr)

        col = x + 1

        # Packet number
        num_str = f"#{pkt_num:<5}"
        _safe(stdscr, row_y, col, num_str,
              base_attr | curses.color_pair(CP_DIM))
        col += len(num_str)

        # Timestamp
        _safe(stdscr, row_y, col, ts_short,
              base_attr | curses.color_pair(CP_DIM))
        col += len(ts_short) + 1

        # Frame type
        if frame_type == "AX.25":
            ft_attr = curses.color_pair(CP_WARNING)
        elif frame_type == "AX100":
            ft_attr = curses.color_pair(CP_SUCCESS)
        else:
            ft_attr = curses.color_pair(CP_ERROR)
        _safe(stdscr, row_y, col, f"{frame_type:<6}",
              base_attr | ft_attr)
        col += 7

        # Command src→dest
        route_str = f"{cmd_src} \u2192 {cmd_dest}"
        _safe(stdscr, row_y, col, route_str,
              base_attr | curses.color_pair(CP_LABEL))
        col += len(route_str) + 1

        # Command ID
        cmd_display = cmd_id[:14] if len(cmd_id) > 14 else cmd_id
        _safe(stdscr, row_y, col, cmd_display,
              base_attr | curses.color_pair(CP_VALUE) | curses.A_BOLD)
        col += len(cmd_display) + 1

        # Right-aligned block: args + size + CRC + DUP
        # Build right side first to know where it starts
        right_parts = []
        if crc_str:
            right_parts.append(crc_str)
        right_parts.append(size_str)
        if is_dup:
            right_parts.append("DUP")
        right_str = "  ".join(right_parts)
        right_x = x + w - len(right_str) - 2

        # Args — fill space between cmd_id and right block
        if args_str and col < right_x - 1:
            max_args_w = right_x - col - 1
            _safe(stdscr, row_y, col, args_str[:max_args_w],
                  base_attr | curses.color_pair(CP_DIM))

        # Draw right-aligned block
        rx = right_x
        if is_dup:
            dup_w = 3
            _safe(stdscr, row_y, rx + len(right_str) - dup_w, "DUP",
                  base_attr | curses.color_pair(CP_ERROR) | curses.A_BOLD)
        # Size
        size_x = right_x
        if crc_str:
            # CRC first, then size
            if "OK" in crc_str:
                crc_attr = curses.color_pair(CP_SUCCESS)
            else:
                crc_attr = curses.color_pair(CP_ERROR) | curses.A_BOLD
            _safe(stdscr, row_y, rx, crc_str,
                  base_attr | crc_attr)
            rx += len(crc_str) + 2
        _safe(stdscr, row_y, rx, size_str,
              base_attr | curses.color_pair(CP_DIM))


# -- Packet Detail Panel ------------------------------------------------------

def draw_packet_detail(stdscr, region, packet, show_hex=True):
    """Draw the expanded detail view of a selected packet."""
    y, x, h, w = region
    if not packet:
        return

    dim = curses.color_pair(CP_DIM) | curses.A_DIM
    lbl = curses.color_pair(CP_LABEL)
    val = curses.color_pair(CP_VALUE) | curses.A_BOLD

    # Top separator + title
    _hline(stdscr, y, x, w, dim)
    pkt_num = packet.get("pkt_num", 0)
    title = f" PACKET #{pkt_num} DETAIL"
    _safe(stdscr, y + 1, x, title,
          curses.color_pair(CP_WARNING) | curses.A_BOLD)

    row = y + 2
    max_row = y + h - 1  # leave last row empty

    # Warnings
    for warning in packet.get("warnings", []):
        if row >= max_row:
            break
        _safe(stdscr, row, x + 2,
              f"\u26a0 {warning}",
              curses.color_pair(CP_ERROR))
        row += 1

    # AX.25 header
    stripped_hdr = packet.get("stripped_hdr")
    if stripped_hdr and row < max_row:
        _safe(stdscr, row, x + 2, "AX.25 HDR", lbl)
        _safe(stdscr, row, x + 14, stripped_hdr[:w - 16], dim)
        row += 1

    # CSP
    csp = packet.get("csp")
    if csp and row < max_row:
        csp_plausible = packet.get("csp_plausible", False)
        tag = "CSP V1" if csp_plausible else "CSP V1 [?]"
        _safe(stdscr, row, x + 2, tag, lbl)
        csp_str = (f"Prio:{csp['prio']}  Src:{csp['src']}  "
                   f"Dest:{csp['dest']}  DPort:{csp['dport']}  "
                   f"SPort:{csp['sport']}  Flags:0x{csp['flags']:02x}")
        _safe(stdscr, row, x + 2 + len(tag) + 2, csp_str, val)
        row += 1

    # SAT TIME
    ts_result = packet.get("ts_result")
    if row < max_row:
        _safe(stdscr, row, x + 2, "SAT TIME", lbl)
        if ts_result:
            dt_utc, dt_local, raw_ms = ts_result
            ts_str = (f"{dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}  \u2502  "
                      f"{dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            _safe(stdscr, row, x + 14, ts_str, val)
        else:
            _safe(stdscr, row, x + 14, "--", dim)
        row += 1

    # Command
    cmd = packet.get("cmd")
    if cmd and row < max_row:
        _safe(stdscr, row, x + 2, "CMD", lbl)
        cmd_info = (f"Src:{node_label(cmd['src'])}  "
                    f"Dest:{node_label(cmd['dest'])}  "
                    f"Echo:{node_label(cmd['echo'])}  "
                    f"Type:{ptype_label(cmd['pkt_type'])}")
        _safe(stdscr, row, x + 14, cmd_info, val)
        row += 1

        if row < max_row:
            _safe(stdscr, row, x + 2, "CMD ID", lbl)
            _safe(stdscr, row, x + 14, cmd["cmd_id"], val)
            row += 1

        # Schema-matched args
        if cmd.get("schema_match") and row < max_row:
            for ta in cmd.get("typed_args", []):
                if row >= max_row:
                    break
                label = ta["name"].upper()
                if ta["type"] == "epoch_ms" and isinstance(ta["value"], dict):
                    value = str(ta["value"]["ms"])
                else:
                    value = str(ta["value"])
                _safe(stdscr, row, x + 2, label[:12], lbl)
                _safe(stdscr, row, x + 14, value[:w - 16], val)
                row += 1
            for i, extra in enumerate(cmd.get("extra_args", [])):
                if row >= max_row:
                    break
                _safe(stdscr, row, x + 2, f"ARG +{i}", lbl)
                _safe(stdscr, row, x + 14, str(extra)[:w - 16], val)
                row += 1
        elif not cmd.get("schema_match"):
            if cmd.get("schema_warning") and row < max_row:
                _safe(stdscr, row, x + 2,
                      f"\u26a0 {cmd['schema_warning']}",
                      curses.color_pair(CP_WARNING))
                row += 1
            for i, arg in enumerate(cmd.get("args", [])):
                if row >= max_row:
                    break
                _safe(stdscr, row, x + 2, f"ARG {i}", lbl)
                _safe(stdscr, row, x + 14, str(arg)[:w - 16], val)
                row += 1

    # HEX dump (toggleable)
    if show_hex and row < max_row:
        raw = packet.get("raw", b"")
        if raw:
            hex_str = raw.hex(" ")
            _safe(stdscr, row, x + 2, "HEX", lbl)
            # Wrap hex across available lines
            hex_w = w - 16
            offset = 0
            while offset < len(hex_str) and row < max_row:
                chunk = hex_str[offset:offset + hex_w]
                _safe(stdscr, row, x + 14, chunk, dim)
                offset += hex_w
                row += 1

        # ASCII
        text = packet.get("text", "")
        if text and row < max_row:
            _safe(stdscr, row, x + 2, "ASCII", lbl)
            _safe(stdscr, row, x + 14, text[:w - 16], dim)
            row += 1

    # CRC status
    if cmd and row < max_row:
        if cmd.get("crc") is not None:
            valid = cmd.get("crc_valid")
            tag = "OK" if valid else "FAIL"
            crc_attr = curses.color_pair(CP_SUCCESS) if valid else curses.color_pair(CP_ERROR)
            _safe(stdscr, row, x + 2, "CRC-16", lbl)
            _safe(stdscr, row, x + 14, f"0x{cmd['crc']:04x}  [{tag}]", crc_attr)
            row += 1

    crc_status = packet.get("crc_status", {})
    if crc_status.get("csp_crc32_valid") is not None and row < max_row:
        valid = crc_status["csp_crc32_valid"]
        tag = "OK" if valid else "FAIL"
        crc_attr = curses.color_pair(CP_SUCCESS) if valid else curses.color_pair(CP_ERROR)
        _safe(stdscr, row, x + 2, "CRC-32C", lbl)
        _safe(stdscr, row, x + 14,
              f"0x{crc_status['csp_crc32_rx']:08x}  [{tag}]", crc_attr)
        row += 1

    # SHA-256
    fp = packet.get("fp", "")
    if fp and row < max_row:
        _safe(stdscr, row, x + 2, "SHA256", lbl)
        _safe(stdscr, row, x + 14, fp, dim)


# -- Input Panel --------------------------------------------------------------

def draw_rx_input(stdscr, region, buf, cursor_pos, silence_secs, pkt_count,
                  rate_per_min, receiving=False, spinner_char="\u2588",
                  status_msg="", error_msg=""):
    """Draw the 2-row input area: status line on top, prompt+hints on bottom."""
    y, x, h, w = region

    # Row 0: status line (spinner + receiving/silence + stats)
    col = x + 1

    if error_msg:
        _safe(stdscr, y, col, error_msg[:w - 2],
              curses.color_pair(CP_ERROR))
    elif status_msg:
        _safe(stdscr, y, col, status_msg[:w - 2],
              curses.color_pair(CP_WARNING))
    else:
        # Spinner
        _safe(stdscr, y, col, spinner_char,
              curses.color_pair(CP_LABEL) | curses.A_BOLD)
        col += 2

        # Receiving / Silence
        if receiving:
            _safe(stdscr, y, col, "Receiving",
                  curses.color_pair(CP_SUCCESS) | curses.A_BOLD)
            col += 11
        else:
            if silence_secs <= 10:
                silence_attr = curses.color_pair(CP_SUCCESS)
            elif silence_secs <= 30:
                silence_attr = curses.color_pair(CP_WARNING)
            else:
                silence_attr = curses.color_pair(CP_ERROR)
            silence_str = f"Silence: {silence_secs:05.1f}s"
            _safe(stdscr, y, col, silence_str, silence_attr)
            col += len(silence_str) + 2

        # Packet count + rate
        stats = f"{pkt_count} pkts"
        if rate_per_min > 0:
            stats += f"  {rate_per_min:.0f} pkt/min"
        _safe(stdscr, y, col, stats,
              curses.color_pair(CP_DIM) | curses.A_DIM)

    # Row 1: prompt + input buffer (left) + hints (right)
    row1 = y + 1
    _safe(stdscr, row1, x + 1, "> ",
          curses.color_pair(CP_LABEL) | curses.A_BOLD)

    # Right side: hints
    hints = "help | cfg | q"
    hints_x = x + w - len(hints) - 1
    _safe(stdscr, row1, hints_x, hints,
          curses.color_pair(CP_DIM) | curses.A_DIM)

    # Input buffer (between prompt and hints)
    max_input_w = hints_x - (x + 3) - 1
    visible_start = 0
    if cursor_pos > max_input_w - 1:
        visible_start = cursor_pos - max_input_w + 1
    visible_buf = buf[visible_start:visible_start + max_input_w]

    _safe(stdscr, row1, x + 3, visible_buf,
          curses.color_pair(CP_VALUE) | curses.A_BOLD)

    # Draw cursor
    cursor_screen_x = x + 3 + (cursor_pos - visible_start)
    if cursor_screen_x < hints_x - 1:
        ch = buf[cursor_pos] if cursor_pos < len(buf) else " "
        try:
            stdscr.addch(row1, cursor_screen_x, ord(ch),
                         curses.A_REVERSE | curses.color_pair(CP_LABEL))
        except curses.error:
            pass


# -- Help Side Panel ----------------------------------------------------------

RX_HELP_LINES = [
    ("KEYBOARD", None),
    ("Up / Down", "Select packet (Down on last \u2192 LIVE)"),
    ("PgUp / PgDn", "Scroll page"),
    ("Home / End", "First / last packet"),
    ("Enter", "Toggle detail panel"),
    ("Ctrl+C", "Quit"),
    ("", ""),
    ("COMMANDS", None),
    ("help", "Toggle this panel"),
    ("cfg / config", "Toggle config panel"),
    ("q / quit", "Exit"),
    ("", ""),
    ("INDICATORS", None),
    ("[LIVE]", "Auto-follow newest"),
    ("DUP", "Duplicate packet"),
    ("CRC:OK / FAIL", "Integrity check"),
]


# -- Config Side Panel --------------------------------------------------------

RX_CONFIG_FIELDS = [
    # (label, key, editable)
    ("Hex Display", "show_hex", True),
    ("Logging",     "logging",  True),
]


def rx_config_get_values(show_hex, logging_enabled, log_path="",
                         schema_count=0, schema_path="", version=""):
    """Read current RX config into a dict."""
    return {
        "show_hex":     "ON" if show_hex else "OFF",
        "logging":      "ON" if logging_enabled else "OFF",
        "log_path":     log_path,
        "schema":       f"{schema_count} cmds ({schema_path})" if schema_count else "MISSING",
        "version":      version,
    }


def draw_rx_config(stdscr, region, values, selected=0, focused=False):
    """Draw the RX config panel in a side region."""
    y, x, h, w = region
    dim = curses.color_pair(CP_DIM) | curses.A_DIM
    inner_w = w - 3

    # Vertical separator on the left edge
    _vline(stdscr, x, y, h, dim)

    # Title
    title_attr = curses.color_pair(CP_WARNING) | curses.A_BOLD
    if not focused:
        title_attr = dim
    _safe(stdscr, y, x + 2, " CONFIGURATION ", title_attr)
    _hline(stdscr, y + 1, x + 1, w - 1, dim)

    # Editable fields
    label_w = 14
    val_x = x + 2 + label_w + 1

    for i, (label, key, editable) in enumerate(RX_CONFIG_FIELDS):
        row = y + 2 + i
        if row >= y + h - 6:
            break
        is_selected = (i == selected and focused)

        marker = "\u25b6" if is_selected else " "
        marker_attr = curses.color_pair(CP_SUCCESS) | curses.A_BOLD if is_selected else dim
        _safe(stdscr, row, x + 1, marker, marker_attr)

        lbl_attr = curses.color_pair(CP_LABEL) if editable else dim
        _safe(stdscr, row, x + 3, label[:label_w], lbl_attr)

        val = values.get(key, "")
        if val == "ON":
            val_attr = curses.color_pair(CP_SUCCESS) | curses.A_BOLD
        elif val == "OFF":
            val_attr = curses.color_pair(CP_DIM) | curses.A_DIM
        else:
            val_attr = curses.color_pair(CP_VALUE) | curses.A_BOLD
        _safe(stdscr, row, val_x, val, val_attr)

    # Info section below editable fields
    info_row = y + 2 + len(RX_CONFIG_FIELDS) + 1
    _hline(stdscr, info_row, x + 1, w - 1, dim)
    info_row += 1

    for label, key in [("Log File", "log_path"), ("Schema", "schema"),
                       ("Version", "version")]:
        if info_row >= y + h - 1:
            break
        _safe(stdscr, info_row, x + 3, label, dim)
        _safe(stdscr, info_row, val_x, values.get(key, "")[:w - val_x - 1], dim)
        info_row += 1

    # Hints at bottom
    hints = "Tab:focus Up/Dn:select Enter:toggle"
    _safe(stdscr, y + h - 1, x + 2, hints[:inner_w], dim)


def draw_rx_help(stdscr, region, schema_count=0, schema_path="",
                 log_txt="", log_jsonl="", version=""):
    """Draw the RX help panel in a side region."""
    y, x, h, w = region
    dim = curses.color_pair(CP_DIM) | curses.A_DIM
    inner_w = w - 3

    # Vertical separator on the left edge
    _vline(stdscr, x, y, h, dim)

    # Title
    _safe(stdscr, y, x + 2, " HELP ",
          curses.color_pair(CP_WARNING) | curses.A_BOLD)
    _hline(stdscr, y + 1, x + 1, w - 1, dim)

    # Two-column layout
    left_col_w = min(18, inner_w // 2)
    right_col_x = x + 2 + left_col_w + 1
    max_right_w = w - left_col_w - 5

    row = y + 2
    for left, right in RX_HELP_LINES:
        if row >= y + h - 5:  # leave room for info section
            break
        if right is None:
            _safe(stdscr, row, x + 2, left[:inner_w],
                  curses.color_pair(CP_LABEL) | curses.A_BOLD)
        elif left == "":
            row += 1
            continue
        else:
            _safe(stdscr, row, x + 3, left[:left_col_w],
                  curses.color_pair(CP_VALUE) | curses.A_BOLD)
            if right and max_right_w > 0:
                _safe(stdscr, row, right_col_x, right[:max_right_w], dim)
        row += 1

    # Info section at bottom
    info_start = y + h - 5
    if info_start > row:
        _hline(stdscr, info_start, x + 1, w - 1, dim)
        if version:
            _safe(stdscr, info_start + 1, x + 2, f"Version: {version}", dim)
        if schema_count > 0:
            _safe(stdscr, info_start + 2, x + 2,
                  f"Schema: {schema_count} cmds ({schema_path})", dim)
        if log_txt:
            _safe(stdscr, info_start + 3, x + 2,
                  f"Log: {log_txt}"[:inner_w], dim)

    # Hint
    _safe(stdscr, y + h - 1, x + 2, "Esc/?:close"[:inner_w], dim)
