"""
mav_gss_lib.curses_common -- Shared Curses Utilities

Color pairs, safe drawing helpers, and splash screen shared by both
the TX dashboard (curses_tx) and the RX monitor (curses_rx).

Author:  Irfan Annuar - USC ISI SERC
"""

import curses


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


def draw_splash(stdscr, subtitle="MAVERIC Ground Station"):
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
        (9, subtitle, curses.color_pair(CP_DIM)),
    ]:
        col = max(0, (max_x - len(text)) // 2)
        _safe(stdscr, start_y + offset, col, text, attr)

    stdscr.refresh()
    curses.napms(2000)
    curses.flushinp()
