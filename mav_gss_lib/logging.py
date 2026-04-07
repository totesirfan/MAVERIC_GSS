"""
mav_gss_lib.logging -- Session Logging

File-based logging for RX and TX sessions. Both produce JSONL
(machine-readable) in logs/json/ and formatted text (human-readable)
in logs/text/, sharing the same visual style via _BaseLog.

Author:  Irfan Annuar - USC ISI SERC
"""

import json
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime

from mav_gss_lib.textutil import clean_text
from mav_gss_lib.protocols.crc import crc16, crc32c

TS_FULL = "%Y-%m-%d %H:%M:%S %Z"   # Full timestamp with timezone

# Line width for text logs
LOG_LINE_WIDTH = 80
SEP_CHAR = "\u2500"      # ─
HEADER_CHAR = "\u2550"   # ═


# =============================================================================
#  BASE LOG
# =============================================================================

class _BaseLog:
    """Shared JSONL + text log infrastructure.

    All file I/O runs on a dedicated background thread so that callers
    (typically the Textual event loop) never block on disk flushes.
    """

    _SENTINEL = None  # poison pill to stop the writer thread

    def __init__(self, log_dir, prefix, version, mode, zmq_addr, mission_name="MAVERIC"):
        self._log_dir = log_dir
        self._prefix = prefix
        self._version = version
        self._mode = mode
        self._zmq_addr = zmq_addr
        self._mission_name = mission_name
        self._q_lock = threading.Lock()  # guards _q replacement during new_session
        os.makedirs(os.path.join(log_dir, "text"), exist_ok=True)
        os.makedirs(os.path.join(log_dir, "json"), exist_ok=True)
        self._open_files()

    def _writer_loop(self):
        """Drain the write queue until sentinel received, then flush remaining."""
        while True:
            item = self._q.get()
            if item is self._SENTINEL:
                # Drain any items queued before the sentinel
                while not self._q.empty():
                    try:
                        remaining = self._q.get_nowait()
                        if remaining is self._SENTINEL:
                            continue
                        self._process_item(remaining)
                    except Exception:
                        break
                break
            try:
                self._process_item(item)
            except Exception as e:
                print(f"WARNING: log write failed ({e}), continuing", file=sys.stderr)

    def _process_item(self, item):
        """Process a single queue item."""
        kind, data = item
        if kind == "jsonl":
            self._jsonl_f.write(data)
            self._jsonl_f.flush()
        elif kind == "text":
            self._text_f.write(data)
            self._text_f.flush()
        elif kind == "rename":
            new_text, new_jsonl = data
            self._text_f.close(); self._jsonl_f.close()
            os.rename(self.text_path, new_text)
            os.rename(self.jsonl_path, new_jsonl)
            self.text_path, self.jsonl_path = new_text, new_jsonl
            self._text_f = open(new_text, "a", buffering=1)
            self._jsonl_f = open(new_jsonl, "a", buffering=1)

    # -- Shared helpers -------------------------------------------------------

    def _write_text(self, text):
        with self._q_lock:
            self._q.put(("text", text))

    def _separator(self, label, extras=""):
        """Build thin separator: ──── #1  timestamp  extras ────────"""
        ts = datetime.now().astimezone().strftime(TS_FULL)
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
    def _route_line(src, dest, echo, ptype, adapter=None):
        """Format routing fields: Src:x  Dest:x  Echo:x  Type:x"""
        nl = adapter.node_label if adapter else str
        pl = adapter.ptype_label if adapter else str
        return (f"Src:{nl(src)}  Dest:{nl(dest)}  "
                f"Echo:{nl(echo)}  Type:{pl(ptype)}")

    @staticmethod
    def _format_csp(prio, src, dest, dport, sport, flags):
        """Format CSP header fields."""
        return (f"Prio:{prio}  Src:{src}  Dest:{dest}  "
                f"DPort:{dport}  SPort:{sport}  Flags:0x{flags:02X}")

    def write_jsonl(self, record):
        with self._q_lock:
            self._q.put(("jsonl", json.dumps(record) + "\n"))

    def _write_entry(self, lines):
        """Write a complete log entry (list of lines + trailing blank)."""
        with self._q_lock:
            self._q.put(("text", "\n".join(lines) + "\n\n"))

    def _write_summary_block(self, summary_lines):
        """Write a summary block with ═ borders."""
        block = [
            "", HEADER_CHAR * LOG_LINE_WIDTH, "  Session Summary", HEADER_CHAR * LOG_LINE_WIDTH,
        ] + summary_lines + [HEADER_CHAR * LOG_LINE_WIDTH, ""]
        with self._q_lock:
            self._q.put(("text", "\n".join(block) + "\n"))

    def _open_files(self, tag=""):
        """Open new log files with fresh timestamp, write header, start writer thread."""
        tag = re.sub(r'[^\w\-.]', '_', tag.strip()).strip('_') if tag else ""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{self._prefix}_{ts}_{tag}" if tag else f"{self._prefix}_{ts}"
        self.text_path = os.path.join(self._log_dir, "text", f"{name}.txt")
        self.jsonl_path = os.path.join(self._log_dir, "json", f"{name}.jsonl")
        self._text_f = open(self.text_path, "w", buffering=1)
        self._jsonl_f = open(self.jsonl_path, "a", buffering=1)
        session_ts = datetime.now().astimezone().strftime(TS_FULL)
        self._text_f.write(
            f"{HEADER_CHAR * LOG_LINE_WIDTH}\n"
            f"  {self._mission_name} Ground Station Log  v{self._version}\n"
            f"  Mode:      {self._mode}\n"
            f"  Session:   {session_ts}\n"
            f"  ZMQ:       {self._zmq_addr}\n"
            f"{HEADER_CHAR * LOG_LINE_WIDTH}\n\n"
        )
        self._text_f.flush()
        self._q = queue.Queue()
        self._writer = threading.Thread(target=self._writer_loop,
                                        name="log-writer", daemon=True)
        self._writer.start()

    def new_session(self, tag=""):
        """Close current log files and start a new session."""
        with self._q_lock:
            self._q.put(self._SENTINEL)
        self._writer.join(timeout=5.0)
        if not self._writer.is_alive():
            self._text_f.close(); self._jsonl_f.close()
        with self._q_lock:
            self._open_files(tag)

    def rename(self, tag):
        """Rename log files by appending a sanitized tag before the extension."""
        tag = re.sub(r'[^\w\-.]', '_', tag.strip()).strip('_')
        if not tag:
            return
        def _new_path(path):
            base, ext = os.path.splitext(path)
            return f"{base}_{tag}{ext}"
        new_text, new_jsonl = _new_path(self.text_path), _new_path(self.jsonl_path)
        if sys.platform == "win32":
            self._q.put(("rename", (new_text, new_jsonl)))
        else:
            os.rename(self.text_path, new_text)
            os.rename(self.jsonl_path, new_jsonl)
            self.text_path, self.jsonl_path = new_text, new_jsonl

    def close(self):
        self._q.put(self._SENTINEL)
        self._writer.join(timeout=5.0)
        if not self._writer.is_alive():
            self._jsonl_f.close()
            self._text_f.close()


