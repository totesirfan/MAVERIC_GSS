"""
mav_gss_lib.tui_tx -- TX Dashboard Widgets (Textual)

Author:  Irfan Annuar - USC ISI SERC
"""

import time

from rich.style import Style
from rich.text import Text
from mav_gss_lib.tui_common import Widget, ScrollableWidget

import mav_gss_lib.protocol as protocol
from mav_gss_lib.protocol import node_label
from mav_gss_lib.tui_common import (
    S_LABEL, S_VALUE, S_SUCCESS, S_WARNING, S_ERROR, S_DIM, S_SEP, lr_line,
    scrollbar_styles, append_wrapped_args, build_header, build_col_hdr,
    build_cmd_columns, flash_phase,
    TS_SHORT, ptype_color, node_color, compute_col_widths, title_style, title_fill,
    hide_echo_if_all_none,
)


def _cmd_col_widths(items, num_fn):
    """Compute column widths for command/record rows.
    num_fn: callable(row) -> display string for the number column (including '#' prefix)."""
    result = compute_col_widths(items, {
        "num": lambda row: [f"#{num_fn(row)}"],
        "src": lambda row: [node_label(row.get("src", protocol.GS_NODE))],
        "dest": lambda row: [node_label(row["dest"])],
        "echo": lambda row: [node_label(row["echo"])],
        "ptype": lambda row: [protocol.PTYPE_NAMES.get(row["ptype"], str(row.get("ptype", "?")))],
    }, defaults={"num": 1, "src": 3, "dest": 4, "echo": 4, "ptype": 4})
    hide_echo_if_all_none(result, [row["echo"] for row in items])
    return result


class TxHeader(Widget):
    """Header bar showing ZMQ status, frequency, uplink mode, log state, and clocks.
    Wraps info items to next row when terminal is too narrow."""
    DEFAULT_CSS = "TxHeader { height: auto; width: 100%; dock: top; }"

    def __init__(self, state, **kw):
        super().__init__(**kw)
        self.s = state

    def render(self):
        s, w = self.s, self.content_size.width
        if s.zmq_status == "ONLINE":
            zmq_style = S_SUCCESS
        else:
            zmq_style = "reverse bold #ff4444" if flash_phase() else "on #330000 bold #ff4444"
        mode_style = Style(color="#55bbaa", bold=True) if s.uplink_mode == "ASM+Golay" else Style(color="#6699cc", bold=True)
        mode_label = "ASM+GOLAY" if s.uplink_mode == "ASM+Golay" else s.uplink_mode
        zmq_val = Text()
        zmq_val.append(s.zmq_addr_disp, style=S_VALUE)
        zmq_val.append(" ")
        zmq_val.append(f"[{s.zmq_status}]", style=zmq_style)
        items = [
            ("ZMQ", zmq_val, None),
            ("Mode", mode_label, mode_style),
        ]
        if not s.csp.csp_crc:
            items.append(("", "NO CRC", Style(color="#ff6666", bold=True)))
        t, _ = build_header("MAVERIC UPLINK", S_LABEL, items, w)
        return t


