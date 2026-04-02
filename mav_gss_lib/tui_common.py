"""
mav_gss_lib.tui_common -- Shared Textual TUI Utilities

Author:  Irfan Annuar - USC ISI SERC
"""

import os
import time
from datetime import datetime, timezone

from rich.align import Align
from rich.console import Group
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.events import Key
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Static

import mav_gss_lib.protocol as protocol

# -- Styles -------------------------------------------------------------------

S_LABEL   = Style(color="#00bfff", bold=True)    # Bright sky blue — labels
S_VALUE   = Style(color="#ffffff", bold=True)    # Pure white — primary data
S_SUCCESS = Style(color="#00ff87", bold=True)    # Bright green — active/ok
S_WARNING = Style(color="#ffd700", bold=True)    # Gold — caution/non-default
S_ERROR   = Style(color="#ff4444", bold=True)    # Bright red — errors/failures
S_DIM     = Style(color="#888888")               # Grey — secondary info
S_SEP     = Style(color="#707070")               # Mid grey — separators/col headers (4.1:1 contrast)
S_USC_CARDINAL = Style(color="#990000", bold=True)
S_USC_GOLD     = Style(color="#FFCC00", bold=True)

# Focus-aware widget title: cyan highlight when focused, white reverse when not
S_TITLE_FOCUSED  = "bold #000000 on #00bfff"
S_TITLE_DEFAULT  = "reverse bold #ffffff"

def title_style(has_focus):
    """Return the appropriate title style string based on widget focus state."""
    return S_TITLE_FOCUSED if has_focus else S_TITLE_DEFAULT

# -- Status duration constants ------------------------------------------------

STATUS_BRIEF   = 2   # quick toggles, confirmations
STATUS_NORMAL  = 3   # general status messages
STATUS_INFO    = 4   # protocol query results
STATUS_LONG    = 5   # errors, warnings, restored state
STATUS_STARTUP = 10  # schema warnings at startup

# -- Datetime format constants ------------------------------------------------

TS_FULL      = "%Y-%m-%d %H:%M:%S %Z"   # Full timestamp with timezone
TS_SHORT     = "%H:%M:%S"               # Time only (for compact display)
TS_UTC_LABEL = "%Y-%m-%d %H:%M:%S UTC"  # UTC timestamp for detail panels

# -- Color helpers ------------------------------------------------------------

_FRAME_COLORS = {"AX.25": "#6699cc", "ASM+GOLAY": "#55bbaa"}
_FRAME_DEFAULT = "#ff4444"

_PTYPE_COLORS = {
    "CMD": "#00D7FF",   # cyan  — operator-initiated
    "RES": "#00C853",   # green — nominal spacecraft reply
    "ACK": "#00BFA5",   # teal  — confirmation receipt
    "TLM": "#82B1FF",   # blue  — routine data stream
    "FILE": "#F48FB1",  # pink  — bulk transfer
}
_PTYPE_DEFAULT = "#E0E0E0"

def frame_color(frame_type):
    """Return color string for a frame type label."""
    return _FRAME_COLORS.get(frame_type, _FRAME_DEFAULT)

def ptype_color(ptype_id):
    """Return color string for a packet type ID."""
    name = protocol.PTYPE_NAMES.get(ptype_id, "")
    return _PTYPE_COLORS.get(name, _PTYPE_DEFAULT)

def node_color(node_id):
    """Return color string for a node — dim if NONE, blue otherwise."""
    return "#888888" if protocol.NODE_NAMES.get(node_id) == "NONE" else "#00bfff"

# -- Column width helper ------------------------------------------------------

def compute_col_widths(rows, extractors, defaults=None):
    """Compute dynamic column widths from visible rows.

    extractors: dict of {col_name: callable(row) -> iterable_of_strings}
    defaults:   dict of {col_name: int} for minimum widths
    Returns:    dict of {col_name: int}
    """
    defaults = defaults or {}
    collected = {k: set() for k in extractors}
    for row in rows:
        for k, fn in extractors.items():
            collected[k].update(fn(row))
    return {k: max((len(s) for s in vals), default=defaults.get(k, 1))
            for k, vals in collected.items()}


