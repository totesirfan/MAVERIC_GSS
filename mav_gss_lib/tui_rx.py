"""
mav_gss_lib.tui_rx -- RX Monitor Widgets (Textual)

Author:  Irfan Annuar - USC ISI SERC
"""

from datetime import datetime, timezone
from rich.text import Text
from mav_gss_lib.tui_common import Widget

import mav_gss_lib.protocol as protocol
from mav_gss_lib.protocol import node_label, ptype_label, format_arg_value
from mav_gss_lib.tui_common import (
    S_LABEL, S_VALUE, S_SUCCESS, S_WARNING, S_ERROR, S_DIM, S_SEP, lr_line,
    scrollbar_styles, append_wrapped_args,
    TS_SHORT, frame_color, ptype_color, node_color, compute_col_widths,
)

class RxHeader(Widget):
    """Header bar showing ZMQ status, frequency, toggle states, queue depth, and clocks."""
    DEFAULT_CSS = "RxHeader { height: 4; width: 100%; dock: top; }"

    def __init__(self, state, zmq_status_ref, queue_ref, **kw):
        super().__init__(**kw)
        self.s, self._zmq, self._q = state, zmq_status_ref, queue_ref

    def render(self):
        s, w = self.s, self.content_size.width
        utc = datetime.now(timezone.utc).strftime(TS_SHORT)
        local = datetime.now().strftime(TS_SHORT)
        zmq = Text()
        zmq.append(" ZMQ ", style=S_LABEL)
        zmq.append(f"{s.zmq_addr} ", style=S_VALUE)
        st = self._zmq[0]
        zmq.append(f"[{st}]", style=S_SUCCESS if st == "LIVE" else (S_ERROR if st == "DOWN" else S_VALUE))
        zmq.append(f"  Freq: {s.frequency}", style=S_WARNING)
        tog = Text()
        tog.append("HEX:", style=S_LABEL)
        tog.append("ON" if s.show_hex else "OFF", style=S_SUCCESS if s.show_hex else S_DIM)
        tog.append("  UL:", style=S_LABEL)
        tog.append("HIDE" if s.hide_uplink else "SHOW", style=S_WARNING if s.hide_uplink else S_DIM)
        t = Text()
        t.append_text(lr_line(Text(f" MAVERIC RX MONITOR", style=S_SUCCESS),
                               Text(f"UTC {utc}  Local {local} ", style=S_VALUE), w))
        t.append("\n" + "─" * w + "\n", style=S_SEP)
        t.append_text(lr_line(zmq, tog, w))
        q_line = Text()
        q_line.append(" ZMQ Thread Queue: ", style=S_LABEL)
        q_line.append(str(self._q.qsize()), style=S_VALUE)
        t.append("\n")
        t.append_text(q_line)
        return t


