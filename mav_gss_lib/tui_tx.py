"""
mav_gss_lib.tui_tx -- TX Dashboard Widgets (Textual)

Author:  Irfan Annuar - USC ISI SERC
"""

from datetime import datetime, timezone
from rich.text import Text
from mav_gss_lib.tui_common import Widget, ScrollableWidget

import mav_gss_lib.protocol as protocol
from mav_gss_lib.protocol import node_label
from mav_gss_lib.tui_common import (
    S_LABEL, S_VALUE, S_SUCCESS, S_WARNING, S_ERROR, S_DIM, S_SEP, lr_line,
    scrollbar_styles, append_wrapped_args,
)


class TxHeader(Widget):
    DEFAULT_CSS = "TxHeader { height: 4; width: 100%; dock: top; }"

    def __init__(self, state, **kw):
        super().__init__(**kw)
        self.s = state

    def render(self):
        s, w = self.s, self.content_size.width
        utc = datetime.now(timezone.utc).strftime("%H:%M:%S")
        local = datetime.now().strftime("%H:%M:%S")
        row1 = Text()
        row1.append(" ZMQ:", style=S_LABEL)
        row1.append(f"{s.zmq_addr_disp} ", style=S_VALUE)
        row1.append(f"[{s.zmq_status}]", style=S_SUCCESS if s.zmq_status == "LIVE" else S_VALUE)
        row1.append(f"  Freq:", style=S_LABEL)
        row1.append(f"{s.freq}", style=S_WARNING)
        row2 = Text()
        row2.append(" LOG:", style=S_LABEL)
        row2.append("ON", style=S_SUCCESS)
        t = Text()
        t.append_text(lr_line(Text(f" MAVERIC TX DASHBOARD", style=S_SUCCESS),
                               Text(f"UTC {utc}  Local {local} ", style=S_VALUE), w))
        t.append("\n" + "─" * w + "\n", style=S_SEP)
        t.append_text(lr_line(row1, Text(), w))
        t.append("\n")
        t.append_text(lr_line(row2, Text(), w))
        return t


class TxQueue(ScrollableWidget):
    DEFAULT_CSS = "TxQueue { height: 1fr; max-height: 33%; width: 100%; }"

    def __init__(self, state, **kw):
        super().__init__(**kw)
        self.s = state

    def _scroll_by(self, delta):
        s = self.s
        count = len(s.tx_queue)
        data_rows = max(1, self.content_size.height - 1)
        s.queue_scroll = max(0, min(count - data_rows, s.queue_scroll + delta))
        self.refresh()

    def render(self):
        s, w, h = self.s, self.content_size.width, self.content_size.height
        q, count = s.tx_queue, len(s.tx_queue)
        title = Text(f" TX QUEUE ({count})  buf: {s.tx_delay_ms}ms", style=S_WARNING)
        if count > 1:
            t_ms = (count - 1) * s.tx_delay_ms
            title.append(f"  total: {t_ms/1000:.1f}s" if t_ms >= 1000 else f"  total: {t_ms}ms", style=S_WARNING)
        t = Text()
        data_rows = h - 1
        ind = Text(f"[{s.queue_scroll+1}-{min(s.queue_scroll+data_rows,count)}/{count}] ", style=S_DIM) if count > data_rows else Text()
        hints = Text("Ctrl+S: send | Ctrl+X: clear ", style=S_DIM)
        # Combine indicator and hints on title line
        right = Text()
        right.append_text(ind)
        right.append_text(hints)
        t.append_text(lr_line(title, right, w))
        if count == 0:
            t.append("\n\n  (empty — type a command below)", style=S_DIM)
            return t
        data_rows -= 1  # account for blank line after title
        # Clamp scroll
        s.queue_scroll = max(0, min(s.queue_scroll, max(0, count - data_rows)))
        sending_idx = s.sending["idx"] if s.sending["active"] else -1
        visible = q[s.queue_scroll:s.queue_scroll + data_rows]
        # Scrollbar
        sb = scrollbar_styles(count, data_rows, s.queue_scroll, data_rows) if count > data_rows else []
        row_w = w - 1 if sb else w
        srcs, dests, echos = set(), set(), set()
        ptypes, nums = set(), []
        for idx, (src, dest, echo, ptype, cmd, args, raw_cmd) in enumerate(visible):
            srcs.add(src); dests.add(dest); echos.add(echo)
            ptypes.add(ptype)
            nums.append(s.queue_scroll + idx + 1)
        nw = max((len(str(n)) for n in nums), default=1)
        sw = max((len(node_label(n)) for n in srcs), default=1)
        dw = max((len(node_label(n)) for n in dests), default=1)
        ew = max((len(node_label(n)) for n in echos), default=1)
        pw = max((len(protocol.PTYPE_NAMES.get(p, str(p))) for p in ptypes), default=1)
        has_non_gs_src = any(src != protocol.GS_NODE for src, *_ in visible)
        # Blank padding line between title and data
        t.append("\n")
        for i, (src, dest, echo, ptype, cmd, args, raw_cmd) in enumerate(visible):
            ai = s.queue_scroll + i
            if sending_idx >= 0 and ai < sending_idx:
                base, tag, ts = "#888888", " SENT", "#44bb66"
            elif sending_idx >= 0 and ai == sending_idx:
                base, tag, ts = "bold #00ff87", " SENDING", "bold #00ff87"
            else:
                base, tag, ts = "", "", ""
            left = Text(style=base)
            left.append(f" #{ai+1:<{nw}} ", style=f"{base} #ffd700" if not base else base)
            if has_non_gs_src:
                left.append(f"{node_label(src):>{sw}} → ", style=f"{base} #00bfff" if not base else base)
            left.append(f"{node_label(dest):<{dw}}  ", style=f"{base} #00bfff" if not base else base)
            left.append(f"E:{node_label(echo):<{ew}}  ", style=f"{base} #888888")
            pt = protocol.PTYPE_NAMES.get(ptype, str(ptype))
            ptype_color = "#00ff87" if ptype == protocol.PTYPE_IDS.get("RES") else "#00bfff"
            left.append(f"{pt:<{pw}}  ", style=f"{base} {ptype_color}" if not base else base)
            left.append(f"{cmd} ", style=f"{base} bold #ffffff" if not base else base)
            args_indent = left.cell_len
            args_style = f"{base} #888888"
            pending_args = None
            rs = f"{tag}  {len(raw_cmd)}B" if tag else f"{len(raw_cmd)}B"
            right = Text(rs + " ", style=ts if tag else "#888888")
            if args:
                avail = row_w - left.cell_len - right.cell_len
                if avail >= len(args):
                    left.append(args, style=args_style)
                else:
                    pending_args = args
            t.append("\n")
            line = lr_line(left, right, row_w)
            if sb:
                line.append(" ", style=sb[i])
            t.append_text(line)
            if pending_args:
                append_wrapped_args(t, pending_args, args_indent, args_style, row_w)
        return t