def hide_echo_if_all_none(col_widths, echo_values):
    """Hide echo column when all visible echoes are NONE (node 0)."""
    if all(protocol.NODE_NAMES.get(e) == "NONE" for e in echo_values):
        col_widths["echo"] = 0


# -- Shared layout helpers ----------------------------------------------------

def _build_item_text(label, value, style):
    """Build a Text fragment for a single header item.
    value can be a str or a pre-styled Text object (style is ignored for Text)."""
    t = Text()
    if label:
        t.append(f" {label}:", style=S_LABEL)
    else:
        t.append(" ")
    if isinstance(value, Text):
        t.append_text(value)
    else:
        t.append(value, style=style)
    return t

def _item_len(label, value):
    vlen = value.cell_len if isinstance(value, Text) else len(value)
    return len(f" {label}:") + vlen if label else 1 + vlen


def build_header(title, title_style, items, w, right_items=None):
    """Build a wrapping header: title row with clocks, separator, then flowing info items.

    items:       list of (label, value, value_style) — flowed left-to-right, wrapping as needed.
    right_items: list of (label, value, value_style) — right-aligned on the last info row.
    Returns (Text, row_count)."""
    utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    t = Text()
    title_text = Text()
    title_text.append(f" {title} ", style="reverse bold #ffffff")
    t.append_text(lr_line(title_text,
                           Text(f"{utc} UTC  {local} ", style=S_VALUE), w))
    t.append("\n" + "─" * w, style=S_SEP)
    rows = 2  # title + separator

    right_items = right_items or []

    # Measure left items
    chunks = [(l, v, s, _item_len(l, v)) for l, v, s in items]

    # Flow left items into rows, reserving space for right_items on the last row
    item_rows = []
    col, row_idx = 0, 0
    for i, (label, value, style, clen) in enumerate(chunks):
        if col > 0 and col + clen > w:
            col, row_idx = 0, row_idx + 1
        item_rows.append(row_idx)
        col += clen
    num_info_rows = row_idx + 1

    # If all left items fit on 1 row but we have 2+, split across 2 rows
    if num_info_rows == 1 and len(chunks) >= 2:
        total = sum(c[3] for c in chunks)
        best_split, best_diff = 1, total
        running = 0
        for i in range(len(chunks) - 1):
            running += chunks[i][3]
            diff = abs(running - (total - running))
            if diff < best_diff:
                best_diff, best_split = diff, i + 1
        item_rows = [0 if i < best_split else 1 for i in range(len(chunks))]
        num_info_rows = 2

    # Render left items row by row, right-align right_items on the last row
    last_row = max(item_rows) if item_rows else 0
    cur_row = -1
    for i, (label, value, style, clen) in enumerate(chunks):
        if item_rows[i] != cur_row:
            if cur_row == last_row and right_items:
                right_items = []
            t.append("\n")
            cur_row = item_rows[i]
            rows += 1
        t.append_text(_build_item_text(label, value, style))

    # Right-align right_items on the last info row
    if right_items:
        right_text = Text()
        for l, v, s in right_items:
            right_text.append_text(_build_item_text(l, v, s))
        right_text.append(" ")
        # Calculate how much left content is on the current (last) row
        last_row_left = sum(c[3] for i, c in enumerate(chunks) if item_rows[i] == cur_row) if chunks else 0
        pad = w - last_row_left - right_text.cell_len
        if pad > 0:
            t.append(" " * pad)
        elif pad < 0:
            # Right items don't fit on last row — put them on their own row
            t.append("\n")
            rows += 1
            pad = w - right_text.cell_len
            if pad > 0:
                t.append(" " * pad)
        t.append_text(right_text)

    # Pad to minimum 2 info rows (4 total including title + separator)
    while rows < 4:
        t.append("\n")
        rows += 1

    return t, rows


