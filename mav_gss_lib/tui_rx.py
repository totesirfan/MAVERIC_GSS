"""
mav_gss_lib.tui_rx -- RX Monitor Widgets (Textual)

Author:  Irfan Annuar - USC ISI SERC
"""

import time

from rich.style import Style
from rich.text import Text
from mav_gss_lib.tui_common import Widget

import mav_gss_lib.protocol as protocol
from mav_gss_lib.protocol import node_label, ptype_label, format_arg_value
from mav_gss_lib.tui_common import (
    S_LABEL, S_VALUE, S_SUCCESS, S_WARNING, S_ERROR, S_DIM, S_SEP, lr_line,
    scrollbar_styles, append_wrapped_args, build_header, build_col_hdr,
    build_cmd_columns, flash_phase,
    TS_SHORT, frame_color, ptype_color, node_color, compute_col_widths, title_style, title_fill,
    hide_echo_if_all_none,
)

# Spinner flash styles: (receiving_unknown, flash_phase) -> (text_style, fill_style)
_RECV_STYLES = {
    (True, True):   ("reverse bold #ffd700", "reverse #ffd700"),
    (True, False):  ("on #332b00 bold #ffd700", "on #332b00"),
    (False, True):  ("reverse bold #00ff87", "reverse #00ff87"),
    (False, False): ("on #003300 bold #00ff87", "on #003300"),
}

class RxHeader(Widget):
    """Header bar showing ZMQ status, frequency, toggle states, queue depth, and clocks.
    Wraps info items to next row when terminal is too narrow."""
    DEFAULT_CSS = "RxHeader { height: auto; width: 100%; dock: top; }"

    def __init__(self, state, zmq_status_ref, queue_ref, **kw):
        super().__init__(**kw)
        self.s, self._zmq, self._q = state, zmq_status_ref, queue_ref

    def render(self):
        s, w = self.s, self.content_size.width
        st = self._zmq[0]
        if st == "ONLINE":
            zmq_style = S_SUCCESS
        else:
            zmq_style = "reverse bold #ff4444" if flash_phase() else "on #330000 bold #ff4444"
        zmq_val = Text()
        zmq_val.append(s.zmq_addr, style=S_VALUE)
        zmq_val.append(" ")
        zmq_val.append(f"[{st}]", style=zmq_style)
        qdepth = self._q.qsize()
        hex_s = S_SUCCESS if s.show_hex else S_DIM
        ul_s = S_DIM if s.hide_uplink else S_WARNING
        q_s = S_VALUE if qdepth else S_DIM
        hex_lbl = S_LABEL if s.show_hex else S_DIM
        ul_lbl = S_DIM if s.hide_uplink else S_LABEL
        q_lbl = S_LABEL if qdepth else S_DIM
        hex_t = Text(); hex_t.append("HEX:", style=hex_lbl); hex_t.append("ON" if s.show_hex else "OFF", style=hex_s)
        ul_t = Text(); ul_t.append("UL:", style=ul_lbl); ul_t.append("HIDE" if s.hide_uplink else "SHOW", style=ul_s)
        q_t = Text(); q_t.append("Queue:", style=q_lbl); q_t.append(str(qdepth), style=q_s)
        items = [
            ("ZMQ", zmq_val, None),
            ("", hex_t, None),
            ("", ul_t, None),
            ("", q_t, None),
        ]
        t, _ = build_header("MAVERIC DOWNLINK", S_LABEL, items, w)
        return t


class _FilteredCache:
    """Caches the filtered packet list; invalidates on generation counter or toggle change."""
    __slots__ = ("_cache", "_last_gen", "_last_hide")
    def __init__(self):
        self._cache = []
        self._last_gen = -1
        self._last_hide = None
    def get(self, packets, hide_uplink, pkt_gen=0):
        if pkt_gen == self._last_gen and hide_uplink == self._last_hide:
            return self._cache
        if hide_uplink:
            self._cache = [(i, p) for i, p in enumerate(packets) if not p.get("is_uplink_echo")]
        else:
            self._cache = list(enumerate(packets))
        self._last_gen = pkt_gen
        self._last_hide = hide_uplink
        return self._cache


