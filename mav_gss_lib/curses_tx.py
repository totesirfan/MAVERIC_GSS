"""
mav_gss_lib.curses_tx -- TX Dashboard Panels

Panel rendering and layout for the TX dashboard. Provides layout
calculation and draw functions for:
  - Header (callsigns, CSP, ZMQ, clock)
  - TX Queue (scrollable pending commands)
  - Sent History (scrollable command log)
  - Config (side panel, editable fields)
  - Help (side panel, reference)
  - Input (text entry with cursor)

Author:  Irfan Annuar - USC ISI SERC
"""

import curses
from datetime import datetime, timezone

from mav_gss_lib.protocol import NODE_NAMES, PTYPE_NAMES, node_label, GS_NODE
from mav_gss_lib.curses_common import (
    _safe, _hline, _vline,
    CP_LABEL, CP_VALUE, CP_SUCCESS, CP_WARNING, CP_ERROR, CP_DIM,
    MIN_COLS,
)


# -- Layout -------------------------------------------------------------------

HEADER_ROWS = 5   # title + separator + AX.25 + CSP + ZMQ/freq
INPUT_ROWS  = 3   # separator + prompt + hints
MIN_QUEUE   = 3   # title + at least 2 data rows
MIN_HISTORY = 3   # title + at least 2 data rows
MIN_ROWS    = HEADER_ROWS + INPUT_ROWS + MIN_QUEUE + MIN_HISTORY


