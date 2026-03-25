"""
mav_gss_lib.logging -- Session Logging

File-based logging for RX and TX sessions. Both produce JSONL
(machine-readable) in logs/json/ and formatted text (human-readable)
in logs/text/, sharing the same visual style via _BaseLog.

Author:  Irfan Annuar - USC ISI SERC
"""

import json
import os
import time
from datetime import datetime

from mav_gss_lib.protocol import node_label, ptype_label, clean_text, format_arg_value, crc16, crc32c

# Line width for text logs
LOG_LINE_WIDTH = 80
SEP_CHAR = "\u2500"      # ─
HEADER_CHAR = "\u2550"   # ═


# =============================================================================
#  BASE LOG
# =============================================================================

class _BaseLog:
    """Shared JSONL + text log infrastructure."""

    def __init__(self, log_dir, prefix, version, mode, zmq_addr,
                 flush_every=10):
        text_dir = os.path.join(log_dir, "text")
        json_dir = os.path.join(log_dir, "json")
        os.makedirs(text_dir, exist_ok=True)
        os.makedirs(json_dir, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.text_path  = os.path.join(text_dir, f"{prefix}_{ts}.txt")
        self.jsonl_path = os.path.join(json_dir, f"{prefix}_{ts}.jsonl")
        self._text_f  = open(self.text_path, "w")
        self._jsonl_f = open(self.jsonl_path, "a")
        self._flush_every = flush_every
        self._writes_since_flush = 0

        # Session header
        session_ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        self._write_text(
            f"{HEADER_CHAR * LOG_LINE_WIDTH}\n"
            f"  MAVERIC Ground Station Log  v{version}\n"
            f"  Mode:      {mode}\n"
            f"  Session:   {session_ts}\n"
            f"  ZMQ:       {zmq_addr}\n"
            f"{HEADER_CHAR * LOG_LINE_WIDTH}\n\n"
        )
        self._text_f.flush()

    # -- Shared helpers -------------------------------------------------------

    def _maybe_flush(self):
        self._writes_since_flush += 1
        if self._writes_since_flush >= self._flush_every:
            self._jsonl_f.flush()
            self._text_f.flush()
            self._writes_since_flush = 0

    def _write_text(self, text):
        self._text_f.write(text)

    def _separator(self, label, extras=""):
        """Build thin separator: ──── #1  timestamp  extras ────────"""
        ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        content = f"{SEP_CHAR * 4} {label}  {ts}  {extras}".rstrip()
        pad = max(0, LOG_LINE_WIDTH - len(content) - 1)
        return content + " " + SEP_CHAR * pad

    @staticmethod
    def _field(label, value):
        """Format a labeled field: '  LABEL       value'"""
        return f"  {label:<12}{value}"

    @staticmethod
    def _hex_lines(data, label="HEX"):
        """Format hex dump at 16 bytes/line with label on first line."""
        if not data:
            return []
        hex_str = data.hex(" ")
        # 16 bytes = 47 chars of hex ("xx " * 15 + "xx")
        chunk_w = 47
        lines = []
        offset = 0
        first = True
        while offset < len(hex_str):
            chunk = hex_str[offset:offset + chunk_w].rstrip()
            if first:
                lines.append(f"  {label:<12}{chunk}")
                first = False
            else:
                lines.append(f"  {'':12}{chunk}")
            offset += chunk_w + 1  # +1 for the space between chunks
        return lines

    @staticmethod
    def _route_line(src, dest, echo, ptype):
        """Format routing fields: Src:x  Dest:x  Echo:x  Type:x"""
        return (f"Src:{node_label(src)}  Dest:{node_label(dest)}  "
                f"Echo:{node_label(echo)}  Type:{ptype_label(ptype)}")

    @staticmethod
    def _format_csp(prio, src, dest, dport, sport, flags):
        """Format CSP header fields."""
        return (f"Prio:{prio}  Src:{src}  Dest:{dest}  "
                f"DPort:{dport}  SPort:{sport}  Flags:0x{flags:02X}")

    def write_jsonl(self, record):
        self._jsonl_f.write(json.dumps(record) + "\n")
        self._maybe_flush()

    def _write_entry(self, lines):
        """Write a complete log entry (list of lines + trailing blank)."""
        self._write_text("\n".join(lines) + "\n\n")
        self._maybe_flush()

    def _write_summary_block(self, summary_lines):
        """Write a summary block with ═ borders."""
        block = [
            "", HEADER_CHAR * LOG_LINE_WIDTH, "  Session Summary", HEADER_CHAR * LOG_LINE_WIDTH,
        ] + summary_lines + [HEADER_CHAR * LOG_LINE_WIDTH, ""]
        self._write_text("\n".join(block) + "\n")
        self._text_f.flush()

    def close(self):
        self._jsonl_f.close()
        self._text_f.close()


# =============================================================================
#  RX SESSION LOG
# =============================================================================

class SessionLog(_BaseLog):
    """RX session log — JSONL + text."""

    def __init__(self, log_dir, zmq_addr, version=""):
        super().__init__(log_dir, "downlink", version, "RX Monitor", zmq_addr)

    def write_packet(self, pkt):
        """Write one RX packet entry. Takes a pkt_record dict."""
        lines = []

        # Separator line
        pkt_num = pkt.get("pkt_num", 0)
        is_unknown = pkt.get("is_unknown", False)
        unknown_num = pkt.get("unknown_num")
        frame_type = pkt.get("frame_type", "???")
        raw = pkt.get("raw", b"")
        inner = pkt.get("inner_payload", b"")
        delta_t = pkt.get("delta_t")
        is_dup = pkt.get("is_dup", False)
        is_uplink_echo = pkt.get("is_uplink_echo", False)

        if is_unknown and unknown_num is not None:
            label = f"U-{unknown_num}"
        else:
            label = f"#{pkt_num}"

        extras = f"{frame_type}  {len(raw)}B \u2192 {len(inner)}B"
        if delta_t is not None:
            extras += f"  \u0394t {delta_t:.3f}s"
        if is_dup:
            extras += "  [DUP]"
        if is_uplink_echo:
            extras += "  [UL]"
        lines.append(self._separator(label, extras))
        if is_uplink_echo:
            banner = "  \u25b2\u25b2\u25b2 UPLINK ECHO \u25b2\u25b2\u25b2"
            lines.append(banner)

        # Warnings
        for w in pkt.get("warnings", []):
            lines.append(self._field("\u26a0 WARNING", w))

        # AX.25 header
        stripped_hdr = pkt.get("stripped_hdr")
        if stripped_hdr:
            lines.append(self._field("AX.25 HDR", stripped_hdr))

        # CSP header
        csp = pkt.get("csp")
        if csp:
            tag = "CSP V1" if pkt.get("csp_plausible") else "CSP V1 [?]"
            lines.append(self._field(tag,
                self._format_csp(csp['prio'], csp['src'], csp['dest'],
                                 csp['dport'], csp['sport'], csp['flags'])))

        # SAT TIME (only when present)
        ts_result = pkt.get("ts_result")
        if ts_result:
            dt_utc, dt_local, raw_ms = ts_result
            lines.append(self._field("SAT TIME",
                f"{dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC')} \u2502 "
                f"{dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')}  ({raw_ms})"))

        # Command
        cmd = pkt.get("cmd")
        if cmd:
            lines.append(self._field("CMD",
                self._route_line(cmd["src"], cmd["dest"], cmd["echo"], cmd["pkt_type"])))
            lines.append(self._field("CMD ID", cmd["cmd_id"]))

            # Schema-matched args
            if cmd.get("schema_match"):
                for ta in cmd.get("typed_args", []):
                    lines.append(self._field(ta["name"].upper(), format_arg_value(ta)))
                for i, extra in enumerate(cmd.get("extra_args", [])):
                    lines.append(self._field(f"ARG +{i}", str(extra)))
            else:
                if cmd.get("schema_warning"):
                    lines.append(self._field("\u26a0 SCHEMA", cmd["schema_warning"]))
                for i, arg in enumerate(cmd.get("args", [])):
                    lines.append(self._field(f"ARG {i}", str(arg)))

        # CRC (before hex)
        if cmd and cmd.get("crc") is not None:
            tag = "OK" if cmd.get("crc_valid") else "FAIL"
            lines.append(self._field("CRC-16", f"0x{cmd['crc']:04x} [{tag}]"))
        crc_status = pkt.get("crc_status", {})
        if crc_status.get("csp_crc32_valid") is not None:
            tag = "OK" if crc_status["csp_crc32_valid"] else "FAIL"
            lines.append(self._field("CRC-32C", f"0x{crc_status['csp_crc32_rx']:08x} [{tag}]"))

        # HEX + ASCII
        lines.extend(self._hex_lines(raw, "HEX"))
        text = pkt.get("text", "")
        if text:
            lines.append(self._field("ASCII", text))

        self._write_entry(lines)

    def write_summary(self, packet_count, session_start, first_pkt_ts, last_pkt_ts,
                      unique=0, duplicates=0, unknown=0, uplink_echoes=0):
        duration = time.time() - session_start
        summary = [
            f"  Packets:   {packet_count} ({unique} unique, {duplicates} dup, "
            f"{unknown} unknown, {uplink_echoes} uplink echo)",
            f"  Duration:  {duration:.1f}s ({duration/60:.1f} min)",
        ]
        if first_pkt_ts and last_pkt_ts:
            summary.append(f"  First:     {first_pkt_ts}")
            summary.append(f"  Last:      {last_pkt_ts}")
        self._write_summary_block(summary)


# =============================================================================
#  TX SESSION LOG
# =============================================================================

class TXLog(_BaseLog):
    """TX session log — JSONL + text."""

    def __init__(self, log_dir, zmq_addr, version=""):
        super().__init__(log_dir, "uplink", version, "TX Dashboard", zmq_addr)

    def write_command(self, n, src, dest, echo, ptype, cmd, args,
                      raw_cmd, payload, ax25, csp):
        """Write one TX command entry with full protocol details."""
        # -- Text entry --
        lines = []

        extras = self._route_line(src, dest, echo, ptype)
        lines.append(self._separator(f"#{n}", extras))

        lines.append(self._field("CMD ID", cmd))
        if args:
            lines.append(self._field("ARGS", args))

        # AX.25 state at time of send
        if ax25.enabled:
            lines.append(self._field("AX.25",
                f"Src:{ax25.src_call}-{ax25.src_ssid}  "
                f"Dest:{ax25.dest_call}-{ax25.dest_ssid}"))
            ax25_hdr = ax25.wrap(b"")  # get just the header (16 bytes)
            lines.extend(self._hex_lines(ax25_hdr, "AX.25 HDR"))

        # CSP state at time of send
        if csp.enabled:
            lines.append(self._field("CSP",
                self._format_csp(csp.prio, csp.src, csp.dest,
                                 csp.dport, csp.sport, csp.flags)))
            lines.extend(self._hex_lines(csp.build_header(), "CSP HDR"))

        # CRC values (computed from the raw command)
        cmd_crc16 = crc16(raw_cmd[:-2]) if len(raw_cmd) >= 2 else None
        if cmd_crc16 is not None:
            lines.append(self._field("CRC-16", f"0x{cmd_crc16:04x} [computed]"))
        if csp.enabled:
            csp_packet = csp.build_header() + raw_cmd
            csp_crc32 = crc32c(csp_packet)
            lines.append(self._field("CRC-32C", f"0x{csp_crc32:08x} [computed]"))

        # Size breakdown
        cmd_len = len(raw_cmd)
        csp_overhead = csp.overhead()
        ax25_overhead = ax25.overhead()
        lines.append(self._field("SIZE",
            f"{len(payload)}B (cmd {cmd_len}B + CSP {csp_overhead}B + AX.25 {ax25_overhead}B)"))

        # Raw command hex + full payload hex
        lines.extend(self._hex_lines(raw_cmd, "RAW CMD"))
        lines.extend(self._hex_lines(payload, "FULL HEX"))
        ascii_text = clean_text(raw_cmd)
        if ascii_text:
            lines.append(self._field("ASCII", ascii_text))

        self._write_entry(lines)

        # -- JSONL entry --
        rec = {
            "n": n,
            "ts": datetime.now().astimezone().isoformat(),
            "src": src,
            "src_lbl": node_label(src),
            "dest": dest,
            "dest_lbl": node_label(dest),
            "echo": echo,
            "echo_lbl": node_label(echo),
            "ptype": ptype,
            "ptype_lbl": ptype_label(ptype),
            "cmd": cmd,
            "args": args,
            "raw_hex": raw_cmd.hex(),
            "raw_len": len(raw_cmd),
            "hex": payload.hex(),
            "len": len(payload),
            "ax25": {
                "enabled": ax25.enabled,
                "src": f"{ax25.src_call}-{ax25.src_ssid}",
                "dest": f"{ax25.dest_call}-{ax25.dest_ssid}",
            },
            "csp": {
                "enabled": csp.enabled,
                "prio": csp.prio,
                "src": csp.src,
                "dest": csp.dest,
                "dport": csp.dport,
                "sport": csp.sport,
                "flags": csp.flags,
            },
        }
        if cmd_crc16 is not None:
            rec["crc16"] = f"0x{cmd_crc16:04x}"
        if csp.enabled:
            rec["crc32c"] = f"0x{csp_crc32:08x}"
        self.write_jsonl(rec)

    def write_summary(self, tx_count, session_start):
        duration = time.time() - session_start
        self._write_summary_block([
            f"  Transmitted: {tx_count}",
            f"  Duration:    {duration:.1f}s ({duration/60:.1f} min)",
        ])