class TxQueue(ScrollableWidget):
    """Scrollable TX queue with typed items (cmd and delay). Each item = one row."""
    DEFAULT_CSS = "TxQueue { height: 2fr; width: 100%; } TxQueue:focus { border: solid #00bfff; }"

    def __init__(self, state, **kw):
        super().__init__(**kw)
        self.s = state
        self._editing = False
        self._edit_buf = ""

    def _vis_rows(self):
        return max(1, self.content_size.height - 4)  # title + hdr + blank + total

    def _scroll_by(self, delta):
        s = self.s
        count = len(s.tx_queue)
        vis = self._vis_rows()
        delta = -delta  # reversed display: next-to-send at bottom
        if self.has_focus and not s.sending["active"]:
            s.queue_sel = max(0, min(count - 1, s.queue_sel + delta))
            if s.queue_sel < s.queue_scroll:
                s.queue_scroll = s.queue_sel
            elif s.queue_sel >= s.queue_scroll + vis:
                s.queue_scroll = s.queue_sel - vis + 1
        else:
            s.queue_scroll = max(0, min(count - vis, s.queue_scroll + delta))
        self.refresh()

    def on_key(self, event):
        k = event.key
        s = self.s
        count = len(s.tx_queue)
        if self._editing:
            event.prevent_default()
            if k == "escape":
                self._editing = False; self.refresh()
            elif k == "enter":
                try: val = max(0, int(self._edit_buf)) if self._edit_buf else 0
                except ValueError: val = 0
                if 0 <= s.queue_sel < count and s.tx_queue[s.queue_sel]["type"] == "delay":
                    s.tx_queue[s.queue_sel]["delay_ms"] = val
                    s._queue_dirty = True; s._queue_save = True
                self._editing = False; self.refresh()
            elif k == "backspace":
                self._edit_buf = self._edit_buf[:-1]; self.refresh()
            elif len(k) == 1 and k.isdigit():
                self._edit_buf += k; self.refresh()
            return
        if not s.sending["active"] and 0 <= s.queue_sel < count:
            item = s.tx_queue[s.queue_sel]
            if k == "enter" and item["type"] == "delay":
                self._editing = True
                self._edit_buf = str(item["delay_ms"])
                event.prevent_default(); self.refresh(); return
            if k == "space" and item["type"] == "cmd":
                item["guard"] = not item.get("guard", False)
                s._queue_dirty = True; s._queue_save = True
                event.prevent_default(); self.refresh(); return
            if k in ("delete", "backspace"):
                s.tx_queue.pop(s.queue_sel)
                if s.queue_sel >= len(s.tx_queue):
                    s.queue_sel = max(0, len(s.tx_queue) - 1)
                s._queue_dirty = True; s._queue_save = True
                event.prevent_default(); self.refresh(); return
            if k == "w":
                s.tx_queue.insert(s.queue_sel + 1, {"type": "delay", "delay_ms": s.tx_delay_ms})
                s._queue_dirty = True; s._queue_save = True
                s.queue_sel += 1  # move to the new delay
                event.prevent_default(); self.refresh(); return
        super().on_key(event)

    def on_focus(self, event):
        s = self.s
        if s.queue_sel < 0 and s.tx_queue:
            s.queue_sel = 0; s.queue_scroll = 0
        self.refresh()

    def on_blur(self, event):
        self._editing = False; self.refresh()

    def render(self):
        s, w, h = self.s, self.content_size.width, self.content_size.height
        q, count = s.tx_queue, len(s.tx_queue)
        t = Text(no_wrap=True, overflow="crop")
        vis = self._vis_rows()
        # Title
        cmd_count = sum(1 for item in q if item["type"] == "cmd")
        title = Text()
        tf = self.has_focus
        title.append(f" TX QUEUE ({cmd_count}) ", style=title_style(tf))
        right = Text(f"[{s.queue_scroll+1}-{min(s.queue_scroll+vis,count)}/{count}] ", style=S_DIM) if count > vis else Text()
        t.append_text(lr_line(title, right, w))
        # Scroll (reversed display: next-to-send at bottom)
        if count > 0:
            sending_active = s.sending["active"]
            if sending_active:
                s.queue_scroll = 0  # next-to-send at bottom
            elif not self.has_focus and s.queue_sel < 0:
                s.queue_scroll = 0
            s.queue_scroll = max(0, min(s.queue_scroll, max(0, count - vis)))
            visible = q[s.queue_scroll:s.queue_scroll + vis]
            cmd_items = [item for item in visible if item["type"] == "cmd"]
            nums = {id(row): i + 1 for i, row in enumerate(cmd_items)}
            col_w = _cmd_col_widths(cmd_items, lambda r: nums[id(r)])
            has_non_gs_src = any(item.get("src", protocol.GS_NODE) != protocol.GS_NODE for item in cmd_items)
            sb = scrollbar_styles(count, vis, s.queue_scroll, vis) if count > vis else []
            visible = list(reversed(visible))
            if sb: sb = list(reversed(sb))
        else:
            visible, col_w = [], _cmd_col_widths([], lambda r: "")
            has_non_gs_src, sb = False, []
        row_w = w - 1 if sb else w
        hdr, hdr_right = build_col_hdr(col_w, has_non_gs_src=has_non_gs_src)
        t.append("\n"); t.append_text(lr_line(hdr, hdr_right, row_w))
        if count == 0:
            t.append("\n  (empty — type a command below)", style=S_DIM)
            return t
        sending_idx = s.sending["idx"] if s.sending["active"] else -1
        guarding = s.sending.get("guarding", False) if s.sending["active"] else False
        focused = self.has_focus and not s.sending["active"]
        n_vis = len(visible)
        t_ms = sum(item["delay_ms"] for item in q if item["type"] == "delay")
        # Bottom-align: pad above items so they anchor to the bottom
        content_rows = n_vis + (1 if t_ms > 0 else 0)
        pad = max(0, h - 2 - content_rows)
        for _ in range(pad):
            t.append("\n")
        for i, item in enumerate(visible):
            ai = s.queue_scroll + (n_vis - 1 - i)  # reversed display
            is_sel = focused and ai == s.queue_sel
            is_next = (ai == 0)
            if item["type"] == "cmd":
                cmd_num = item.get("num", ai + 1)
                self._render_cmd(t, item, ai, cmd_num, is_sel, is_next, sending_idx, guarding,
                                 col_w, has_non_gs_src, row_w, sb, i, s)
            else:
                self._render_delay(t, item, ai, is_sel, sending_idx, guarding, row_w, sb, i, s)
        if t_ms > 0:
            total_str = f"{t_ms/1000:.1f}s"
            t.append("\n"); t.append_text(lr_line(Text(), Text(f"Σ {total_str} ", style=S_DIM), row_w))
        return t

    def _render_cmd(self, t, item, ai, cmd_num, is_sel, is_next, sending_idx, guarding,
                    col_w, has_non_gs_src, row_w, sb, vi, s):
        """Render a command row."""
        sent_at = s.sending.get("sent_at", 0.0)
        is_current = sending_idx >= 0 and ai == sending_idx
        in_flash = is_current and sent_at > 0 and time.time() - sent_at < 1.0
        if is_current and guarding:
            flash = flash_phase()
            b = "reverse bold #ffd700" if flash else "on #332b00 bold #ffd700"
            tag, ts, uniform = " GUARD", b, True
        elif in_flash:
            flash = flash_phase()
            b = "reverse bold #00ff87" if flash else "on #003300 bold #00ff87"
            tag, ts, uniform = " SENT", b, True
        elif is_sel:
            b, tag, ts, uniform = "reverse bold", "", "", False
        elif is_next:
            b, tag, ts, uniform = "on #1a1a1a", "", "", False
        else:
            b, tag, ts, uniform = "", "", "", False
        left = Text(style=b)
        args_indent = build_cmd_columns(left, col_w, num_str=f"#{cmd_num}",
            src=item["src"], dest=item["dest"], echo=item["echo"],
            ptype_id=item["ptype"], cmd_name=item["cmd"],
            has_non_gs_src=has_non_gs_src, b=b, uniform=uniform)
        args_style = b if uniform else (f"{b} #ffffff" if b != "#888888" else b)
        # Right side
        right_parts = Text()
        if is_next and not tag:
            right_parts.append(" NEXT ", style="bold #000000 on #ffffff")
        if item.get("guard") and "SENT" not in tag and "GUARD" not in tag:
            right_parts.append(" GUARDED ", style="bold #000000 on #ffd700")
        if tag:
            right_parts.append(f"{tag}  ", style=ts)
        size_style = ts if tag else (f"{b} #555555" if is_sel else f"{b} #999999")
        right_parts.append(f" {len(item['raw_cmd'])}B ", style=size_style)
        pending_args = None
        if item["args"]:
            avail = row_w - left.cell_len - right_parts.cell_len
            if avail >= len(item["args"]):
                left.append(item["args"], style=args_style)
            else:
                pending_args = item["args"]
        t.append("\n")
        line = lr_line(left, right_parts, row_w, fill_style=b)
        if sb and vi < len(sb): line.append(" ", style=sb[vi])
        t.append_text(line)
        if pending_args:
            append_wrapped_args(t, pending_args, args_indent, args_style, row_w)

    def _render_delay(self, t, item, ai, is_sel, sending_idx, guarding, row_w, sb, vi, s):
        """Render a delay separator row."""
        delay_ms = item["delay_ms"]
        editing = is_sel and self._editing
        delay_end = s.sending.get("delay_end", 0.0)
        waiting = s.sending.get("waiting", False)
        is_current = sending_idx >= 0 and ai == sending_idx
        counting = is_current and waiting and delay_end > 0
        delay_s = f"{delay_ms / 1000:.1f}s"
        if editing:
            label = f" [{self._edit_buf}_]ms "
            dstyle = S_LABEL
        elif counting:
            flash = flash_phase()
            remaining = max(0, delay_end - time.time())
            label = f" {remaining:.1f}s "
            dstyle = "reverse bold #00ff87" if flash else "on #003300 bold #00ff87"
        elif is_sel:
            label = f" {delay_s} "
            dstyle = "reverse bold"
        else:
            label = f" {delay_s} "
            dstyle = "bold #000000 on #aaaaaa"
        lw = len(label)
        center = (row_w - lw) // 2
        line_style = S_DIM
        sep = Text()
        sep.append("─" * center, style=line_style)
        sep.append(label, style=dstyle)
        sep.append("─" * max(0, row_w - center - lw), style=line_style)
        t.append("\n")
        final = lr_line(sep, Text(), row_w)
        if sb and vi < len(sb): final.append(" ", style=sb[vi])
        t.append_text(final)