class PacketList(Widget):
    """Scrollable list of received packets with selection, auto-scroll,
    inline spinner, scrollbar, uplink echo hiding, and duplicate tagging."""
    DEFAULT_CSS = "PacketList { height: 1fr; width: 100%; border-top: solid #555555; border-left: solid black; border-right: solid black; } PacketList:focus { border: solid #00bfff; }"
    can_focus = True

    def __init__(self, state, **kw):
        super().__init__(**kw)
        self.s = state

    # -- Mouse wheel -----------------------------------------------------------

    def _find_prev_visible(self, from_idx):
        """Find the previous visible packet index, skipping hidden uplink echoes."""
        s = self.s
        for i in range(from_idx - 1, -1, -1):
            if not s.hide_uplink or not s.packets[i].get("is_uplink_echo"):
                return i
        return from_idx

    def _find_next_visible(self, from_idx):
        """Find the next visible packet index, or -1 for auto-scroll."""
        s = self.s
        for i in range(from_idx + 1, len(s.packets)):
            if not s.hide_uplink or not s.packets[i].get("is_uplink_echo"):
                return i
        return -1

    def _find_last_visible(self):
        """Find the last visible packet index (for entering selection mode)."""
        s = self.s
        for i in range(len(s.packets) - 1, -1, -1):
            if not s.hide_uplink or not s.packets[i].get("is_uplink_echo"):
                return i
        return 0

    def on_key(self, event):
        if event.key == "enter":
            self.s.detail_open = not self.s.detail_open
            self.refresh()
            event.prevent_default()

    def on_mouse_scroll_up(self, event):
        s = self.s
        if not s.packets: return
        if s.selected_idx == -1:
            s.selected_idx = self._find_last_visible()
            lh = self.content_size.height - 4
            if lh > 0:
                s.scroll_offset = max(0, len(s.packets) - lh)
        for _ in range(3):
            prev = self._find_prev_visible(s.selected_idx)
            if prev == s.selected_idx: break
            s.selected_idx = prev
        self.refresh()

    def on_mouse_scroll_down(self, event):
        s = self.s
        if not s.packets: return
        if s.selected_idx != -1:
            for _ in range(3):
                nxt = self._find_next_visible(s.selected_idx)
                if nxt == -1: s.selected_idx = -1; break
                s.selected_idx = nxt
        self.refresh()

    # -- Render ----------------------------------------------------------------

    def render(self):
        s, w, h = self.s, self.content_size.width, self.content_size.height
        # Build filtered view: list of (original_idx, pkt)
        if s.hide_uplink:
            filtered = [(i, p) for i, p in enumerate(s.packets) if not p.get("is_uplink_echo")]
        else:
            filtered = list(enumerate(s.packets))
        count = len(filtered)
        auto = (s.selected_idx == -1)
        t = Text()
        total_label = f"{count}" if count == len(s.packets) else f"{count}/{len(s.packets)}"
        title = Text(f" PACKETS ({total_label})", style=S_SUCCESS)
        title.append("  Auto Scroll:", style=S_LABEL)
        title.append("ON" if auto else "OFF", style=S_SUCCESS if auto else S_DIM)
        data_rows = h - 4  # title + padding + separator + spinner
        if data_rows < 1 or count == 0:
            t.append_text(title)
            if count == 0:
                t.append("\n  (waiting for packets...)", style=S_DIM)
            # Pad to pin spinner at bottom
            used = 2 if count == 0 else 1
            for _ in range(max(0, data_rows - used)):
                t.append("\n")
            t.append("\n")
            t.append("─" * w, style=S_SEP)
            t.append("\n")
            t.append_text(self._spinner_line(s, w))
            return t
        if auto:
            end, start = count, max(0, count - data_rows)
        else:
            # Map selected_idx to filtered position
            filt_sel = next((fi for fi, (oi, _) in enumerate(filtered) if oi == s.selected_idx), count - 1)
            start, end = s.scroll_offset, min(count, s.scroll_offset + data_rows)
            # Ensure selected is visible
            if filt_sel < start: start = filt_sel
            elif filt_sel >= end: start = filt_sel - data_rows + 1
            start = max(0, start)
            end = min(count, start + data_rows)
            s.scroll_offset = start
        ind = Text(f"[{start+1}-{end}/{count}] ", style=S_DIM) if count > data_rows else Text()
        t.append_text(lr_line(title, ind, w))
        t.append("\n")
        actual = len(s.packets) - 1 if auto else s.selected_idx
        # Scrollbar
        sb = scrollbar_styles(count, data_rows, start, data_rows) if count > data_rows else []
        # Dynamic column alignment over visible packets
        vis_slice = filtered[start:end]
        col_w = self._compute_col_widths([p for _, p in vis_slice])
        sb_idx = 0
        for i, (orig_idx, pkt) in enumerate(vis_slice):
            t.append("\n")
            row_w = w - 1 if sb else w  # reserve 1 char for scrollbar gutter
            line = self._pkt_line(pkt, orig_idx == actual, row_w, col_w)
            if sb and sb_idx < len(sb):
                line.append(" ", style=sb[sb_idx])
            sb_idx += 1
            t.append_text(line)
            # Wrap args onto continuation line if they didn't fit
            if self._pending_args:
                args_text, indent, args_style = self._pending_args
                self._pending_args = None
                sb_idx = append_wrapped_args(t, args_text, indent, args_style, row_w, sb, sb_idx)
        # Pad to pin spinner at bottom
        remaining = data_rows - sb_idx
        for j in range(max(0, remaining)):
            t.append("\n")
            if sb and sb_idx < len(sb):
                pad = Text(" " * (w - 1))
                pad.append(" ", style=sb[sb_idx])
                t.append_text(pad)
            sb_idx += 1
        t.append("\n")
        t.append("─" * w, style=S_SEP)
        t.append("\n")
        t.append_text(self._spinner_line(s, w))
        return t

    @staticmethod
    def _compute_col_widths(visible):
        """Pre-scan visible packets to compute dynamic column widths."""
        def _num(p):
            if p.get("is_unknown") and p.get("unknown_num") is not None:
                return [f"U-{p['unknown_num']}"]
            return [f"#{p.get('pkt_num', 0)}"]
        def _cmd_field(p, key):
            cmd = p.get("cmd")
            return [node_label(cmd[key])] if cmd else []
        def _ptype(p):
            cmd = p.get("cmd")
            return [protocol.PTYPE_NAMES.get(cmd['pkt_type'], '?')] if cmd else []
        return compute_col_widths(visible, {
            "num": _num,
            "src": lambda p: _cmd_field(p, 'src'),
            "dest": lambda p: _cmd_field(p, 'dest'),
            "echo": lambda p: _cmd_field(p, 'echo'),
            "ptype": _ptype,
        }, defaults={"num": 2})

    def _spinner_line(self, s, w):
        """Build the bottom spinner/status line showing receive state and packet rate."""
        t = Text(no_wrap=True, overflow="crop")
        if s.error_status.text:
            t.append(f" {s.error_status.text}", style=S_ERROR)
        elif s.status.text:
            t.append(f" {s.status.text}", style=S_WARNING)
        else:
            spin_char = s.spinner[s.spin_idx] if s.spinner else "▸"
            if s.receiving:
                t.append(f" {spin_char:<5}", style=S_SUCCESS)
                t.append("  Receiving", style=S_SUCCESS)
            else:
                t.append(f" {spin_char:<5}", style=S_LABEL)
                secs = s.silence_secs
                t.append(f"  Waiting... {secs:05.1f}s", style=S_LABEL)
            t.append(f"  {s.pkt_count} pkts", style=S_DIM)
            if s.rate_per_min > 0:
                t.append(f"  {s.rate_per_min:.0f} pkt/min", style=S_DIM)
        return t

    def _pkt_line(self, pkt, is_sel, w, col_w):
        """Render one packet as a single-line Text with dynamic column alignment."""
        b = "reverse" if is_sel else ""
        cmd = pkt.get("cmd")
        nw, sw, dw, ew, pw = (col_w["num"], col_w["src"], col_w["dest"],
                               col_w["echo"], col_w["ptype"])
        left = Text(style=b)
        if pkt.get("is_unknown") and pkt.get("unknown_num") is not None:
            left.append(f" {'U-' + str(pkt['unknown_num']):<{nw}} ", style=f"{b} #ff4444")
        else:
            left.append(f" {'#' + str(pkt.get('pkt_num',0)):<{nw}} ", style=f"{b} #888888")
        left.append(f"{pkt.get('gs_ts_short','??:??:??')} ", style=f"{b} #ffffff")
        self._pending_args = None
        if pkt.get("is_unknown"):
            left.append("UNKNOWN ", style=f"{b} bold #ff4444")
        else:
            ft = pkt.get("frame_type", "???")
            left.append(f"{ft:<10} ", style=f"{b} {frame_color(ft)}")
            if cmd:
                left.append(f"{node_label(cmd['src']):>{sw}} → {node_label(cmd['dest']):<{dw}}  ", style=f"{b} #00bfff")
                left.append(f"E:{node_label(cmd['echo']):<{ew}}  ", style=f"{b} #888888")
                pt = cmd['pkt_type']
                left.append(f"{protocol.PTYPE_NAMES.get(cmd['pkt_type'],'?'):<{pw}}  ", style=f"{b} {ptype_color(pt)}")
                left.append(f"{cmd['cmd_id'][:14]} ", style=f"{b} bold #ffffff")
                args = (" ".join(format_arg_value(ta) for ta in cmd.get("typed_args",[])
                                 if ta.get("important"))
                        if cmd.get("schema_match")
                        else " ".join(str(a) for a in cmd.get("args",[])))
                if args:
                    self._pending_args = (args, left.cell_len, f"{b} #888888")
        right = Text(style=b)
        crc_v = pkt.get("crc_status",{}).get("csp_crc32_valid")
        if crc_v is None and cmd:
            crc_v = cmd.get("crc_valid")
        if crc_v is False:
            right.append("CRC:FAIL  ", style=f"{b} bold #ff4444")
        if pkt.get("is_uplink_echo"):
            right.append("UL  ", style=f"{b} bold #ffd700")
        if pkt.get("is_dup"):
            right.append("DUP  ", style=f"{b} bold #ff4444")
        right.append(f"{len(pkt.get('inner_payload',b''))}B ", style=f"{b} #888888")
        # Check if args fit on first line
        if self._pending_args:
            args_text, indent, args_style = self._pending_args
            avail = w - left.cell_len - right.cell_len
            if avail >= len(args_text):
                left.append(args_text, style=args_style)
                self._pending_args = None
        return lr_line(left, right, w, fill_style=b)