def lr_line(left, right, w, fill_style=""):
    """Build a single Text line: left + right, right-aligned, exactly w chars wide.

    Truncates LEFT (not right) when content overflows, preserving status badges.
    """
    right_len = right.cell_len
    left_budget = w - right_len
    line = Text(no_wrap=True, overflow="crop")
    if left_budget > 0:
        if left.cell_len > left_budget:
            left.truncate(left_budget)
        line.append_text(left)
        pad = w - line.cell_len - right_len
        if pad > 0:
            line.append(" " * pad, style=fill_style)
    line.append_text(right)
    # Fill remaining width (ensures highlight covers entire row)
    remaining = w - line.cell_len
    if remaining > 0:
        line.append(" " * remaining, style=fill_style)
    line.truncate(w)
    return line


def flash_phase():
    """Return True/False alternating at 500ms intervals for blink animations."""
    return int(time.time() * 1000 / 500) % 2 == 0

S_SCROLLBAR_THUMB = Style(bgcolor="#666666")  # lighter grey — thumb (visible area)
S_SCROLLBAR_TRACK = Style(bgcolor="#222222")  # darker grey — track (background)

def scrollbar_styles(total, visible, offset, height):
    """Return a list of height Style objects for a vertical scrollbar track.

    Returns empty list when content fits (total <= visible).
    Uses background-colored spaces for a continuous solid look.
    """
    if total <= visible or height <= 0:
        return []
    thumb_size = max(1, round(visible / total * height))
    max_offset = total - visible
    thumb_start = round(offset / max_offset * (height - thumb_size)) if max_offset > 0 else 0
    return [S_SCROLLBAR_THUMB if thumb_start <= i < thumb_start + thumb_size else S_SCROLLBAR_TRACK
            for i in range(height)]