# =============================================================================
#  RX SESSION LOG
# =============================================================================

class SessionLog(_BaseLog):
    """RX session log — JSONL + text."""

    def __init__(self, log_dir, zmq_addr, version="", mission_name="MAVERIC"):
        super().__init__(log_dir, "downlink", version, "RX Monitor", zmq_addr, mission_name=mission_name)

    def write_packet(self, pkt, adapter=None):
        """Write one RX packet entry. Takes a Packet instance.

        Platform handles: separator, warnings, hex dump, ASCII.
        Adapter handles: mission-specific text lines (protocol headers,
        command details, CRC display) via format_log_lines().
        """
        lines = []
        label = f"U-{pkt.unknown_num}" if pkt.is_unknown and pkt.unknown_num is not None else f"#{pkt.pkt_num}"
        extras = f"{pkt.frame_type}  {len(pkt.raw)}B \u2192 {len(pkt.inner_payload)}B"
        if pkt.delta_t is not None: extras += f"  \u0394t {pkt.delta_t:.3f}s"
        if pkt.is_dup: extras += "  [DUP]"
        if pkt.is_uplink_echo: extras += "  [UL]"
        lines.append(self._separator(label, extras))
        if pkt.is_uplink_echo:
            lines.append("  \u25b2\u25b2\u25b2 UPLINK ECHO \u25b2\u25b2\u25b2")

        # Warnings
        for w in pkt.warnings:
            lines.append(self._field("\u26a0 WARNING", w))

        # Mission-specific lines (adapter-driven)
        if adapter is not None:
            lines.extend(adapter.format_log_lines(pkt))

        lines.extend(self._hex_lines(pkt.raw, "HEX"))
        if pkt.text:
            lines.append(self._field("ASCII", pkt.text))

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

    def __init__(self, log_dir, zmq_addr, version="", mission_name="MAVERIC"):
        super().__init__(log_dir, "uplink", version, "TX Dashboard", zmq_addr, mission_name=mission_name)

    def write_command(self, n, src, dest, echo, ptype, cmd, args,
                      raw_cmd, payload, ax25, csp, uplink_mode="AX.25", adapter=None):
        """Write one TX command entry with full protocol details."""
        nl = adapter.node_label if adapter else str
        pl = adapter.ptype_label if adapter else str
        # -- Text entry --
        lines = []

        extras = self._route_line(src, dest, echo, ptype, adapter=adapter)
        lines.append(self._separator(f"#{n}", extras))

        lines.append(self._field("MODE", uplink_mode))
        lines.append(self._field("CMD ID", cmd))
        if args:
            lines.append(self._field("ARGS", args))

        # AX.25 state at time of send (skip for ASM+Golay)
        if uplink_mode != "ASM+Golay" and ax25.enabled:
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
        if uplink_mode == "ASM+Golay":
            lines.append(self._field("SIZE",
                f"{len(payload)}B (cmd {cmd_len}B + CSP {csp_overhead}B -> RS 255B + overhead 57B)"))
        else:
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
            "n": n, "ts": datetime.now().astimezone().isoformat(),
            "uplink_mode": uplink_mode,
            "src": src, "src_lbl": nl(src),
            "dest": dest, "dest_lbl": nl(dest),
            "echo": echo, "echo_lbl": nl(echo),
            "ptype": ptype, "ptype_lbl": pl(ptype),
            "cmd": cmd, "args": args,
            "raw_hex": raw_cmd.hex(), "raw_len": len(raw_cmd),
            "hex": payload.hex(), "len": len(payload),
            "ax25": {"enabled": ax25.enabled,
                     "src": f"{ax25.src_call}-{ax25.src_ssid}",
                     "dest": f"{ax25.dest_call}-{ax25.dest_ssid}"},
            "csp": {"enabled": csp.enabled, "prio": csp.prio, "src": csp.src,
                    "dest": csp.dest, "dport": csp.dport, "sport": csp.sport,
                    "flags": csp.flags},
        }
        if cmd_crc16 is not None:
            rec["crc16"] = f"0x{cmd_crc16:04x}"
        if csp.enabled:
            rec["crc32c"] = f"0x{csp_crc32:08x}"
        self.write_jsonl(rec)

    def write_mission_command(self, n, display, mission_payload,
                              raw_cmd, payload, ax25, csp, uplink_mode="AX.25"):
        """Write one mission-built TX command entry with protocol details."""
        title = display.get("title", "?")
        subtitle = display.get("subtitle", "")

        lines = []
        lines.append(self._separator(f"#{n}", subtitle))
        lines.append(self._field("MODE", uplink_mode))
        lines.append(self._field("COMMAND", title))
        for field in display.get("fields", []):
            lines.append(self._field(field["name"].upper(), str(field["value"])))

        if uplink_mode != "ASM+Golay" and ax25.enabled:
            lines.append(self._field("AX.25",
                f"Src:{ax25.src_call}-{ax25.src_ssid}  "
                f"Dest:{ax25.dest_call}-{ax25.dest_ssid}"))

        if csp.enabled:
            lines.append(self._field("CSP",
                self._format_csp(csp.prio, csp.src, csp.dest,
                                 csp.dport, csp.sport, csp.flags)))

        cmd_len = len(raw_cmd)
        csp_overhead = csp.overhead()
        if uplink_mode == "ASM+Golay":
            lines.append(self._field("SIZE",
                f"{len(payload)}B (cmd {cmd_len}B + CSP {csp_overhead}B)"))
        else:
            ax25_overhead = ax25.overhead()
            lines.append(self._field("SIZE",
                f"{len(payload)}B (cmd {cmd_len}B + CSP {csp_overhead}B + AX.25 {ax25_overhead}B)"))

        lines.extend(self._hex_lines(raw_cmd, "RAW CMD"))
        lines.extend(self._hex_lines(payload, "FULL HEX"))
        ascii_text = clean_text(raw_cmd)
        if ascii_text:
            lines.append(self._field("ASCII", ascii_text))

        self._write_entry(lines)

        rec = {
            "n": n, "ts": datetime.now().astimezone().isoformat(),
            "type": "mission_cmd",
            "uplink_mode": uplink_mode,
            "display": display,
            "mission_payload": mission_payload,
            "raw_hex": raw_cmd.hex(), "raw_len": len(raw_cmd),
            "hex": payload.hex(), "len": len(payload),
        }
        self.write_jsonl(rec)

    def write_summary(self, tx_count, session_start):
        duration = time.time() - session_start
        self._write_summary_block([
            f"  Transmitted: {tx_count}",
            f"  Duration:    {duration:.1f}s ({duration/60:.1f} min)",
        ])
