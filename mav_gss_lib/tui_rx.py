"""
mav_gss_lib.tui_rx -- RX Monitor Widgets (Textual)

Author:  Irfan Annuar - USC ISI SERC
"""

from datetime import datetime, timezone
from rich.table import Table
from rich.text import Text
from mav_gss_lib.tui_common import Widget

import mav_gss_lib.protocol as protocol
from mav_gss_lib.protocol import node_label, ptype_label, format_arg_value
from mav_gss_lib.tui_common import (
    S_LABEL, S_VALUE, S_SUCCESS, S_WARNING, S_ERROR, S_DIM, S_SEP, lr_line,
)

class RxHeader(Widget):
    DEFAULT_CSS = "RxHeader { height: 4; width: 100%; dock: top; }"

    def __init__(self, state, zmq_status_ref, queue_ref, **kw):
        super().__init__(**kw)
        self.s, self._zmq, self._q = state, zmq_status_ref, queue_ref

    def render(self):
        s, w = self.s, self.content_size.width
        utc = datetime.now(timezone.utc).strftime("%H:%M:%S")
        local = datetime.now().strftime("%H:%M:%S")
        zmq = Text()
        zmq.append(" ZMQ ", style=S_LABEL)
        zmq.append(f"{s.zmq_addr} ", style=S_VALUE)
        st = self._zmq[0]
        zmq.append(f"[{st}]", style=S_SUCCESS if st == "LIVE" else (S_ERROR if st == "DOWN" else S_VALUE))
        zmq.append(f"  Freq: {s.frequency}", style=S_WARNING)
        tog = Text()
        tog.append("HEX:", style=S_LABEL)
        tog.append("ON" if s.show_hex else "OFF", style=S_SUCCESS if s.show_hex else S_DIM)
        tog.append("  LOG:", style=S_LABEL)
        tog.append("ON" if s.logging_enabled else "OFF", style=S_SUCCESS if s.logging_enabled else S_DIM)
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
    DEFAULT_CSS = "PacketList { height: 1fr; width: 100%; }"

    def __init__(self, state, spinner=None, **kw):
        super().__init__(**kw)
        self.s, self.spinner = state, spinner

    def render(self):
        s, w, h = self.s, self.content_size.width, self.content_size.height
        pkts, count = s.packets, len(s.packets)
        auto = (s.selected_idx == -1)
        t = Text()
        t.append("─" * w + "\n", style=S_SEP)
        title = Text(f" PACKETS ({count})", style=S_SUCCESS)
        title.append("  Auto Scroll:", style=S_LABEL)
        title.append("ON" if auto else "OFF", style=S_SUCCESS if auto else S_DIM)
        data_rows = h - 3  # title + spinner + separator
        if data_rows < 1 or count == 0:
            t.append_text(title)
            if count == 0:
                t.append("\n  (waiting for packets...)", style=S_DIM)
            # Pad to pin spinner at bottom
            used = 2 if count == 0 else 1
            for _ in range(max(0, data_rows - used)):
                t.append("\n")
            t.append("\n")
            t.append_text(self._spinner_line(s, w))
            return t
        if auto:
            end, start = count, max(0, count - data_rows)
        else:
            start, end = s.scroll_offset, min(count, s.scroll_offset + data_rows)
        ind = Text(f"[{start+1}-{end}/{count}] ", style=S_DIM) if count > data_rows else Text()
        t.append_text(lr_line(title, ind, w))
        actual = count - 1 if auto else s.selected_idx
        rendered = end - start
        for i, pkt in enumerate(pkts[start:end]):
            t.append("\n")
            t.append_text(self._pkt_line(pkt, start + i == actual, w))
        # Pad to pin spinner at bottom
        for _ in range(data_rows - rendered):
            t.append("\n")
        t.append("\n")
        t.append_text(self._spinner_line(s, w))
        return t

    def _spinner_line(self, s, w):
        t = Text(no_wrap=True, overflow="crop")
        if s.error_status.text:
            t.append(f" {s.error_status.text}", style=S_ERROR)
        elif s.status.text:
            t.append(f" {s.status.text}", style=S_WARNING)
        elif self.spinner:
            t.append(f" {self.spinner[s.spin_idx]}", style=S_LABEL)
            if s.receiving:
                t.append("  Receiving", style=S_SUCCESS)
            else:
                secs = s.silence_secs
                t.append(f"  Silence: {secs:05.1f}s", style=S_SUCCESS if secs <= 10 else (S_WARNING if secs <= 30 else S_ERROR))
            t.append(f"  {s.pkt_count} pkts", style=S_DIM)
            if s.rate_per_min > 0:
                t.append(f"  {s.rate_per_min:.0f} pkt/min", style=S_DIM)
        return t

    def _pkt_line(self, pkt, is_sel, w):
        b = "reverse" if is_sel else ""
        cmd = pkt.get("cmd")
        left = Text(style=b)
        if pkt.get("is_unknown") and pkt.get("unknown_num") is not None:
            left.append(f" U-{pkt['unknown_num']:<4}", style=f"{b} #ff4444")
        else:
            left.append(f" #{pkt.get('pkt_num',0):<5}", style=f"{b} #888888")
        left.append(f"{pkt.get('gs_ts_short','??:??:??')} ", style=f"{b} #ffffff")
        if pkt.get("is_unknown"):
            left.append("UNKNOWN ", style=f"{b} bold #ff4444")
        else:
            ft = pkt.get("frame_type", "???")
            left.append(f"{ft:<6} ", style=f"{b} {'#ffd700' if ft=='AX.25' else '#00ff87' if ft=='AX100' else '#ff4444'}")
            if cmd:
                left.append(f"{node_label(cmd['src'])} → {node_label(cmd['dest'])} ", style=f"{b} #00bfff")
                left.append(f"E:{node_label(cmd['echo'])} ", style=f"{b} #888888")
                left.append(f"{protocol.PTYPE_NAMES.get(cmd['pkt_type'],'?')} ", style=f"{b} #00bfff")
                left.append(f"{cmd['cmd_id'][:14]} ", style=f"{b} bold #ffffff")
                args = (" ".join([format_arg_value(ta) for ta in cmd.get("typed_args",[])]
                                 + [str(e) for e in cmd.get("extra_args",[])])
                        if cmd.get("schema_match")
                        else " ".join(str(a) for a in cmd.get("args",[])))
                if args:
                    left.append(args, style=f"{b} #888888")
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
        return lr_line(left, right, w, fill_style=b)