def append_wrapped_args(t, args, indent, style, row_w, sb=None, sb_idx=0):
    """Append args as continuation lines aligned at indent. Returns new sb_idx."""
    # Cap indent so wrapped content gets at least 1/3 of the row width
    max_indent = max(2, (row_w * 2) // 3)
    indent = min(indent, max_indent)
    cont_w = max(1, row_w - indent)
    for ci in range(0, len(args), cont_w):
        t.append("\n")
        cont = Text()
        cont.append(" " * indent, style="")
        cont.append(args[ci:ci + cont_w], style=style)
        if sb and sb_idx < len(sb):
            pad_needed = row_w - cont.cell_len
            if pad_needed > 0:
                cont.append(" " * pad_needed)
            cont.append(" ", style=sb[sb_idx])
        t.append_text(cont)
        sb_idx += 1
    return sb_idx


class ScrollableWidget(Widget):
    """Base for focusable, scrollable list widgets with mouse wheel + keyboard."""
    can_focus = True

    def _scroll_by(self, delta):
        raise NotImplementedError

    def on_click(self, event): self.focus()
    def on_mouse_scroll_up(self, event): self._scroll_by(-3)
    def on_mouse_scroll_down(self, event): self._scroll_by(3)

    def on_key(self, event: Key):
        k = event.key
        if k == "up": self._scroll_by(-1); event.prevent_default()
        elif k == "down": self._scroll_by(1); event.prevent_default()
        elif k == "pageup": self._scroll_by(-max(1, self.content_size.height - 3)); event.prevent_default()
        elif k == "pagedown": self._scroll_by(max(1, self.content_size.height - 3)); event.prevent_default()


class MavAppBase(App):
    """Shared base class for MavRxApp and MavTxApp.

    Provides config screen toggling, help panel, common key bindings,
    tick-driven widget refresh, input submission dispatch, and cleanup hooks.
    Subclasses implement _dispatch(), _open_config(), and _cleanup().
    """
    ENABLE_COMMAND_PALETTE = False
    _WIDGET_QUERY = ""
    _INPUT_ID = ""

    def on_click(self, event):
        w = event.widget if hasattr(event, "widget") else None
        while w is not None and not getattr(w, "can_focus", False):
            w = w.parent
        if w is not None and w is not self:
            w.focus()

    def _act(self):
        for w in self.query(self._WIDGET_QUERY):
            if w.display:
                w.refresh()

    def _dispatch(self, line): raise NotImplementedError
    def _pre_dispatch(self, line): pass
    def _handle_result(self, result): return False
    def _open_config(self): raise NotImplementedError
    def _cleanup(self): pass

    def on_input_submitted(self, event):
        if event.input.id != self._INPUT_ID: return
        from textual.widgets import Input
        line = event.value.strip()
        self.query_one(f"#{self._INPUT_ID}", Input).value = ""
        if not line: return
        self._pre_dispatch(line)
        result = self._dispatch(line)
        if result == "break": self._cleanup(); self.exit(); return
        if result == "restart": self._cleanup(); self.exit(result="restart"); return
        if result == "open_config": self._open_config(); return
        if self._handle_result(result): return
        self._act()


def dispatch_common(state, cmd):
    """Handle commands shared between RX and TX.
    Returns 'break', 'open_config', True (handled), or None (not recognized)."""
    if cmd in ('q', 'quit', 'exit'): return "break"
    if cmd == 'help': state.help_open = not getattr(state, 'help_open', False); return True
    if cmd in ('cfg', 'config'): state.help_open = False; return "open_config"
    if cmd.startswith('tag '): return ("tag", cmd[4:])
    if cmd == 'tag': return ("tag", "")
    if cmd.startswith('log '): return ("log", cmd[4:])
    if cmd == 'log': return ("log", "")
    if cmd == 'restart': return "restart"
    if cmd == 'hclear': return None  # data differs per app, let subclass handle
    return None


class Hints(Widget):
    """Single-line hint bar docked at bottom."""
    DEFAULT_CSS = "Hints { height: 1; width: 100%; }"
    def __init__(self, text, **kw):
        super().__init__(**kw)
        self._text = text
    def render(self):
        return Text(self._text, style=S_DIM, no_wrap=True, overflow="ellipsis")


class HelpPanel(Widget):
    """Side panel showing help lines. Parameterized with data at construction."""
    DEFAULT_CSS = "HelpPanel { width: auto; max-width: 50%; dock: right; display: none; border-left: solid #555555; border-top: solid #555555; }"
    def __init__(self, state, help_lines, hint, get_info, **kw):
        super().__init__(**kw)
        self.s, self._lines, self._hint, self._get_info = state, help_lines, hint, get_info
    def render(self):
        return render_help_panel(self._lines, self._hint, *self._get_info(self.s))


class ConfigScreen(ModalScreen):
    """Modal config screen — owns all keyboard input until dismissed.

    fields: (label, key, editable) tuples — True=text, "toggle"=on/off,
    ("cycle", [...])=cycle through list on Enter, False=readonly.
    Dismisses with the edited values dict. Inline cursor editing for text fields.
    """
    CSS = """
    ConfigScreen { align: right top; background: black 50%; }
    #cfg-box { width: auto; max-width: 50%; height: 100%; dock: right;
               border-left: solid #555555; border-top: solid #555555; background: black; }
    """

    def __init__(self, fields, values):
        super().__init__()
        self._all_fields, self._values = fields, dict(values)
        self._sel, self._editing = 0, False
        self._buf, self._cur = "", 0
        self._rebuild_visible()

    def _rebuild_visible(self):
        """Rebuild visible field list based on current values. Fields with a 4th
        element (callable) are only shown when that callable returns True."""
        old_key = self._fields[self._sel][1] if hasattr(self, '_fields') and self._fields else None
        self._fields = [f for f in self._all_fields
                        if len(f) < 4 or f[3](self._values)]
        # Try to preserve selection by key
        if old_key:
            for i, f in enumerate(self._fields):
                if f[1] == old_key:
                    self._sel = i; return
        self._sel = min(self._sel, max(0, len(self._fields) - 1))

    def compose(self) -> ComposeResult:
        yield Static(id="cfg-box")

    def on_mount(self):
        self._refresh()

    def _refresh(self):
        t = Text()
        t.append(" CONFIGURATION\n", style=S_LABEL)
        for i, field in enumerate(self._fields):
            label, key, editable = field[0], field[1], field[2]
            sel = (i == self._sel)
            t.append("▶ " if sel else "  ", style=S_VALUE if sel else S_DIM)
            t.append(f"{label:<18}", style=S_LABEL if editable else S_DIM)
            if sel and self._editing:
                before, after = self._buf[:self._cur], self._buf[self._cur:]
                t.append(before, style=S_VALUE)
                t.append(after[0] if after else " ", style="reverse")
                if len(after) > 1: t.append(after[1:], style=S_VALUE)
            else:
                val = str(self._values.get(key, ""))
                is_cycle = isinstance(editable, tuple) and editable[0] == "cycle"
                if editable == "toggle":
                    vs = S_VALUE if val == "ON" else S_DIM
                elif is_cycle:
                    styles = editable[2] if len(editable) > 2 else {}
                    display_labels = editable[3] if len(editable) > 3 else {}
                    val = display_labels.get(val, val)
                    vs = styles.get(self._values.get(key, ""), S_VALUE)
                elif not editable:
                    vs = S_DIM
                elif sel:
                    vs = Style(color="#ffffff", bold=True, underline=True)
                else:
                    vs = S_VALUE
                t.append(val, style=vs)
            t.append("\n")
        hint = " Enter:save  Esc:cancel" if self._editing else " ↑↓:select  Enter:edit  Esc:close & save"
        t.append(f"\n\n{hint}", style=S_DIM)
        self.query_one("#cfg-box", Static).update(t)

    def on_key(self, event: Key):
        k, ch = event.key, event.character
        if self._editing:
            if k == "enter":
                key = self._fields[self._sel][1]
                self._values[key] = self._buf; self._editing = False
            elif k == "escape": self._editing = False
            elif ch and ch.isprintable():
                self._buf = self._buf[:self._cur] + ch + self._buf[self._cur:]; self._cur += 1
            elif k == "backspace" and self._cur > 0:
                self._buf = self._buf[:self._cur-1] + self._buf[self._cur:]; self._cur -= 1
            elif k == "delete" and self._cur < len(self._buf):
                self._buf = self._buf[:self._cur] + self._buf[self._cur+1:]
            elif k == "left": self._cur = max(0, self._cur - 1)
            elif k == "right": self._cur = min(len(self._buf), self._cur + 1)
            elif k == "home": self._cur = 0
            elif k == "end": self._cur = len(self._buf)
        elif k == "up": self._sel = (self._sel - 1) % len(self._fields)
        elif k == "down": self._sel = (self._sel + 1) % len(self._fields)
        elif k == "enter":
            key, editable = self._fields[self._sel][1], self._fields[self._sel][2]
            is_cycle = isinstance(editable, tuple) and editable[0] == "cycle"
            if editable == "toggle":
                v = self._values.get(key, "OFF")
                self._values[key] = "OFF" if v == "ON" else "ON"
            elif is_cycle:
                choices = editable[1]
                cur = self._values.get(key, choices[0])
                idx = choices.index(cur) if cur in choices else 0
                self._values[key] = choices[(idx + 1) % len(choices)]
                self._rebuild_visible()
            elif editable:
                self._editing = True
                self._buf = str(self._values.get(key, "")); self._cur = len(self._buf)
        elif k == "escape":
            self.dismiss(self._values)
            event.stop(); return
        event.stop(); event.prevent_default(); self._refresh()


class ImportScreen(ModalScreen):
    """Modal file picker for generated_commands/."""
    CSS = """
    ImportScreen { align: center middle; background: black 60%; }
    #imp-box { width: auto; min-width: 40; height: auto; border: solid #555555;
               background: black; padding: 1 2; }
    """
    def __init__(self, files):
        super().__init__()
        self._files, self._sel = files, 0
    def compose(self) -> ComposeResult:
        yield Static(id="imp-box")
    def on_mount(self): self._refresh()
    def _refresh(self):
        t = Text()
        t.append(" IMPORT FILE\n\n", style=S_LABEL)
        for i, f in enumerate(self._files):
            sel = (i == self._sel)
            t.append("▶ " if sel else "  ", style=S_VALUE if sel else S_DIM)
            t.append(f + "\n", style="bold #ffffff" if sel else S_VALUE)
        t.append("\n ↑↓:select  Enter:import  Esc:cancel", style=S_DIM)
        self.query_one("#imp-box", Static).update(t)
    def on_key(self, event: Key):
        k = event.key
        if k == "up": self._sel = (self._sel - 1) % len(self._files)
        elif k == "down": self._sel = (self._sel + 1) % len(self._files)
        elif k == "enter": self.dismiss(self._files[self._sel]); event.stop(); return
        elif k == "escape": self.dismiss(None); event.stop(); return
        event.stop(); event.prevent_default(); self._refresh()


class ConfirmScreen(ModalScreen):
    """Modal confirmation dialog — Enter to confirm, Escape to cancel.

    Uses a semi-transparent overlay so the TX queue remains visible
    behind the dialog, following spacecraft ops "see what you're commanding".

    Set destructive=True for irreversible actions (clear, delete) —
    uses red border and red action button so the modal is visually
    distinct from routine confirmations (NASA-HFDS 8.5.1).

    Optional detail lines provide extra context (e.g. command routing, args).
    """
    CSS = """
    ConfirmScreen { align: center middle; background: black 40%; }
    #confirm-box { width: auto; min-width: 40; height: auto;
                   border: solid #555555; background: black; padding: 1 3; }
    """

    def __init__(self, message, action_label="Confirm", *, destructive=False, details=None, content=None):
        super().__init__()
        self._message = message
        self._action_label = action_label
        self._destructive = destructive
        self._details = details or []
        self._content = content

    def compose(self):
        yield Static(id="confirm-box")

    def on_mount(self):
        self._refresh()

    def _refresh(self):
        t = Text(justify="center")
        box = self.query_one("#confirm-box", Static)
        if self._destructive:
            t.append(f"⚠ {self._message}\n", style=S_ERROR)
            box.styles.border = ("solid", "#cc0000")
        else:
            t.append(f"{self._message}\n", style=S_LABEL)
            box.styles.border = ("solid", "#00bfff")
        if self._content:
            t.append("\n")
            t.append_text(self._content)
            t.append("\n")
        if self._details:
            t.append("\n")
            for lbl, val in self._details:
                t.append(f"  {lbl:<12}", style=S_DIM)
                t.append(f"{val}\n", style=S_VALUE)
        t.append("\n")
        if self._destructive:
            t.append(f" Enter:{self._action_label} ", style="bold #ffffff on #cc0000")
        else:
            t.append(f" Enter:{self._action_label} ", style="bold #000000 on #00ff87")
        t.append("  ")
        t.append(" Esc:Cancel ", style="bold #000000 on #888888")
        box.update(t)

    def on_key(self, event):
        if event.key == "enter":
            self.dismiss(True)
        elif event.key == "escape":
            self.dismiss(False)
        event.stop(); event.prevent_default()


# -- Status message -----------------------------------------------------------

class StatusMessage:
    """Transient status message with auto-expiry for the TUI status bar.

    Thread-safe: state is a single tuple replaced atomically (one
    STORE_ATTR under CPython's GIL), so concurrent reads from the UI
    thread and writes from background threads cannot tear.
    """
    __slots__ = ("_state",)
    def __init__(self, text="", duration=0):
        self._state = (text, time.time() + duration) if text else ("", 0)
    def set(self, text, duration=3):
        self._state = (text, time.time() + duration)
    def clear(self):
        self._state = ("", 0)
    def check_expiry(self):
        text, expire = self._state
        if text and time.time() >= expire:
            self._state = ("", 0)
            return True
        return False
    @property
    def text(self):
        return self._state[0]
    def __bool__(self):
        return bool(self._state[0])

# -- Splash screen ------------------------------------------------------------

_LOGO = [
    "██    ██  ██████   ██████ ",
    "██    ██  ██       ██     ",
    "██    ██  ██████   ██     ",
    "██    ██       ██  ██     ",
    " ██████   ██████   ██████ ",
]

class SplashScreen(ModalScreen):
    """Full-screen splash showing USC logo, config summary, and GNU Radio reminder."""
    DEFAULT_CSS = """
    SplashScreen { align: center middle; }
    #splash-content { width: 100%; height: auto; padding: 1 2; text-align: center; }
    """
    BINDINGS = [("any", "dismiss_splash", "Continue")]

    def __init__(self, subtitle="MAVERIC Ground Station", config_lines=None):
        super().__init__()
        self._subtitle = subtitle
        self._config_lines = config_lines or []

    def compose(self) -> ComposeResult:
        yield Static(id="splash-content")

    def on_mount(self):
        serc = "Space Engineering Research Center"
        box_content = [serc, self._subtitle] + _LOGO
        inner_w = max(len(s) for s in box_content) + 4

        def center(txt, w):
            p = w - len(txt)
            return " " * (p // 2) + txt + " " * (p - p // 2)

        t = Text()
        logo_w = max(len(l.rstrip()) for l in _LOGO)
        def row(content="", style=S_USC_GOLD):
            t.append("║", style=S_USC_GOLD)
            t.append(center(content, inner_w) if content else " " * inner_w, style=style)
            t.append("║\n", style=S_USC_GOLD)
        t.append("╔" + "═" * inner_w + "╗\n", style=S_USC_GOLD)
        row()
        for line in _LOGO:
            row(line.rstrip().ljust(logo_w), S_USC_CARDINAL)
        row()
        row("ISI", S_USC_GOLD)
        row(serc, S_USC_GOLD)
        row()
        row(self._subtitle, S_DIM)
        t.append("╚" + "═" * inner_w + "╝", style=S_USC_GOLD)
        parts = [Align.center(t)]
        parts.append(Text("\n!! Confirm GNU Radio MAV_DUPLEX Flowgraph is running !!\n",
                          justify="center", style=S_WARNING))
        if self._config_lines:
            lw = max(len(l) for l, _ in self._config_lines)
            cfg = Table.grid(padding=(0, 0, 0, 0))
            cfg.add_column(width=lw, style=S_DIM)
            cfg.add_column(width=2)
            cfg.add_column(style=S_DIM)
            for label, val in self._config_lines:
                cfg.add_row(Text(label), Text("  "), Text(val))
            parts.append(Align.center(cfg))
        parts.append(Text("\nPress any key to continue...", justify="center", style=S_DIM))
        self.query_one("#splash-content", Static).update(Group(*parts))

    def on_key(self, event):
        event.stop(); event.prevent_default()
        self.dismiss()

    def action_dismiss_splash(self):
        self.dismiss()

# -- Shared panel renderers ---------------------------------------------------

def render_help_panel(help_lines, hint, version="", schema_count=0,
                      schema_path="", log_path=""):
    """Render the help panel Rich Text from help_lines data and session info."""
    t = Text()
    t.append(" HELP\n", style=S_LABEL)
    for left, right in help_lines:
        if right is None:
            t.append(f" {left}\n", style=S_LABEL)
        elif left == "":
            t.append("\n")
        else:
            t.append(f"  {left:<20}", style=S_VALUE)
            t.append(f"{right}\n", style=S_DIM)
    t.append("\n")
    if version:
        t.append(f"  {'Version':<20}", style=S_VALUE)
        t.append(f"{version}\n", style=S_DIM)
    if schema_count > 0:
        t.append(f"  {'Schema':<20}", style=S_VALUE)
        t.append(f"{schema_count} cmds ({os.path.basename(schema_path)})\n", style=S_DIM)
    if log_path:
        t.append(f"  {'Log':<20}", style=S_VALUE)
        t.append(f"{os.path.basename(log_path)}\n", style=S_DIM)
    t.append(f"\n {hint}", style=S_DIM)
    return t