class PacketList(Widget):
    """Scrollable list of received packets with selection, auto-scroll,
    inline spinner, scrollbar, uplink echo hiding, and duplicate tagging."""
    DEFAULT_CSS = "PacketList { height: 1fr; width: 100%; border-top: solid #555555; border-left: solid black; border-right: solid black; } PacketList:focus { border: solid #00bfff; }"
    can_focus = True

    def __init__(self, state, **kw):
        super().__init__(**kw)
        self.s = state
        self._filter_cache = _FilteredCache()

    # -- Mouse wheel -----------------------------------------------------------

    def _is_visible(self, idx):
        return not self.s.hide_uplink or not self.s.packets[idx].get("is_uplink_echo")

    def _find_prev_visible(self, from_idx):
        """Find the previous visible packet index, skipping hidden uplink echoes."""
        for i in range(from_idx - 1, -1, -1):
            if self._is_visible(i): return i
        return from_idx

    def _find_next_visible(self, from_idx):
        """Find the next visible packet index, or -1 for auto-scroll."""
        for i in range(from_idx + 1, len(self.s.packets)):
            if self._is_visible(i): return i
        return -1

    def _find_last_visible(self):
        """Find the last visible packet index (for entering selection mode)."""
        for i in range(len(self.s.packets) - 1, -1, -1):
            if self._is_visible(i): return i
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
        prev = self._find_prev_visible(s.selected_idx)
        if prev != s.selected_idx:
            s.selected_idx = prev
        self.refresh()

    def on_mouse_scroll_down(self, event):
        s = self.s
        if not s.packets: return
        if s.selected_idx != -1:
            nxt = self._find_next_visible(s.selected_idx)
            if nxt == -1: s.selected_idx = -1
            else: s.selected_idx = nxt
        self.refresh()

    # -- Render ----------------------------------------------------------------

    def render(self):
        s, w, h = self.s, self.content_size.width, self.content_size.height
        # Build filtered view: list of (original_idx, pkt) — cached
        filtered = self._filter_cache.get(s.packets, s.hide_uplink, getattr(s, 'pkt_gen', 0))
        count = len(filtered)
        auto = (s.selected_idx == -1)
        t = Text(no_wrap=True, overflow="crop")
        title = Text()
        tf = self.has_focus
        title.append(f" PACKETS ({count}) ", style=title_style(tf))
        if not auto:
            title.append(" SCROLL UNLOCKED ", style="bold #000000 on #ffd700")
        data_rows = h - 4  # title + col header + separator + spinner
        # Compute visible slice first so header and data share same col widths
        if data_rows >= 1 and count > 0:
            if auto:
                end, start = count, max(0, count - data_rows)
            else:
                filt_sel = next((fi for fi, (oi, _) in enumerate(filtered) if oi == s.selected_idx), count - 1)
                start, end = s.scroll_offset, min(count, s.scroll_offset + data_rows)
                if filt_sel < start: start = filt_sel
                elif filt_sel >= end: start = filt_sel - data_rows + 1
                start = max(0, start)
                end = min(count, start + data_rows)
                s.scroll_offset = start
            vis_slice = filtered[start:end]
            col_w = self._compute_col_widths([p for _, p in vis_slice])
            sb = scrollbar_styles(count, data_rows, start, data_rows) if count > data_rows else []
        else:
            vis_slice, start, end = [], 0, 0
            col_w = self._compute_col_widths([])
            sb = []
        row_w = w - 1 if sb else w
        # Title line
        ind = Text(f"[{start+1}-{end}/{count}] ", style=S_DIM) if count > data_rows else Text()
        t.append_text(lr_line(title, ind, w))
        # Sticky column header row — always visible, aligned with data
        hdr, hdr_right = build_col_hdr(col_w, has_non_gs_src=True, has_time=True,
                                       has_frame=True, right_text="FLAGS  SIZE ")
        t.append("\n")
        t.append_text(lr_line(hdr, hdr_right, row_w))
        if data_rows < 1 or count == 0:
            if count == 0:
                t.append("\n  (waiting for packets...)", style=S_DIM)
            used = 2 if count == 0 else 1
            for _ in range(max(0, data_rows - used + 1)):
                t.append("\n")
            t.append("\n")
            t.append("─" * w, style=S_SEP)
            t.append("\n")
            t.append_text(self._spinner_line(s, w))
            return t
        actual = len(s.packets) - 1 if auto else s.selected_idx
        sb_idx = 0
        for i, (orig_idx, pkt) in enumerate(vis_slice):
            t.append("\n")
            line, pending = self._pkt_line(pkt, orig_idx == actual, row_w, col_w)
            if sb and sb_idx < len(sb):
                line.append(" ", style=sb[sb_idx])
            sb_idx += 1
            t.append_text(line)
            if pending:
                args_text, indent, args_style = pending
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
        def _frame(p):
            if p.get("is_unknown"): return ["UNKNOWN"]
            return [p.get("frame_type", "???")]
        result = compute_col_widths(visible, {
            "num": _num,
            "frame": _frame,
            "src": lambda p: _cmd_field(p, 'src'),
            "dest": lambda p: _cmd_field(p, 'dest'),
            "echo": lambda p: _cmd_field(p, 'echo'),
            "ptype": _ptype,
        }, defaults={"num": 2, "frame": 5, "src": 3, "dest": 4, "echo": 4, "ptype": 4})
        hide_echo_if_all_none(result, [p["cmd"]["echo"] for p in visible if p.get("cmd")])
        return result

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
                rs, fill = _RECV_STYLES[(s.receiving_unknown, flash_phase())]
                t.append(f" {spin_char:<5}", style=rs)
                t.append("  Received", style=rs)
                remaining = w - t.cell_len
                if remaining > 0:
                    t.append(" " * remaining, style=fill)
                return t
            else:
                cycle = int(s._spin_acc) % 8
                pos = cycle if cycle < 5 else 8 - cycle
                bar = " " * pos + "•" + " " * (4 - pos)
                t.append(f" {bar}", style=S_DIM)
                secs = s.silence_secs
                t.append(f"  Waiting... {secs:05.1f}s", style=S_DIM)
            if s.rate_per_min > 0:
                t.append(f"  {s.rate_per_min:.0f} pkt/min", style=S_DIM)
        return t

    def _pkt_line(self, pkt, is_sel, w, col_w):
        """Render one packet as a single-line Text with dynamic column alignment."""
        b = "reverse bold" if is_sel else ""
        cmd = pkt.get("cmd")
        left = Text(style=b)
        pending_args = None
        is_unk = pkt.get("is_unknown")
        if is_unk and pkt.get("unknown_num") is not None:
            num_str = "U-" + str(pkt["unknown_num"])
        else:
            num_str = "#" + str(pkt.get("pkt_num", 0))
        if is_unk:
            # Unknown: just num + time + "UNKNOWN" frame label
            fw = col_w.get("frame", 5)
            left.append(f" {num_str:<{col_w['num']}} ", style=f"{b} #ffd700")
            left.append(f" {pkt.get('gs_ts_short','??:??:??')} ", style=f"{b} #ffffff")
            left.append(f" {'UNKNOWN':<{fw}} ", style=f"{b} bold #ffd700")
        elif cmd:
            build_cmd_columns(left, col_w, num_str=num_str,
                src=cmd["src"], dest=cmd["dest"], echo=cmd["echo"],
                ptype_id=cmd["pkt_type"], cmd_name=cmd["cmd_id"][:14],
                time_str=pkt.get("gs_ts_short", "??:??:??"),
                frame_str=pkt.get("frame_type", "???"), b=b)
            args = (" ".join(format_arg_value(ta) for ta in cmd.get("typed_args",[])
                             if ta.get("important"))
                    if cmd.get("schema_match")
                    else " ".join(str(a) for a in cmd.get("args",[])))
            if args:
                pending_args = (" " + args + " ", left.cell_len, f"{b} #ffffff")
        else:
            # Known frame but no parsed command — just num + time + frame
            ft = pkt.get("frame_type", "???")
            fw = col_w.get("frame", 5)
            left.append(f" {num_str:<{col_w['num']}} ", style=f"{b} #ffffff")
            left.append(f" {pkt.get('gs_ts_short','??:??:??')} ", style=f"{b} #ffffff")
            left.append(f" {ft:<{fw}} ", style=f"{b} {frame_color(ft)}")
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
        sz_style = f"{b} #555555" if is_sel else f"{b} #999999"
        right.append(f" {len(pkt.get('inner_payload',b''))}B ", style=sz_style)
        if pending_args:
            args_text, indent, args_style = pending_args
            avail = w - left.cell_len - right.cell_len
            if avail >= len(args_text):
                left.append(args_text, style=args_style)
                pending_args = None
        return lr_line(left, right, w, fill_style=b), pending_args


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
    if show_wrapper and pkt.get("stripped_hdr"):
        ft = pkt.get("frame_type", "")
        f("AX.25 HDR", pkt["stripped_hdr"], Style(color=frame_color(ft)))
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
            for ta in cmd.get("typed_args", []): f(ta["name"].upper(), format_arg_value(ta))
            for i, ex in enumerate(cmd.get("extra_args", [])): f(f"ARG +{i}", str(ex))
        else:
            if cmd.get("schema_warning"): lines.append(("⚠", cmd["schema_warning"], S_WARNING))
            for i, a in enumerate(cmd.get("args", [])): f(f"ARG {i}", str(a))
    # CRC: always show if FAIL, otherwise only with wrapper
    crc_st = pkt.get("crc_status", {})
    for label, val, valid, fmt in [
        ("CRC-16", cmd.get("crc") if cmd else None, cmd.get("crc_valid") if cmd else None, "04x"),
        ("CRC-32C", crc_st.get("csp_crc32_rx"), crc_st.get("csp_crc32_valid"), "08x"),
    ]:
        if val is not None and (show_wrapper or not valid):
            f(label, f"0x{val:{fmt}}  [{'OK' if valid else 'FAIL'}]", S_SUCCESS if valid else S_ERROR)
    if show_hex:
        raw = pkt.get("raw", b"")
        if raw: f("HEX", raw.hex(" "), S_DIM)
        if pkt.get("text"): f("ASCII", pkt["text"], S_DIM)
    return lines