class PacketDetail(Widget):
    DEFAULT_CSS = "PacketDetail { height: auto; max-height: 25; width: 100%; }"

    def __init__(self, state, **kw):
        super().__init__(**kw)
        self.s = state

    def render(self):
        s, w = self.s, self.content_size.width
        auto = (s.selected_idx == -1)
        actual = len(s.packets) - 1 if auto and s.packets else s.selected_idx
        pkt = s.packets[actual] if 0 <= actual < len(s.packets) else None
        g = Table.grid(expand=True, padding=(0, 0, 0, 2))
        g.add_column(width=12, style=S_LABEL)
        g.add_column(ratio=1)
        from rich.console import Group
        sep = Text("─" * w, style=S_SEP)
        if not pkt:
            return sep
        is_unk = pkt.get("is_unknown", False)
        if is_unk and pkt.get("unknown_num") is not None:
            title = Text(f" UNKNOWN U-{pkt['unknown_num']}", style=S_ERROR)
        else:
            title = Text(f" PACKET #{pkt.get('pkt_num',0)} DETAIL", style=S_WARNING)
        def f(lbl, val, st=S_VALUE):
            g.add_row(Text(lbl), Text(str(val), style=st))
        if is_unk:
            if s.show_hex:
                raw = pkt.get("raw", b"")
                if raw: f("HEX", raw.hex(" "), S_DIM)
                if pkt.get("text"): f("ASCII", pkt["text"], S_DIM)
                inner = pkt.get("inner_payload", b"")
                if inner: f("SIZE", f"{len(inner)}B (raw {len(raw)}B)", S_DIM)
            return Group(sep, title, g)
        for wm in pkt.get("warnings", []):
            g.add_row(Text("⚠", style=S_ERROR), Text(wm, style=S_ERROR))
        if pkt.get("is_uplink_echo"):
            f("UL ECHO", "Uplink echo — dest/echo not addressed to GS", S_WARNING)
        if pkt.get("stripped_hdr"):
            f("AX.25 HDR", pkt["stripped_hdr"], S_DIM)
        csp = pkt.get("csp")
        if csp:
            tag = "CSP V1" if pkt.get("csp_plausible") else "CSP V1 [?]"
            f(tag, f"Prio:{csp['prio']}  Src:{csp['src']}  Dest:{csp['dest']}  DPort:{csp['dport']}  SPort:{csp['sport']}  Flags:0x{csp['flags']:02x}")
        ts_r = pkt.get("ts_result")
        if ts_r:
            f("SAT TIME", f"{ts_r[0].strftime('%Y-%m-%d %H:%M:%S UTC')}  │  {ts_r[1].strftime('%Y-%m-%d %H:%M:%S %Z')}")
        else:
            f("SAT TIME", "--", S_DIM)
        cmd = pkt.get("cmd")
        if cmd:
            f("CMD", f"Src:{node_label(cmd['src'])}  Dest:{node_label(cmd['dest'])}  Echo:{node_label(cmd['echo'])}  Type:{ptype_label(cmd['pkt_type'])}")
            f("CMD ID", cmd["cmd_id"])
            if cmd.get("schema_match"):
                for ta in cmd.get("typed_args", []): f(ta["name"].upper()[:12], format_arg_value(ta))
                for i, ex in enumerate(cmd.get("extra_args", [])): f(f"ARG +{i}", str(ex))
            else:
                if cmd.get("schema_warning"):
                    g.add_row(Text("⚠", style=S_WARNING), Text(cmd["schema_warning"], style=S_WARNING))
                for i, a in enumerate(cmd.get("args", [])): f(f"ARG {i}", str(a))
        if cmd and cmd.get("crc") is not None:
            v = cmd.get("crc_valid")
            f("CRC-16", f"0x{cmd['crc']:04x}  [{'OK' if v else 'FAIL'}]", S_SUCCESS if v else S_ERROR)
        crc_st = pkt.get("crc_status", {})
        if crc_st.get("csp_crc32_valid") is not None:
            v = crc_st["csp_crc32_valid"]
            f("CRC-32C", f"0x{crc_st['csp_crc32_rx']:08x}  [{'OK' if v else 'FAIL'}]", S_SUCCESS if v else S_ERROR)
        if s.show_hex:
            raw = pkt.get("raw", b"")
            if raw: f("HEX", raw.hex(" "), S_DIM)
        if pkt.get("text"): f("ASCII", pkt["text"], S_DIM)
        return Group(sep, title, g)