def _build_detail_lines(pkt, is_unk, show_hex, show_wrapper):
    """Build detail field lines as [(label, value, style), ...] from packet data."""
    lines = []
    def f(lbl, val, st=S_VALUE): lines.append((lbl, str(val), st))
    if is_unk:
        if show_hex:
            raw = pkt.get("raw", b"")
            if raw: f("HEX", raw.hex(" "), S_DIM)
            if pkt.get("text"): f("ASCII", pkt["text"], S_DIM)
            inner = pkt.get("inner_payload", b"")
            if inner: f("SIZE", f"{len(inner)}B (raw {len(raw)}B)", S_DIM)
        return lines
    for wm in pkt.get("warnings", []): lines.append(("⚠", wm, S_ERROR))
    if pkt.get("is_uplink_echo"): f("UL ECHO", "Uplink echo — dest/echo not addressed to GS", S_WARNING)
    if show_wrapper and pkt.get("stripped_hdr"): f("AX.25 HDR", pkt["stripped_hdr"], S_DIM)
    csp = pkt.get("csp")
    if show_wrapper and csp:
        tag = "CSP V1" if pkt.get("csp_plausible") else "CSP V1 [?]"
        f(tag, f"Prio:{csp['prio']}  Src:{csp['src']}  Dest:{csp['dest']}  DPort:{csp['dport']}  SPort:{csp['sport']}  Flags:0x{csp['flags']:02x}")
    cmd = pkt.get("cmd")
    if cmd:
        route = Text()
        route.append("Src:", style="#ffffff"); route.append(f"{node_label(cmd['src'])}  ", style=node_color(cmd['src']))
        route.append("Dest:", style="#ffffff"); route.append(f"{node_label(cmd['dest'])}  ", style=node_color(cmd['dest']))
        route.append("Echo:", style="#ffffff"); route.append(f"{node_label(cmd['echo'])}  ", style=node_color(cmd['echo']))
        pt = cmd['pkt_type']
        route.append("Type:", style="#ffffff"); route.append(ptype_label(cmd['pkt_type']), style=ptype_color(pt))
        lines.append(("CMD ROUTE", route, S_VALUE))
        f("CMD ID", cmd["cmd_id"])
        if cmd.get("schema_match"):
            for ta in cmd.get("typed_args", []): f(ta["name"].upper()[:12], format_arg_value(ta))
            for i, ex in enumerate(cmd.get("extra_args", [])): f(f"ARG +{i}", str(ex))
        else:
            if cmd.get("schema_warning"): lines.append(("⚠", cmd["schema_warning"], S_WARNING))
            for i, a in enumerate(cmd.get("args", [])): f(f"ARG {i}", str(a))
    # CRC: always show if FAIL, otherwise only with wrapper
    if cmd and cmd.get("crc") is not None:
        v = cmd.get("crc_valid")
        if show_wrapper or not v: f("CRC-16", f"0x{cmd['crc']:04x}  [{'OK' if v else 'FAIL'}]", S_SUCCESS if v else S_ERROR)
    crc_st = pkt.get("crc_status", {})
    if crc_st.get("csp_crc32_valid") is not None:
        v = crc_st["csp_crc32_valid"]
        if show_wrapper or not v: f("CRC-32C", f"0x{crc_st['csp_crc32_rx']:08x}  [{'OK' if v else 'FAIL'}]", S_SUCCESS if v else S_ERROR)
    if show_hex:
        raw = pkt.get("raw", b"")
        if raw: f("HEX", raw.hex(" "), S_DIM)
        if pkt.get("text"): f("ASCII", pkt["text"], S_DIM)
    return lines