class SentHistory(ScrollableWidget):
    DEFAULT_CSS = "SentHistory { height: 1fr; width: 100%; }"

    def __init__(self, state, **kw):
        super().__init__(**kw)
        self.s = state

    def _scroll_by(self, delta):
        s = self.s
        count = len(s.history)
        data_rows = max(1, self.content_size.height - 1)
        s.hist_scroll = max(min(data_rows - 1, count - 1), min(count - 1, s.hist_scroll + delta))
        self.refresh()

    def render(self):
        s, w, h = self.s, self.content_size.width, self.content_size.height
        hist, count = s.history, len(s.history)
        t = Text()
        title = Text(f" SENT HISTORY ({count})", style=S_SUCCESS)
        data_rows = h - 1
        if count == 0:
            t.append_text(title)
            t.append("\n\n  (no commands sent yet)", style=S_DIM)
            return t
        data_rows -= 1  # blank line between title and data
        end = min(s.hist_scroll + 1, count)
        start = max(0, end - data_rows)
        ind = Text(f"[{start+1}-{end}/{count}] ", style=S_DIM) if count > data_rows else Text()
        t.append_text(lr_line(title, ind, w))
        t.append("\n\n")
        visible = hist[start:end]
        # Scrollbar
        sb = scrollbar_styles(count, data_rows, start, data_rows) if count > data_rows else []
        row_w = w - 1 if sb else w
        srcs, dests, echos = set(), set(), set()
        ptypes, nums = set(), []
        for rec in visible:
            srcs.add(rec.get('src', protocol.GS_NODE))
            dests.add(rec['dest']); echos.add(rec['echo'])
            ptypes.add(rec['ptype'])
            nums.append(rec['n'])
        nw = max((len(str(n)) for n in nums), default=1)
        sw = max((len(node_label(n)) for n in srcs), default=1)
        dw = max((len(node_label(n)) for n in dests), default=1)
        ew = max((len(node_label(n)) for n in echos), default=1)
        pw = max((len(protocol.PTYPE_NAMES.get(p, '?')) for p in ptypes), default=1)
        has_non_gs_src = any(rec.get('src', protocol.GS_NODE) != protocol.GS_NODE for rec in visible)
        for i, rec in enumerate(visible):
            src = rec.get('src', protocol.GS_NODE)
            left = Text()
            left.append(f" #{rec['n']:<{nw}} ", style=S_SUCCESS)
            left.append(f"{rec['ts']} ", style="#ffffff")
            if has_non_gs_src:
                left.append(f"{node_label(src):>{sw}} → ", style="#00bfff")
            left.append(f"{node_label(rec['dest']):<{dw}}  ", style="#00bfff")
            left.append(f"E:{node_label(rec['echo']):<{ew}}  ", style=S_DIM)
            pt = protocol.PTYPE_NAMES.get(rec['ptype'], '?')
            left.append(f"{pt:<{pw}}  ",
                        style=S_SUCCESS if rec['ptype'] == protocol.PTYPE_IDS.get("RES") else S_LABEL)
            left.append(f"{rec['cmd']} ", style=S_VALUE)
            args_indent = left.cell_len
            pending_args = None
            if rec["args"]:
                right = Text(f"{rec['payload_len']}B ", style=S_DIM)
                avail = row_w - left.cell_len - right.cell_len
                if avail >= len(rec["args"]):
                    left.append(rec["args"], style=S_DIM)
                else:
                    pending_args = rec["args"]
            line = lr_line(left, Text(f"{rec['payload_len']}B ", style=S_DIM), row_w)
            if sb:
                line.append(" ", style=sb[i])
            t.append_text(line)
            t.append("\n")
            if pending_args:
                append_wrapped_args(t, pending_args, args_indent, S_DIM, row_w)
                t.append("\n")
        return t