class PacketDetail(Widget):
    """Expanded detail view for the selected packet — CSP header fields,
    command routing, CRC verification, hex/ASCII dump, and parsed args."""
    DEFAULT_CSS = "PacketDetail { max-height: 50%; width: 100%; border-top: solid #555555; border-left: solid black; border-right: solid black; }"

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
        if not pkt:
            self.styles.height = 10
            return Text()
        is_unk = pkt.get("is_unknown", False)
        ts_r = pkt.get("ts_result")
        title = Text()
        if is_unk and pkt.get("unknown_num") is not None:
            title.append(f" UNKNOWN U-{pkt['unknown_num']} ", style=S_WARNING)
        else:
            title.append(f" PACKET #{pkt.get('pkt_num',0)} DETAIL ", style="reverse bold #ffffff")
        if ts_r:
            title.append(f" {ts_r[0].strftime('%Y-%m-%d %H:%M:%S')} UTC  {ts_r[1].strftime('%Y-%m-%d %H:%M:%S %Z')}", style="#ffffff")
        lines = _build_detail_lines(pkt, is_unk, s.show_hex, s.show_wrapper)

        # Render lines, wrapping long values with aligned continuation
        max_lbl = max((len(lbl) for lbl, _, _ in lines), default=12)
        label_w = max_lbl + 2  # " " + label + " "
        val_w = max(1, w - label_w)
        rendered_rows = 1  # title
        t = Text()
        t.append_text(lr_line(title, Text(), w))
        for lbl, val, st in lines:
            t.append("\n")
            row = Text()
            row.append(f" {lbl:<{label_w - 1}}", style="#00bfff")
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
        self.styles.height = max(10, rendered_rows + 1)  # +1 for top border, min 10
        return t