class SentHistory(ScrollableWidget):
    """Scrollable log of previously sent commands with timestamps and byte sizes."""
    DEFAULT_CSS = "SentHistory { height: 1fr; width: 100%; } SentHistory:focus { border: solid #00bfff; }"

    def __init__(self, state, **kw):
        super().__init__(**kw)
        self.s = state

    def _scroll_by(self, delta):
        s = self.s
        count = len(s.history)
        data_rows = max(1, self.content_size.height - 3)
        s.hist_scroll = max(min(data_rows - 1, count - 1), min(count - 1, max(0, s.hist_scroll + delta)))
        self.refresh()

    def render(self):
        s, w, h = self.s, self.content_size.width, self.content_size.height
        hist, count = s.history, len(s.history)
        t = Text(no_wrap=True, overflow="crop")
        title = Text()
        tf = self.has_focus
        title.append(f" SENT HISTORY ({count}) ", style=title_style(tf))
        data_rows = h - 1
        # Compute visible slice first so header and data share same col widths
        data_rows -= 2  # col header + blank line between title and data
        if count > 0:
            if not self.has_focus:
                s.hist_scroll = count - 1
            end = min(s.hist_scroll + 1, count)
            start = max(0, end - data_rows)
            visible = hist[start:end]
            col_w = _cmd_col_widths(visible, lambda r: r['n'])
            has_non_gs_src = any(rec.get('src', protocol.GS_NODE) != protocol.GS_NODE for rec in visible)
            sb = scrollbar_styles(count, data_rows, start, data_rows) if count > data_rows else []
        else:
            visible, start, end = [], 0, 0
            col_w = _cmd_col_widths([], lambda r: "")
            has_non_gs_src = False
            sb = []
        row_w = w - 1 if sb else w
        # Title line
        ind = Text(f"[{start+1}-{end}/{count}] ", style=S_DIM) if count > data_rows else Text()
        t.append_text(lr_line(title, ind, w))
        hdr, hdr_right = build_col_hdr(col_w, has_non_gs_src=has_non_gs_src, has_time=True)
        t.append("\n")
        t.append_text(lr_line(hdr, hdr_right, row_w))
        if count == 0:
            t.append("\n  (no commands sent yet)", style=S_DIM)
            return t
        sending_active = s.sending.get("active", False)
        t.append("\n")
        for i, rec in enumerate(visible):
            src = rec.get('src', protocol.GS_NODE)
            is_last = (start + i == count - 1)
            b = "on #1a1a2e bold" if is_last and sending_active else ""
            h_node = f"{b} #778899"
            h_val  = f"{b} #8899aa"
            left = Text(style=b)
            hist_colors = {"num": "#8899aa", "time": "#8899aa", "node": "#778899",
                           "echo": "#888888" if protocol.NODE_NAMES.get(rec['echo']) == "NONE" else "#778899",
                           "ptype": "#778899", "cmd": "bold #8899aa" if not b else ""}
            args_indent = build_cmd_columns(left, col_w, num_str=f"#{rec['n']}",
                src=src, dest=rec["dest"], echo=rec["echo"],
                ptype_id=rec["ptype"], cmd_name=rec["cmd"],
                time_str=rec["ts"], has_non_gs_src=has_non_gs_src,
                b=b, colors=hist_colors)
            pending_args = None
            right = Text(f" {rec['payload_len']}B ", style=f"{b} #999999" if not b else b)
            if rec["args"]:
                avail = row_w - left.cell_len - right.cell_len
                if avail >= len(rec["args"]):
                    left.append(rec["args"], style=h_val)
                else:
                    pending_args = rec["args"]
            line = lr_line(left, right, row_w, fill_style=b)
            if sb:
                line.append(" ", style=sb[i])
            t.append_text(line)
            t.append("\n")
            if pending_args:
                append_wrapped_args(t, pending_args, args_indent, h_val, row_w)
                t.append("\n")
        return t


