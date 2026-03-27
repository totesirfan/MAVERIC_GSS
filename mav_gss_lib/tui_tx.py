"""
mav_gss_lib.tui_tx -- TX Dashboard Widgets (Textual)

Author:  Irfan Annuar - USC ISI SERC
"""

from datetime import datetime, timezone
from rich.text import Text
from mav_gss_lib.tui_common import Widget

import mav_gss_lib.protocol as protocol
from mav_gss_lib.protocol import node_label
from mav_gss_lib.tui_common import (
    S_LABEL, S_VALUE, S_SUCCESS, S_WARNING, S_ERROR, S_DIM, S_SEP, lr_line,
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


class TxQueue(Widget):
    DEFAULT_CSS = "TxQueue { height: 1fr; max-height: 33%; width: 100%; }"

    def __init__(self, state, **kw):
        super().__init__(**kw)
        self.s = state

    def render(self):
        s, w, h = self.s, self.content_size.width, self.content_size.height
        q, count = s.tx_queue, len(s.tx_queue)
        title = Text(f" TX QUEUE ({count})  buf: {s.tx_delay_ms}ms", style=S_WARNING)
        if count > 1:
            t_ms = (count - 1) * s.tx_delay_ms
            title.append(f"  total: {t_ms/1000:.1f}s" if t_ms >= 1000 else f"  total: {t_ms}ms", style=S_WARNING)
        t = Text()
        t.append("─" * w + "\n", style=S_SEP)
        t.append_text(lr_line(title, Text("Ctrl+S: send | Ctrl+X: clear ", style=S_DIM), w))
        data_rows = h - 1
        if count == 0:
            t.append("\n  (empty — type a command below)", style=S_DIM)
            return t
        sending_idx = s.sending["idx"] if s.sending["active"] else -1
        for i, (src, dest, echo, ptype, cmd, args, raw_cmd) in enumerate(q[s.queue_scroll:s.queue_scroll + data_rows]):
            ai = s.queue_scroll + i
            if sending_idx >= 0 and ai < sending_idx:
                base, tag, ts = "#888888", " SENT", "#44bb66"
            elif sending_idx >= 0 and ai == sending_idx:
                base, tag, ts = "bold #00ff87", " SENDING", "bold #00ff87"
            else:
                base, tag, ts = "", "", ""
            left = Text(style=base)
            left.append(f" {ai+1:>2}. ", style=f"{base} #ffd700" if not base else base)
            left.append(f"{node_label(src)} → {node_label(dest)} ", style=f"{base} #00bfff" if not base else base)
            left.append(f"E:{node_label(echo)} ", style=f"{base} #888888")
            left.append(f"{protocol.PTYPE_NAMES.get(ptype, str(ptype))} ", style=f"{base} #00bfff" if not base else base)
            left.append(f"{cmd} ", style=f"{base} bold #ffffff" if not base else base)
            if args: left.append(args, style=f"{base} #888888")
            rs = f"{len(raw_cmd)}B"
            if tag: rs = f"{tag}  {rs}"
            t.append("\n")
            t.append_text(lr_line(left, Text(rs + " ", style=ts if tag else "#888888"), w))
        if count > data_rows:
            t.append("\n")
            t.append_text(lr_line(Text(), Text(f"[{s.queue_scroll+1}-{min(s.queue_scroll+data_rows,count)}/{count}] ", style=S_DIM), w))
        return t


class SentHistory(Widget):
    DEFAULT_CSS = "SentHistory { height: 1fr; width: 100%; }"

    def __init__(self, state, **kw):
        super().__init__(**kw)
        self.s = state

    def render(self):
        s, w, h = self.s, self.content_size.width, self.content_size.height
        hist, count = s.history, len(s.history)
        t = Text()
        t.append("─" * w + "\n", style=S_SEP)
        t.append(f" SENT HISTORY ({count})\n", style=S_SUCCESS)
        data_rows = h - 2
        if count == 0:
            t.append("  (no commands sent yet)", style=S_DIM)
            return t
        end = min(s.hist_scroll + 1, count)
        start = max(0, end - data_rows)
        for rec in hist[start:end]:
            left = Text()
            left.append(f" #{rec['n']:<4}", style=S_SUCCESS)
            left.append(f"{rec['ts']} ", style=S_VALUE)
            left.append(f"{node_label(rec.get('src',protocol.GS_NODE))} → {node_label(rec['dest'])} ", style=S_LABEL)
            left.append(f"E:{node_label(rec['echo'])} ", style=S_DIM)
            left.append(f"{protocol.PTYPE_NAMES.get(rec['ptype'],'?')} ", style=S_LABEL)
            left.append(f"{rec['cmd']} ", style=S_VALUE)
            if rec["args"]: left.append(rec["args"], style=S_DIM)
            t.append_text(lr_line(left, Text(f"{rec['payload_len']}B ", style=S_DIM), w))
            t.append("\n")
        if count > data_rows:
            t.append_text(lr_line(Text(), Text(f"[{start+1}-{end}/{count}] ", style=S_DIM), w))
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
    ("Ctrl+Z", "Remove last queued"), ("Up / Down", "History recall"),
    ("PgUp / PgDn", "Scroll history"), ("Ctrl+A / Ctrl+E", "Cursor start / end"),
    ("Ctrl+W / Ctrl+U", "Del word / clear input"),
    ("COMMANDS", None), ("send", "Send all queued"), ("undo / pop", "Remove last queued"),
    ("clear / hclear", "Clear queue / history"), ("cfg / help / nodes", "Panels & info"),
    ("raw <hex>", "Send raw bytes"), ("q", "Exit"),
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

def _tx_help_info(s):
    return (s.version, s.schema_count, s.schema_path, s.tx_log.text_path)