# -- Help / Config data -------------------------------------------------------

RX_HELP_LINES = [
    ("MONITORING", None),
    ("Enter", "Toggle detail panel"),
    ("Shift+Down", "Jump to live (auto-follow)"),
    ("Up / Down", "Select packet"),
    ("PgUp / PgDn", "Scroll by page"),
    ("DISPLAY", None),
    ("hex", "Toggle hex dump"),
    ("ul", "Toggle uplink echo visibility"),
    ("wrapper", "Toggle AX.25/CSP/CRC fields"),
    ("INDICATORS", None),
    ("UL", "Uplink echo"),
    ("DUP", "Duplicate packet"),
    ("CRC:OK / CRC:FAIL", "Integrity check result"),
    ("COMMANDS", None),
    ("hclear", "Clear packet history"),
    ("cfg / help", "Open config / help"),
    ("tag <name>", "Tag log file"),
    ("log [name]", "Start new log session"),
    ("q", "Exit"),
]

RX_CONFIG_FIELDS = [("Hex Display", "show_hex", "toggle"), ("Wrapper", "show_wrapper", "toggle"), ("Hide Uplink", "hide_uplink", "toggle")]

def rx_config_get_values(s):
    """Extract current RX config toggle values for the config modal."""
    return {"show_hex": "ON" if s.show_hex else "OFF", "show_wrapper": "ON" if s.show_wrapper else "OFF", "hide_uplink": "ON" if s.hide_uplink else "OFF"}

def rx_help_info(s):
    """Return (version, schema_count, schema_path, log_path) for the help panel."""
    return (s.version, s.schema_count, s.schema_path, s.log.text_path if s.log else "(disabled)")