class TxStatusBar(Widget):
    """Single-line status bar displaying transient status messages."""
    DEFAULT_CSS = "TxStatusBar { height: 1; width: 100%; }"
    def __init__(self, state, **kw):
        super().__init__(**kw)
        self.s = state
    def render(self):
        s = self.s
        t = Text(no_wrap=True, overflow="crop")
        with s.send_lock:
            active = s.sending.get("active")
            idx = s.sending.get("idx", 0)
            total = s.sending.get("total", len(s.tx_queue))
        if active:
            t.append(f" SENT {idx + 1}/{total}", style=S_SUCCESS)
        elif s.status.text:
            t.append(f" {s.status.text}", style=S_WARNING)
        t.truncate(self.content_size.width)
        return t


# -- Help / Config data -------------------------------------------------------

HELP_LINES = [
    ("SENDING", None),
    ("Ctrl+S", "Send all queued commands"),
    ("Ctrl+C / Esc", "Abort send in progress"),
    ("Enter", "Confirm guarded command"),
    ("QUEUE", None),
    ("CMD [ARGS]", "Queue using schema defaults"),
    ("[SRC] DEST ECHO TYPE CMD", "Queue with explicit routing"),
    ("Ctrl+Z", "Remove last item"),
    ("Ctrl+X", "Clear entire queue"),
    ("Space", "Toggle guard (queue focus)"),
    ("wait [ms]", "Queue a delay between commands"),
    ("imp [file]", "Import from generated_commands/"),
    ("COMMAND FORMAT", None),
    ("e.g.", "set_voltage 3.3"),
    ("e.g.", "EPS NONE CMD ping hello"),
    ("SRC / DEST / ECHO", "Node name or ID"),
    ("TYPE", "CMD | RES | ACK | TLM | FILE"),
    ("COMMANDS", None),
    ("mode [AX.25|ASM+GOLAY]", "Switch uplink encoding"),
    ("raw <hex>", "Send raw hex bytes"),
    ("nodes", "List all node IDs"),
    ("cfg / help", "Open config / help"),
    ("tag <name>", "Tag log file"),
    ("log [name]", "Start new log session"),
    ("q", "Exit"),
]