class TxStatusBar(Widget):
    DEFAULT_CSS = "TxStatusBar { height: 1; width: 100%; }"
    def __init__(self, state, **kw):
        super().__init__(**kw)
        self.s = state
    def render(self):
        t = Text(no_wrap=True, overflow="crop")
        if self.s.status.text:
            t.append(f" {self.s.status.text}", style=S_WARNING)
        t.truncate(self.content_size.width)
        return t


# -- Help / Config data -------------------------------------------------------

HELP_LINES = [
    ("COMMAND FORMAT", None), ("[SRC] DEST ECHO TYPE CMD [ARGS]", ""),
    ("  SRC/DEST/ECHO", "Node name or ID"), ("  TYPE", "REQ|RES|ACK|NONE"),
    ("SRC defaults to GS (6)", ""),
    ("e.g.", "EPS UPPM REQ ping"), ("e.g.", "EPS 2 3 1 set_voltage 3.3"),
    ("KEYS", None), ("Ctrl+S / Ctrl+X", "Send / clear queue"),
    ("Ctrl+Z", "Remove last queued"), ("Up / Down", "History / scroll (focus)"),
    ("Tab / Shift+Tab", "Cycle focus: input/queue/history"),
    ("Mouse wheel", "Scroll focused widget"),
    ("Ctrl+A / Ctrl+E", "Cursor start / end"),
    ("Ctrl+W / Ctrl+U", "Del word / clear input"),
    ("COMMANDS", None), ("send", "Send all queued"), ("undo / pop", "Remove last queued"),
    ("clear / hclear", "Clear queue / history"), ("cfg / help / nodes", "Panels & info"),
    ("imp [file]", "Import from generated_commands/"), ("raw <hex>", "Send raw bytes"), ("q", "Exit"),
]

CONFIG_FIELDS = [
    ("AX.25 Src Call", "ax25_src_call", True), ("AX.25 Src SSID", "ax25_src_ssid", True),
    ("AX.25 Dest Call", "ax25_dest_call", True), ("AX.25 Dest SSID", "ax25_dest_ssid", True),
    ("CSP Priority", "csp_prio", True), ("CSP Source", "csp_src", True),
    ("CSP Destination", "csp_dest", True), ("CSP Dest Port", "csp_dport", True),
    ("CSP Src Port", "csp_sport", True), ("CSP Flags", "csp_flags", True),
    ("Frequency", "freq", True), ("ZMQ Address", "zmq_addr", True),
    ("TX Delay (ms)", "tx_delay_ms", True),
]

def config_get_values(csp, ax25, freq, zmq_addr, tx_delay_ms):
    return {
        "ax25_src_call": ax25.src_call, "ax25_src_ssid": str(ax25.src_ssid),
        "ax25_dest_call": ax25.dest_call, "ax25_dest_ssid": str(ax25.dest_ssid),
        "csp_prio": str(csp.prio), "csp_src": str(csp.src), "csp_dest": str(csp.dest),
        "csp_dport": str(csp.dport), "csp_sport": str(csp.sport), "csp_flags": f"0x{csp.flags:02X}",
        "freq": freq, "zmq_addr": zmq_addr, "tx_delay_ms": str(tx_delay_ms),
    }

def config_apply(values, csp, ax25):
    ax25.src_call = values["ax25_src_call"].upper()[:6]
    ax25.src_ssid = int(values["ax25_src_ssid"])
    ax25.dest_call = values["ax25_dest_call"].upper()[:6]
    ax25.dest_ssid = int(values["ax25_dest_ssid"])
    csp.prio = int(values["csp_prio"], 0); csp.src = int(values["csp_src"], 0)
    csp.dest = int(values["csp_dest"], 0); csp.dport = int(values["csp_dport"], 0)
    csp.sport = int(values["csp_sport"], 0); csp.flags = int(values["csp_flags"], 0)
    return values["freq"], values["zmq_addr"], max(0, int(values["tx_delay_ms"]))

def tx_help_info(s):
    return (s.version, s.schema_count, s.schema_path, s.tx_log.text_path)
