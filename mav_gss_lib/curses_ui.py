"""
mav_gss_lib.curses_ui -- Curses Dashboard Panels

Panel rendering and layout for the TX dashboard. Provides color pair
initialization, dynamic layout calculation, and draw functions for:
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

from mav_gss_lib.protocol import NODE_NAMES, node_label, ptype_label, GS_NODE


def _node_name(node_id):
    """Just the name, no number. E.g. 'EPS' instead of '2 (EPS)'."""
    return NODE_NAMES.get(node_id, str(node_id))


# -- Color pairs (indices) ----------------------------------------------------

CP_LABEL   = 1   # cyan   — field labels
CP_VALUE   = 2   # white  — field values (use with A_BOLD)
CP_SUCCESS = 3   # green  — TX success, status OK
CP_WARNING = 4   # yellow — warnings, batch mode
CP_ERROR   = 5   # red    — errors
CP_DIM     = 6   # white  — secondary info (use with A_DIM)
CP_HEADER  = 7   # cyan   — header bar (use with A_REVERSE)
CP_USC_CARDINAL = 8   # red    — USC cardinal (splash)
CP_USC_GOLD     = 9   # yellow — USC gold (splash)


def init_colors():
    """Initialize curses color pairs mirroring the ANSI Theme roles."""
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(CP_LABEL,   curses.COLOR_CYAN,  -1)
    curses.init_pair(CP_VALUE,   curses.COLOR_WHITE,  -1)
    curses.init_pair(CP_SUCCESS, curses.COLOR_GREEN,  -1)
    curses.init_pair(CP_WARNING, curses.COLOR_YELLOW, -1)
    curses.init_pair(CP_ERROR,   curses.COLOR_RED,    -1)
    curses.init_pair(CP_DIM,     curses.COLOR_WHITE,  -1)
    curses.init_pair(CP_HEADER,  curses.COLOR_CYAN,   -1)
    curses.init_pair(CP_USC_CARDINAL, curses.COLOR_RED,    -1)
    curses.init_pair(CP_USC_GOLD,     curses.COLOR_YELLOW, -1)


# -- Splash screen ------------------------------------------------------------

_USC_LOGO = [
    "██    ██  ██████   ██████ ",
    "██    ██  ██       ██     ",
    "██    ██  ██████   ██     ",
    "██    ██       ██  ██     ",
    " ██████   ██████   ██████ ",
]


def draw_splash(stdscr):
    """Full-screen centered splash with USC logo in cardinal/gold."""
    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()

    # Total block: 5 logo + blank + ISI + SERC full + blank + subtitle = 10 lines
    block_h = 10
    start_y = max(0, (max_y - block_h) // 2)

    cardinal = curses.color_pair(CP_USC_CARDINAL) | curses.A_BOLD
    gold = curses.color_pair(CP_USC_GOLD) | curses.A_BOLD

    # USC block letters
    for i, line in enumerate(_USC_LOGO):
        col = max(0, (max_x - len(line)) // 2)
        _safe(stdscr, start_y + i, col, line, cardinal)

    # ISI + SERC + subtitle
    for offset, text, attr in [
        (6, "ISI", gold),
        (7, "Space Engineering Research Center", gold),
        (9, "MAVERIC Ground Station", curses.color_pair(CP_DIM)),
    ]:
        col = max(0, (max_x - len(text)) // 2)
        _safe(stdscr, start_y + offset, col, text, attr)

    stdscr.refresh()
    curses.napms(2000)
    curses.flushinp()


# -- Layout -------------------------------------------------------------------

HEADER_ROWS = 5   # title + separator + AX.25 + CSP + ZMQ/freq
INPUT_ROWS  = 3   # separator + prompt + hints
MIN_QUEUE   = 3   # title + at least 2 data rows
MIN_HISTORY = 3   # title + at least 2 data rows
MIN_ROWS    = HEADER_ROWS + INPUT_ROWS + MIN_QUEUE + MIN_HISTORY
MIN_COLS    = 80


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
        half = w // 2
        layout["history"]    = (hist_y, 0, history_h, half)
        layout["side_panel"] = (hist_y, half, history_h, w - half)
    else:
        layout["history"] = (hist_y, 0, history_h, w)

    return layout


# -- Safe addstr --------------------------------------------------------------

def _safe(win, y, x, text, attr=0):
    """addstr that silently ignores writes past the window edge."""
    try:
        win.addnstr(y, x, text, win.getmaxyx()[1] - x - 1, attr)
    except curses.error:
        pass


def _hline(win, y, x, w, attr=0):
    """Draw a horizontal line."""
    try:
        win.addnstr(y, x, "\u2500" * w, w, attr)
    except curses.error:
        pass


def _vline(win, x, y_start, h, attr=0):
    """Draw a vertical line."""
    for row in range(h):
        try:
            win.addch(y_start + row, x, "\u2502", attr)
        except curses.error:
            pass


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
    total_ms = (count - 1) * tx_delay_ms if count > 1 else 0
    if total_ms >= 1000:
        total_str = f"{total_ms / 1000:.1f}s"
    else:
        total_str = f"{total_ms}ms"
    if count > 1:
        title = f" TX QUEUE ({count})  buf: {tx_delay_ms}ms  total: {total_str}"
    else:
        title = f" TX QUEUE ({count})  buf: {tx_delay_ms}ms"
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
        for i, (dest, cmd, args, raw_cmd) in enumerate(visible):
            row_y = y + 1 + i
            if row_y >= y + h:
                break
            idx = scroll_offset + i + 1
            abs_idx = scroll_offset + i  # 0-based index into queue
            dest_lbl = _node_name(dest)
            col = x + 1

            # Determine row style based on send progress
            if sending_idx >= 0 and abs_idx < sending_idx:
                _dim = curses.color_pair(CP_DIM) | curses.A_DIM
                lbl_attr = val_attr = idx_attr = _dim
                tag, tag_attr = " SENT", curses.color_pair(CP_SUCCESS) | curses.A_DIM
            elif sending_idx >= 0 and abs_idx == sending_idx:
                _grn = curses.color_pair(CP_SUCCESS) | curses.A_BOLD
                lbl_attr = val_attr = idx_attr = _grn
                tag, tag_attr = " SENDING", _grn
            else:
                lbl_attr = curses.color_pair(CP_LABEL) | curses.A_BOLD
                val_attr = curses.color_pair(CP_VALUE) | curses.A_BOLD
                idx_attr = curses.color_pair(CP_DIM) | curses.A_DIM
                tag, tag_attr = "", 0

            idx_str = f"{idx:>2}."
            _safe(stdscr, row_y, col, idx_str, idx_attr)
            col += len(idx_str) + 1

            _safe(stdscr, row_y, col, dest_lbl, lbl_attr)
            col += len(dest_lbl) + 1

            _safe(stdscr, row_y, col, cmd, val_attr)
            col += len(cmd) + 1

            if args:
                _safe(stdscr, row_y, col, args,
                      val_attr & ~curses.A_BOLD if sending_idx < 0 else val_attr)

            # Right side: size + optional tag
            right = f"({len(raw_cmd)}B)"
            if tag:
                right = tag + "  " + right
            _safe(stdscr, row_y, x + w - len(right) - 2, right,
                  tag_attr if tag else curses.color_pair(CP_DIM) | curses.A_DIM)

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
            dest_name = _node_name(rec["dest"])
            cmd = rec["cmd"]
            args = rec["args"]
            ptype_lbl = ptype_label(rec["ptype"])
            size = f"{rec['payload_len']}B"

            col = x + 1

            tag = f"#{n}"
            _safe(stdscr, row_y, col, tag,
                  curses.color_pair(CP_SUCCESS) | curses.A_BOLD)
            col += max(len(tag), 4) + 1

            _safe(stdscr, row_y, col, ts,
                  curses.color_pair(CP_DIM) | curses.A_DIM)
            col += 10

            _safe(stdscr, row_y, col, dest_name,
                  curses.color_pair(CP_LABEL) | curses.A_BOLD)
            col += len(dest_name) + 1

            _safe(stdscr, row_y, col, cmd,
                  curses.color_pair(CP_VALUE) | curses.A_BOLD)
            col += len(cmd) + 1

            # Right side metadata — only if enough room
            right = (f"Src:{GS_NODE}  Dest:{rec['dest']}  "
                     f"Echo:{rec['echo']}  Type:{ptype_lbl}  "
                     f"{size}")
            right_x = x + w - len(right) - 1

            if args:
                if right_x > col + 2:
                    max_args_w = max(0, right_x - col - 1)
                    _safe(stdscr, row_y, col, args[:max_args_w],
                          curses.color_pair(CP_VALUE))
                else:
                    # No room for right side, just show args
                    _safe(stdscr, row_y, col, args[:w - col - 1],
                          curses.color_pair(CP_VALUE))
                    continue

            if right_x > col:
                _safe(stdscr, row_y, right_x, right,
                      curses.color_pair(CP_DIM) | curses.A_DIM)

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
    inner_w = w - 3

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
    ("<dest> <cmd> [args]", "e.g. EPS SET_VOLTAGE 3.3"),
    ("", ""),
    ("DESTINATIONS", None),
    ("Node name or number", "EPS, LPPM, 2, 3"),
    ("nodes", "List all node IDs"),
    ("", ""),
    ("COMMAND SCHEMA", None),
    ("maveric_commands.yml", "Valid command defs"),
    ("Invalid cmds rejected", "Edit YAML to add"),
    ("", ""),
    ("KEYBOARD SHORTCUTS", None),
    ("Ctrl+S", "Send queued"),
    ("Ctrl+X", "Clear queue"),
    ("Up / Down", "History recall"),
    ("PgUp / PgDn", "Scroll history"),
    ("Ctrl+A / Ctrl+E", "Start / end"),
    ("Ctrl+W / Ctrl+U", "Del word / clear"),
    ("", ""),
    ("COMMANDS", None),
    ("send", "Send all queued"),
    ("clear", "Clear queue"),
    ("config / cfg", "Config panel"),
    ("help", "This panel"),
    ("nodes", "List node IDs"),
    ("raw <hex>", "Send raw bytes"),
    ("q / quit", "Exit"),
    ("", ""),
    ("LOGGING", None),
    ("All TX logged to", "logs/uplink_*.jsonl"),
    ("Log path in", "config panel"),
]


def draw_help(stdscr, region):
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
    left_col_w = min(22, inner_w // 2)
    right_col_x = x + 2 + left_col_w + 1
    max_right_w = w - left_col_w - 5

    visible = min(len(HELP_LINES), h - 3)
    for i in range(visible):
        left, right = HELP_LINES[i]
        row = y + 2 + i
        if row >= y + h - 1:
            break

        if right is None:
            # Section header
            _safe(stdscr, row, x + 2, left[:inner_w],
                  curses.color_pair(CP_LABEL) | curses.A_BOLD)
        elif left == "":
            continue
        else:
            _safe(stdscr, row, x + 3, left[:left_col_w],
                  curses.color_pair(CP_VALUE) | curses.A_BOLD)
            if right and max_right_w > 0:
                _safe(stdscr, row, right_col_x, right[:max_right_w],
                      curses.color_pair(CP_DIM) | curses.A_DIM)

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