def calculate_layout(max_y, max_x, side_panel=False):
    """Return panel regions as {name: (y, x, h, w)} dicts.

    When side_panel=True, the history area splits into left (history)
    and right (side_panel) halves.
    Returns None if terminal is too small.
    """
    if max_y < MIN_ROWS or max_x < MIN_COLS:
        return None

    w = max_x
    remaining = max_y - HEADER_ROWS - INPUT_ROWS
    queue_h = max(MIN_QUEUE, remaining // 3)
    history_h = remaining - queue_h
    if history_h < MIN_HISTORY:
        history_h = MIN_HISTORY
        queue_h = remaining - history_h

    hist_y = HEADER_ROWS + queue_h

    layout = {
        "header":  (0, 0, HEADER_ROWS, w),
        "queue":   (HEADER_ROWS, 0, queue_h, w),
        "input":   (max_y - INPUT_ROWS, 0, INPUT_ROWS, w),
    }

    if side_panel:
        side_w = w * 4 // 10
        main_w = w - side_w
        layout["history"]    = (hist_y, 0, history_h, main_w)
        layout["side_panel"] = (hist_y, main_w, history_h, side_w)
    else:
        layout["history"] = (hist_y, 0, history_h, w)

    return layout


# -- Header Panel -------------------------------------------------------------

def draw_header(stdscr, region, csp, ax25, zmq_addr, freq="435.0 MHz",
                log_path=""):
    """Draw the 4-row header with live clock, callsigns, CSP, ZMQ."""
    y, x, h, w = region
    utc_now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    local_now = datetime.now().strftime("%H:%M:%S")
    time_str = f"UTC {utc_now}  Local {local_now}"

    # Row 0: title + clock
    title = "MAVERIC TX DASHBOARD"
    _safe(stdscr, y, x + 1, title,
          curses.color_pair(CP_SUCCESS) | curses.A_BOLD)
    _safe(stdscr, y, x + w - len(time_str) - 1, time_str,
          curses.color_pair(CP_VALUE) | curses.A_BOLD)

    # Row 1: separator under title
    _hline(stdscr, y + 1, x, w, curses.color_pair(CP_DIM) | curses.A_DIM)

    # Row 2: AX.25 callsigns + CSP summary
    _safe(stdscr, y + 2, x + 1, "AX.25",
          curses.color_pair(CP_LABEL))
    _safe(stdscr, y + 2, x + 7,
          f"{ax25.src_call}-{ax25.src_ssid}"
          f" \u2192 {ax25.dest_call}-{ax25.dest_ssid}",
          curses.color_pair(CP_VALUE) | curses.A_BOLD)

    csp_str = (f"Prio:{csp.prio} Src:{csp.src} Dest:{csp.dest} "
               f"DPort:{csp.dport} SPort:{csp.sport} "
               f"Flags:0x{csp.flags:02X}")
    csp_x = w // 2
    _safe(stdscr, y + 2, x + csp_x, "CSP",
          curses.color_pair(CP_LABEL))
    _safe(stdscr, y + 2, x + csp_x + 4, csp_str,
          curses.color_pair(CP_DIM) | curses.A_DIM)

    # Row 3: ZMQ + Freq
    _safe(stdscr, y + 3, x + 1, "ZMQ",
          curses.color_pair(CP_LABEL))
    _safe(stdscr, y + 3, x + 7,
          f"{zmq_addr} [BOUND]",
          curses.color_pair(CP_VALUE) | curses.A_BOLD)
    freq_str = f"Freq: {freq}"
    _safe(stdscr, y + 3, x + csp_x, freq_str,
          curses.color_pair(CP_WARNING))

    # Row 4: separator
    _hline(stdscr, y + 4, x, w, curses.color_pair(CP_DIM) | curses.A_DIM)


# -- Queue Panel --------------------------------------------------------------

def draw_queue(stdscr, region, queue, scroll_offset=0, sending_idx=-1,
               tx_delay_ms=0):
    """Draw the TX Queue panel with scrollable command list.

    sending_idx: index of the command currently being sent (-1 = not sending).
    Items before sending_idx are dimmed (already sent), the active item is
    highlighted green, and items after are normal (waiting).
    """
    y, x, h, w = region

    # Title row
    count = len(queue)
    title = f" TX QUEUE ({count})  buf: {tx_delay_ms}ms"
    if count > 1:
        total_ms = (count - 1) * tx_delay_ms
        total_str = f"{total_ms / 1000:.1f}s" if total_ms >= 1000 else f"{total_ms}ms"
        title += f"  total: {total_str}"
    _safe(stdscr, y, x, title,
          curses.color_pair(CP_WARNING) | curses.A_BOLD)
    hints = "Ctrl+S: send | Ctrl+X: clear"
    _safe(stdscr, y, x + w - len(hints) - 2, hints,
          curses.color_pair(CP_DIM) | curses.A_DIM)

    # Data rows
    data_rows = h - 1
    if count == 0:
        _safe(stdscr, y + 1, x + 2, "(empty \u2014 type a command below)",
              curses.color_pair(CP_DIM) | curses.A_DIM)
    else:
        visible = queue[scroll_offset:scroll_offset + data_rows]
        for i, (dest, echo, ptype, cmd, args, raw_cmd) in enumerate(visible):
            row_y = y + 1 + i
            if row_y >= y + h:
                break
            idx = scroll_offset + i + 1
            abs_idx = scroll_offset + i  # 0-based index into queue
            dest_lbl = node_label(dest)
            echo_lbl = node_label(echo)
            ptype_lbl = PTYPE_NAMES.get(ptype, str(ptype))
            col = x + 1

            # Determine row style based on send progress
            if sending_idx >= 0 and abs_idx < sending_idx:
                _dim = curses.color_pair(CP_DIM) | curses.A_DIM
                base = _dim
                tag, tag_attr = " SENT", curses.color_pair(CP_SUCCESS) | curses.A_DIM
            elif sending_idx >= 0 and abs_idx == sending_idx:
                _grn = curses.color_pair(CP_SUCCESS) | curses.A_BOLD
                base = _grn
                tag, tag_attr = " SENDING", _grn
            else:
                base = 0
                tag, tag_attr = "", 0

            idx_str = f"{idx:>2}."
            _safe(stdscr, row_y, col, idx_str,
                  base | curses.color_pair(CP_WARNING))
            col += len(idx_str) + 1

            _safe(stdscr, row_y, col, dest_lbl,
                  base | curses.color_pair(CP_LABEL))
            col += len(dest_lbl) + 1

            echo_str = f"E:{echo_lbl}"
            _safe(stdscr, row_y, col, echo_str,
                  base | curses.color_pair(CP_DIM))
            col += len(echo_str) + 1

            _safe(stdscr, row_y, col, ptype_lbl,
                  base | curses.color_pair(CP_LABEL))
            col += len(ptype_lbl) + 1

            _safe(stdscr, row_y, col, cmd,
                  base | curses.color_pair(CP_VALUE) | curses.A_BOLD)
            col += len(cmd) + 1

            if args:
                _safe(stdscr, row_y, col, args,
                      base | curses.color_pair(CP_DIM))

            # Right side: size + optional tag
            right = f"({len(raw_cmd)}B)"
            if tag:
                right = tag + "  " + right
            _safe(stdscr, row_y, x + w - len(right) - 2, right,
                  tag_attr if tag else curses.color_pair(CP_DIM))

        if count > data_rows:
            ind = f"[{scroll_offset + 1}-{min(scroll_offset + data_rows, count)}/{count}]"
            _safe(stdscr, y + h - 1, x + w - len(ind) - 2, ind,
                  curses.color_pair(CP_DIM) | curses.A_DIM)

    _hline(stdscr, y + h - 1 if count <= data_rows - 1 else y + h,
           x, w, curses.color_pair(CP_DIM) | curses.A_DIM)


# -- History Panel ------------------------------------------------------------

def draw_history(stdscr, region, history, scroll_offset=0):
    """Draw the Sent History panel. Adapts to narrow width when side panel open."""
    y, x, h, w = region

    _hline(stdscr, y, x, w, curses.color_pair(CP_DIM) | curses.A_DIM)

    count = len(history)
    title = f" SENT HISTORY ({count})"
    _safe(stdscr, y + 1, x, title,
          curses.color_pair(CP_SUCCESS) | curses.A_BOLD)

    data_start = y + 2
    data_rows = h - 2
    if count == 0:
        _safe(stdscr, data_start, x + 2, "(no commands sent yet)",
              curses.color_pair(CP_DIM) | curses.A_DIM)
    else:
        # Bottom-anchored: scroll_offset is the last visible item index
        end = min(scroll_offset + 1, count)
        start = max(0, end - data_rows)
        visible = history[start:end]
        for i, rec in enumerate(visible):
            row_y = data_start + i
            if row_y >= y + h:
                break
            n = rec["n"]
            ts = rec["ts"]
            src_name = node_label(GS_NODE)
            dest_name = node_label(rec["dest"])
            echo_name = node_label(rec["echo"])
            ptype_name = PTYPE_NAMES.get(rec["ptype"], str(rec["ptype"]))
            cmd = rec["cmd"]
            args = rec["args"]
            size = f"{rec['payload_len']}B"

            col = x + 1

            tag = f"#{n}"
            _safe(stdscr, row_y, col, tag,
                  curses.color_pair(CP_SUCCESS) | curses.A_BOLD)
            col += max(len(tag), 4) + 1

            _safe(stdscr, row_y, col, ts,
                  curses.color_pair(CP_DIM))
            col += len(ts) + 1

            route_str = f"{src_name} \u2192 {dest_name}"
            _safe(stdscr, row_y, col, route_str,
                  curses.color_pair(CP_LABEL))
            col += len(route_str) + 1

            echo_str = f"E:{echo_name}"
            _safe(stdscr, row_y, col, echo_str,
                  curses.color_pair(CP_DIM))
            col += len(echo_str) + 1

            _safe(stdscr, row_y, col, ptype_name,
                  curses.color_pair(CP_LABEL))
            col += len(ptype_name) + 1

            _safe(stdscr, row_y, col, cmd,
                  curses.color_pair(CP_VALUE) | curses.A_BOLD)
            col += len(cmd) + 1

            # Right-aligned block
            right = f"({size})"
            right_x = x + w - len(right) - 2

            if args and col < right_x - 1:
                max_args_w = right_x - col - 1
                _safe(stdscr, row_y, col, args[:max_args_w],
                      curses.color_pair(CP_DIM))

            _safe(stdscr, row_y, right_x, right,
                  curses.color_pair(CP_DIM))

        if count > data_rows:
            ind = f"[{start + 1}-{end}/{count}]"
            _safe(stdscr, y + h - 1, x + w - len(ind) - 2, ind,
                  curses.color_pair(CP_DIM) | curses.A_DIM)


# -- Config Side Panel --------------------------------------------------------

CONFIG_FIELDS = [
    # (label, key, editable)
    ("AX.25 Src Call",  "ax25_src_call",  True),
    ("AX.25 Src SSID",  "ax25_src_ssid",  True),
    ("AX.25 Dest Call", "ax25_dest_call", True),
    ("AX.25 Dest SSID", "ax25_dest_ssid", True),
    ("CSP Priority",    "csp_prio",       True),
    ("CSP Source",      "csp_src",        True),
    ("CSP Destination", "csp_dest",       True),
    ("CSP Dest Port",   "csp_dport",      True),
    ("CSP Src Port",    "csp_sport",      True),
    ("CSP Flags",       "csp_flags",      True),
    ("Frequency",       "freq",           True),
    ("ZMQ Address",     "zmq_addr",       True),
    ("TX Delay (ms)",   "tx_delay_ms",    True),
    ("Log File",        "log_path",       False),
]


def config_get_values(csp, ax25, freq, zmq_addr, tx_delay_ms, log_path):
    """Read current config into a dict keyed by field key."""
    return {
        "ax25_src_call":  ax25.src_call,
        "ax25_src_ssid":  str(ax25.src_ssid),
        "ax25_dest_call": ax25.dest_call,
        "ax25_dest_ssid": str(ax25.dest_ssid),
        "csp_prio":       str(csp.prio),
        "csp_src":        str(csp.src),
        "csp_dest":       str(csp.dest),
        "csp_dport":      str(csp.dport),
        "csp_sport":      str(csp.sport),
        "csp_flags":      f"0x{csp.flags:02X}",
        "freq":           freq,
        "zmq_addr":       zmq_addr,
        "tx_delay_ms":    str(tx_delay_ms),
        "log_path":       log_path,
    }


def config_apply(values, csp, ax25):
    """Apply edited values back to csp/ax25. Returns (freq, zmq_addr, tx_delay_ms)."""
    ax25.src_call  = values["ax25_src_call"].upper()[:6]
    ax25.src_ssid  = int(values["ax25_src_ssid"]) & 0x0F
    ax25.dest_call = values["ax25_dest_call"].upper()[:6]
    ax25.dest_ssid = int(values["ax25_dest_ssid"]) & 0x0F
    csp.prio  = int(values["csp_prio"], 0)
    csp.src   = int(values["csp_src"], 0)
    csp.dest  = int(values["csp_dest"], 0)
    csp.dport = int(values["csp_dport"], 0)
    csp.sport = int(values["csp_sport"], 0)
    csp.flags = int(values["csp_flags"], 0)
    tx_delay_ms = max(0, int(values["tx_delay_ms"]))
    return values["freq"], values["zmq_addr"], tx_delay_ms


def draw_config(stdscr, region, values, selected, editing,
                edit_buf="", edit_cursor=0, focused=False):
    """Draw the config panel in a side region."""
    y, x, h, w = region
    dim = curses.color_pair(CP_DIM) | curses.A_DIM

    # Vertical separator on the left edge
    _vline(stdscr, x, y, h, dim)

    # Title — highlight when focused
    title_attr = curses.color_pair(CP_WARNING) | curses.A_BOLD
    if not focused and not editing:
        title_attr = dim
    _safe(stdscr, y, x + 2, " CONFIGURATION ",
          title_attr)
    _hline(stdscr, y + 1, x + 1, w - 1, dim)

    # Fields
    label_w = 16
    val_x = x + 2 + label_w + 1
    max_val_w = w - label_w - 5  # room for value text

    for i, (label, key, editable) in enumerate(CONFIG_FIELDS):
        row = y + 2 + i
        if row >= y + h - 1:
            break
        is_selected = (i == selected)

        # Marker — only show when focused
        marker = "\u25b6" if (is_selected and (focused or editing)) else " "
        marker_attr = curses.color_pair(CP_SUCCESS) | curses.A_BOLD if is_selected else dim
        _safe(stdscr, row, x + 1, marker, marker_attr)

        # Label
        lbl_attr = curses.color_pair(CP_LABEL) if editable else dim
        _safe(stdscr, row, x + 3, label[:label_w], lbl_attr)

        # Value
        if editing and is_selected:
            display = edit_buf[:max_val_w]
            _safe(stdscr, row, val_x, display,
                  curses.color_pair(CP_VALUE) | curses.A_BOLD)
            # Cursor
            cx = val_x + min(edit_cursor, max_val_w - 1)
            if cx < x + w - 1:
                ch = edit_buf[edit_cursor] if edit_cursor < len(edit_buf) else " "
                try:
                    stdscr.addch(row, cx, ord(ch),
                                 curses.A_REVERSE | curses.color_pair(CP_LABEL))
                except curses.error:
                    pass
        else:
            val = values.get(key, "")
            val_attr = curses.color_pair(CP_VALUE) | curses.A_BOLD
            if not editable:
                val_attr = dim
            if is_selected and not editing:
                val_attr |= curses.A_UNDERLINE
            _safe(stdscr, row, val_x, val[:max_val_w], val_attr)

    # Hints at bottom
    hint_row = y + h - 1
    if editing:
        hints = "Enter:save Esc:cancel"
    else:
        hints = "Tab:focus Up/Dn:select Enter:edit"
    _safe(stdscr, hint_row, x + 2, hints[:w - 3], dim)


# -- Help Side Panel ----------------------------------------------------------

HELP_LINES = [
    ("COMMAND FORMAT", None),
    ("DEST ECHO TYPE CMD [ARGS]", ""),
    ("  DEST/ECHO", "Node name or ID"),
    ("  TYPE", "REQ|RES|ACK|NONE"),
    ("SRC always GS (6)", ""),
    ("e.g.", "EPS UPPM REQ PING"),
    ("e.g.", "2 3 1 SET_VOLTAGE 3.3"),
    ("KEYS", None),
    ("Ctrl+S / Ctrl+X", "Send / clear queue"),
    ("Up / Down", "History recall"),
    ("PgUp / PgDn", "Scroll history"),
    ("Ctrl+A / Ctrl+E", "Cursor start / end"),
    ("Ctrl+W / Ctrl+U", "Del word / clear input"),
    ("COMMANDS", None),
    ("send", "Send all queued"),
    ("clear / hclear", "Clear queue / history"),
    ("cfg / help / nodes", "Panels & info"),
    ("raw <hex>", "Send raw bytes"),
    ("q", "Exit"),
]


def draw_help(stdscr, region, version="", schema_count=0,
              schema_path="", log_path=""):
    """Draw the help panel in a side region."""
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
    left_col_w = inner_w * 5 // 10
    right_col_x = x + 2 + left_col_w + 1
    max_right_w = w - left_col_w - 5

    row = y + 2
    for left, right in HELP_LINES:
        if row >= y + h - 5:
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
        if log_path:
            _safe(stdscr, info_start + 3, x + 2,
                  f"Log: {log_path}"[:inner_w], dim)

    # Hint
    _safe(stdscr, y + h - 1, x + 2, "Esc: close"[:inner_w], dim)


# -- Input Panel --------------------------------------------------------------

def draw_input(stdscr, region, buf, cursor_pos, queue_count, status_msg=""):
    """Draw the input area with prompt, cursor, and hints bar."""
    y, x, h, w = region

    # Row 0: separator
    _hline(stdscr, y, x, w, curses.color_pair(CP_DIM) | curses.A_DIM)

    # Row 1: prompt + input buffer
    _safe(stdscr, y + 1, x + 1, "> ",
          curses.color_pair(CP_LABEL) | curses.A_BOLD)

    max_input_w = w - 5
    visible_start = 0
    if cursor_pos > max_input_w - 1:
        visible_start = cursor_pos - max_input_w + 1
    visible_buf = buf[visible_start:visible_start + max_input_w]

    _safe(stdscr, y + 1, x + 3, visible_buf,
          curses.color_pair(CP_VALUE) | curses.A_BOLD)

    # Draw cursor
    cursor_screen_x = x + 3 + (cursor_pos - visible_start)
    if cursor_screen_x < w - 1:
        ch = buf[cursor_pos] if cursor_pos < len(buf) else " "
        try:
            stdscr.addch(y + 1, cursor_screen_x, ord(ch),
                         curses.A_REVERSE | curses.color_pair(CP_LABEL))
        except curses.error:
            pass

    # Row 2: hints + status
    if status_msg:
        _safe(stdscr, y + 2, x + 1, status_msg,
              curses.color_pair(CP_WARNING))
    else:
        hints = "Enter: queue | cfg | help | Ctrl+C: quit"
        _safe(stdscr, y + 2, x + 1, hints,
              curses.color_pair(CP_DIM) | curses.A_DIM)