class PacketDetail(Widget):
    """Expanded detail view for the selected packet — CSP header fields,
    command routing, CRC verification, hex/ASCII dump, and parsed args."""
    DEFAULT_CSS = "PacketDetail { max-height: 50%; width: 100%; border-left: solid black; border-right: solid black; }"

    def __init__(self, state, **kw):
        super().__init__(**kw)
        self.s = state

    def render(self):
        s = self.s
        w = self.content_size.width or 80
        auto = (s.selected_idx == -1)
        if auto and s.packets:
            # Find last visible packet for auto-scroll
            actual = len(s.packets) - 1
            if s.hide_uplink:
                for i in range(len(s.packets) - 1, -1, -1):
                    if not s.packets[i].get("is_uplink_echo"):
                        actual = i; break
        else:
            actual = s.selected_idx
        pkt = s.packets[actual] if 0 <= actual < len(s.packets) else None
        # Skip uplink echoes in detail
        if pkt and s.hide_uplink and pkt.get("is_uplink_echo"):
            pkt = None
        sep = Text("─" * w, style=S_SEP)
        if not pkt:
            self.styles.height = 1
            return sep
        is_unk = pkt.get("is_unknown", False)
        ts_r = pkt.get("ts_result")
        if is_unk and pkt.get("unknown_num") is not None:
            title = Text(f" UNKNOWN U-{pkt['unknown_num']}", style=S_ERROR)
        else:
            title = Text(f" PACKET #{pkt.get('pkt_num',0)} DETAIL", style=S_WARNING)
        if ts_r:
            title.append(f"  {ts_r[0].strftime('%Y-%m-%d %H:%M:%S UTC')}  {ts_r[1].strftime('%Y-%m-%d %H:%M:%S %Z')}", style="#ffffff")
        lines = _build_detail_lines(pkt, is_unk, s.show_hex, s.show_wrapper)

        # Render lines, wrapping long values with aligned continuation
        label_w = 13  # " " + 12-char label
        val_w = max(1, w - label_w)
        rendered_rows = 2  # sep + title
        t = Text()
        t.append_text(sep)
        t.append("\n")
        t.append_text(lr_line(title, Text(), w))
        for lbl, val, st in lines:
            t.append("\n")
            row = Text()
            row.append(f" {lbl:<12}", style=S_LABEL)
            if isinstance(val, Text):
                row.append_text(val)
            else:
                chunks = [val[i:i + val_w] for i in range(0, len(val), val_w)] if len(val) > val_w else [val]
                row.append(chunks[0], style=st)
            t.append_text(row)
            rendered_rows += 1
            if not isinstance(val, Text):
                for chunk in chunks[1:]:
                    t.append("\n")
                    cont = Text()
                    cont.append(" " * label_w, style="")
                    cont.append(chunk, style=st)
                    t.append_text(cont)
                    rendered_rows += 1
        rendered_rows += 1  # blank padding at bottom
        self.styles.height = rendered_rows
        return t