class RxStatusBar(Widget):
    DEFAULT_CSS = "RxStatusBar { height: 1; width: 100%; }"

    def __init__(self, state, **kw):
        super().__init__(**kw)
        self.s = state

    def render(self):
        return Text()


# -- Help / Config data -------------------------------------------------------

RX_HELP_LINES = [
    ("KEYS", None), ("Up / Down", "Select packet"), ("PgUp / PgDn", "Scroll page"),
    ("Enter", "Toggle detail"), ("Ctrl+A / Ctrl+E", "Cursor start / end"),
    ("Ctrl+W / Ctrl+U", "Del word / clear input"), ("Ctrl+C", "Quit"),
    ("COMMANDS", None), ("cfg / help", "Toggle panels"), ("hclear", "Clear history"),
    ("hex / log", "Toggle hex / logging"), ("detail / live", "Toggle detail / follow"),
    ("q", "Exit"),
    ("INDICATORS", None), ("[LIVE]", "Auto-follow newest"), ("UL", "Uplink echo"),
    ("DUP", "Duplicate packet"), ("CRC:OK/FAIL", "Integrity check"),
]

RX_CONFIG_FIELDS = [("Hex Display", "show_hex", "toggle"), ("Logging", "logging", "toggle")]

def rx_config_get_values(s):
    return {"show_hex": "ON" if s.show_hex else "OFF", "logging": "ON" if s.logging_enabled else "OFF"}

def _rx_help_info(s):
    return (s.version, s.schema_count, s.schema_path, s.log.text_path if s.log else "(disabled)")
