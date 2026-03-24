"""
mav_gss_lib.curses_common -- Shared Curses Utilities

Color pairs, safe drawing helpers, and splash screen shared by both
the TX dashboard (curses_tx) and the RX monitor (curses_rx).

Author:  Irfan Annuar - USC ISI SERC
"""

import curses


# -- Buffer editing -----------------------------------------------------------

def edit_buffer(ch, buf, cursor):
    """Handle a keystroke for text buffer editing.
    Returns (new_buf, new_cursor, handled).

    Shared by MAV_TX2 and MAV_RX2 dashboards.
    """
    if ch in (curses.KEY_BACKSPACE, 127, 8):
        if cursor > 0:
            return buf[:cursor - 1] + buf[cursor:], cursor - 1, True
        return buf, cursor, True
    if ch == curses.KEY_DC:
        if cursor < len(buf):
            return buf[:cursor] + buf[cursor + 1:], cursor, True
        return buf, cursor, True
    if ch == curses.KEY_LEFT:
        return buf, max(0, cursor - 1), True
    if ch == curses.KEY_RIGHT:
        return buf, min(len(buf), cursor + 1), True
    if ch in (curses.KEY_HOME, 1):  # Ctrl+A
        return buf, 0, True
    if ch in (curses.KEY_END, 5):  # Ctrl+E
        return buf, len(buf), True
    if ch == 21:  # Ctrl+U — clear line
        return "", 0, True
    if ch == 11:  # Ctrl+K — kill to end
        return buf[:cursor], cursor, True
    if ch == 23:  # Ctrl+W — delete word backwards
        if cursor > 0:
            p = cursor - 1
            while p > 0 and buf[p - 1] == ' ':
                p -= 1
            while p > 0 and buf[p - 1] != ' ':
                p -= 1
            return buf[:p] + buf[cursor:], p, True
        return buf, cursor, True
    if 32 <= ch <= 126:
        return buf[:cursor] + chr(ch) + buf[cursor:], cursor + 1, True
    return buf, cursor, False


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

MIN_COLS = 80


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


# -- Safe drawing helpers -----------------------------------------------------

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


# -- Splash screen ------------------------------------------------------------

_USC_LOGO = [
    "██    ██  ██████   ██████ ",
    "██    ██  ██       ██     ",
    "██    ██  ██████   ██     ",
    "██    ██       ██  ██     ",
    " ██████   ██████   ██████ ",
]


def draw_splash(stdscr, subtitle="MAVERIC Ground Station", config_lines=None):
    """Full-screen centered splash with USC logo in cardinal/gold.

    config_lines: optional list of strings shown below the GNURadio
                  reminder (e.g. ZMQ address, frequency).
    """
    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()

    if config_lines is None:
        config_lines = []

    # Block height:
    #   5 logo + 1 blank + ISI + SERC + 1 blank + subtitle
    #   + 1 blank + gnuradio warning
    #   + 1 blank + config lines
    #   + 1 blank + "Press any key"
    block_h = 10 + 2 + (len(config_lines) + 1 if config_lines else 0) + 2
    start_y = max(0, (max_y - block_h) // 2)

    cardinal = curses.color_pair(CP_USC_CARDINAL) | curses.A_BOLD
    gold = curses.color_pair(CP_USC_GOLD) | curses.A_BOLD
    dim = curses.color_pair(CP_DIM)
    warn = curses.color_pair(CP_WARNING) | curses.A_BOLD

    # USC block letters
    for i, line in enumerate(_USC_LOGO):
        col = max(0, (max_x - len(line)) // 2)
        _safe(stdscr, start_y + i, col, line, cardinal)

    # ISI + SERC + subtitle
    for offset, text, attr in [
        (6, "ISI", gold),
        (7, "Space Engineering Research Center", gold),
        (9, subtitle, dim),
    ]:
        col = max(0, (max_x - len(text)) // 2)
        _safe(stdscr, start_y + offset, col, text, attr)

    # GNURadio reminder
    row = start_y + 11
    gr_text = "!! Confirm GNURadio Flowgraph is running !!"
    col = max(0, (max_x - len(gr_text)) // 2)
    _safe(stdscr, row, col, gr_text, warn)

    # Config details
    if config_lines:
        row += 2
        for line in config_lines:
            col = max(0, (max_x - len(line)) // 2)
            _safe(stdscr, row, col, line, dim)
            row += 1

    # Press any key
    row += 1
    prompt = "Press any key to continue..."
    col = max(0, (max_x - len(prompt)) // 2)
    _safe(stdscr, row, col, prompt, dim | curses.A_BLINK)

    stdscr.refresh()
    stdscr.nodelay(False)
    stdscr.getch()
    curses.flushinp()