# -- Help / Config data -------------------------------------------------------

RX_HELP_LINES = [
    ("KEYS", None), ("Up / Down", "Select packet"), ("PgUp / PgDn", "Scroll page"),
    ("Mouse wheel", "Scroll packet list"),
    ("Enter (on list)", "Toggle detail"), ("Ctrl+A / Ctrl+E", "Cursor start / end"),
    ("Ctrl+W / Ctrl+U", "Del word / clear input"), ("Ctrl+C", "Quit"),
    ("COMMANDS", None), ("cfg / help", "Toggle panels"), ("hclear", "Clear history"),
    ("hex / ul / wrapper", "Toggle hex / uplink / wrapper"),
    ("wrapper", "Toggle AX.25/CSP/CRC detail"),
    ("detail / live", "Toggle detail / follow"),
    ("q", "Exit"),
    ("INDICATORS", None), ("[LIVE]", "Auto-follow newest"), ("UL", "Uplink echo"),
    ("DUP", "Duplicate packet"), ("CRC:OK/FAIL", "Integrity check"),
]

RX_CONFIG_FIELDS = [("Hex Display", "show_hex", "toggle"), ("Wrapper", "show_wrapper", "toggle"), ("Hide Uplink", "hide_uplink", "toggle")]

def rx_config_get_values(s):
    """Extract current RX config toggle values for the config modal."""
    return {"show_hex": "ON" if s.show_hex else "OFF", "show_wrapper": "ON" if s.show_wrapper else "OFF", "hide_uplink": "ON" if s.hide_uplink else "OFF"}

def rx_help_info(s):
    """Return (version, schema_count, schema_path, log_path) for the help panel."""
    return (s.version, s.schema_count, s.schema_path, s.log.text_path if s.log else "(disabled)")