def _is_golay(v): return v.get("uplink_mode") == "ASM+Golay"
def _is_ax25(v): return v.get("uplink_mode") == "AX.25"

CONFIG_FIELDS = [
    ("Uplink Mode", "uplink_mode", ("cycle", ["AX.25", "ASM+Golay"], {"AX.25": Style(color="#6699cc", bold=True), "ASM+Golay": Style(color="#55bbaa", bold=True)}, {"ASM+Golay": "ASM+GOLAY"})),
    # AX.25 fields
    ("AX.25 Src Call", "ax25_src_call", True, _is_ax25),
    ("AX.25 Src SSID", "ax25_src_ssid", True, _is_ax25),
    ("AX.25 Dest Call", "ax25_dest_call", True, _is_ax25),
    ("AX.25 Dest SSID", "ax25_dest_ssid", True, _is_ax25),
    # Common fields (always visible)
    ("CSP CRC-32", "csp_crc", ("cycle", ["ON", "OFF"], {"ON": Style(color="#55bb55", bold=True), "OFF": Style(color="#ff6666", bold=True)}, {})),
    ("CSP Priority", "csp_prio", True), ("CSP Source", "csp_src", True),
    ("CSP Destination", "csp_dest", True), ("CSP Dest Port", "csp_dport", True),
    ("CSP Src Port", "csp_sport", True), ("CSP Flags", "csp_flags", True),
    ("Frequency", "freq", True), ("ZMQ Address", "zmq_addr", True),
    ("TX Delay (ms)", "tx_delay_ms", True),
]

def config_get_values(csp, ax25, freq, zmq_addr, tx_delay_ms, uplink_mode="AX.25"):
    """Extract current TX config values for the config modal."""
    return {
        "uplink_mode": uplink_mode,
        "ax25_src_call": ax25.src_call, "ax25_src_ssid": str(ax25.src_ssid),
        "ax25_dest_call": ax25.dest_call, "ax25_dest_ssid": str(ax25.dest_ssid),
        "csp_crc": "ON" if csp.csp_crc else "OFF",
        "csp_prio": str(csp.prio), "csp_src": str(csp.src), "csp_dest": str(csp.dest),
        "csp_dport": str(csp.dport), "csp_sport": str(csp.sport), "csp_flags": f"0x{csp.flags:02X}",
        "freq": freq, "zmq_addr": zmq_addr, "tx_delay_ms": str(tx_delay_ms),
    }

def config_apply(values, csp, ax25):
    """Apply edited config values back to CSP/AX25 objects. Returns (freq, zmq, delay, mode)."""
    ax25.src_call = values["ax25_src_call"].upper()[:6]
    ax25.src_ssid = int(values["ax25_src_ssid"])
    ax25.dest_call = values["ax25_dest_call"].upper()[:6]
    ax25.dest_ssid = int(values["ax25_dest_ssid"])
    csp.csp_crc = values["csp_crc"] == "ON"
    csp.prio = int(values["csp_prio"], 0); csp.src = int(values["csp_src"], 0)
    csp.dest = int(values["csp_dest"], 0); csp.dport = int(values["csp_dport"], 0)
    csp.sport = int(values["csp_sport"], 0); csp.flags = int(values["csp_flags"], 0)
    return values["freq"], values["zmq_addr"], max(0, int(values["tx_delay_ms"])), values["uplink_mode"]

def tx_help_info(s):
    """Return (version, schema_count, schema_path, log_path) for the help panel."""
    return (s.version, s.schema_count, s.schema_path, s.tx_log.text_path)

def build_guard_content(item, num, total):
    """Build a reverse-highlighted Rich Text line for the guard confirmation modal,
    matching the TX queue row format."""
    b = "reverse bold"
    src, dest, echo = item["src"], item["dest"], item["echo"]
    ptype = item["ptype"]
    t = Text(style=b)
    t.append(f" #{num} ", style=f"{b} #ffffff")
    if src != protocol.GS_NODE:
        t.append(f" {node_label(src)} → {node_label(dest)} ", style=f"{b} #00bfff")
    else:
        t.append(f" {node_label(dest)} ", style=f"{b} #00bfff")
    if protocol.NODE_NAMES.get(echo) != "NONE":
        t.append(f" E:{node_label(echo)} ", style=f"{b} {node_color(echo)}")
    pt = protocol.PTYPE_NAMES.get(ptype, str(ptype))
    t.append(f" {pt} ", style=f"{b} {ptype_color(ptype)}")
    t.append(f" {item['cmd']} ", style=f"{b} #ffffff")
    if item["args"]:
        t.append(f" {item['args']} ", style=f"{b} #ffffff")
    t.append(f" {len(item['raw_cmd'])}B ", style=f"{b} #999999")
    return t
