"""
MAV_RX -- MAVERIC Ground Station Monitor

Packet monitor for the MAVERIC CubeSat mission. Subscribes to decoded PDUs
from a GNU Radio / gr-satellites flowgraph over ZMQ PUB/SUB and displays
packet contents for live debugging.

Designed to run continuously. The flowgraph can be started and stopped
independently -- the monitor will idle and resume when packets arrive.

Raw hex is ground truth. All parsed fields (CSP, timestamps, command structure)
are diagnostic until the telemetry map is finalized.

When maveric_commands.yml is present, known commands are parsed deterministically
by the schema. Unknown commands display raw args with a warning.

Author:  Irfan Annuar - USC ISI SERC
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

from mav_gss_lib.protocol import (
    node_label, ptype_label,
    try_parse_csp_v1, try_parse_command,
    clean_text, fingerprint,
    load_command_defs, apply_schema,
    verify_csp_crc32,
)
from mav_gss_lib.display import (
    C, TOP, MID, BOT, INN_W,
    row, strip_ansi, wrap_hex,
    banner, info_line, separator,
)
from mav_gss_lib.transport import init_zmq_sub, receive_pdu

# -- Config -------------------------------------------------------------------

VERSION = "4.2"
ZMQ_PORT = "52001"
ZMQ_ADDR = f"tcp://127.0.0.1:{ZMQ_PORT}"
ZMQ_RECV_TIMEOUT_MS = 200
LOG_DIR = "logs"
CMD_DEFS_PATH = "maveric_commands.yml"


# =============================================================================
#  FRAME NORMALIZATION
# =============================================================================

def detect_frame_type(meta):
    """Determine frame type from gr-satellites metadata.
    Returns 'AX.25', 'AX100', or 'UNKNOWN'."""
    tx_info = str(meta.get("transmitter", ""))
    for frame_type in ("AX.25", "AX100"):
        if frame_type in tx_info:
            return frame_type
    return "UNKNOWN"


def normalize_frame(frame_type, raw):
    """Strip outer framing, return (inner_payload, stripped_header_hex, warnings)."""
    warnings = []

    if frame_type == "AX.25":
        idx = raw.find(b"\x03\xf0")
        if idx == -1:
            warnings.append("AX.25 frame but no 03 f0 delimiter found")
            return raw, None, warnings
        return raw[idx + 2:], raw[:idx + 2].hex(" "), warnings

    if frame_type != "AX100":
        warnings.append("Unknown frame type -- returning raw")

    return raw, None, warnings


# =============================================================================
#  LOGGING
# =============================================================================

class SessionLog:
    """Manages JSONL and text log file handles for one session."""

    def __init__(self, log_dir, zmq_addr, flush_every=10):
        os.makedirs(log_dir, exist_ok=True)
        session_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.jsonl_path = os.path.join(log_dir, f"maveric_{session_ts}.jsonl")
        self.text_path  = os.path.join(log_dir, f"maveric_{session_ts}.txt")
        self._jsonl_f = open(self.jsonl_path, "a")
        self._text_f  = open(self.text_path, "w")
        self._flush_every = flush_every
        self._writes_since_flush = 0

        self._text_f.write(f"{'='*80}\n")
        self._text_f.write(f"  MAVERIC Ground Station Log  (MAV_RX v{VERSION})\n")
        self._text_f.write(f"  Session started: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}\n")
        self._text_f.write(f"  ZMQ source:      {zmq_addr}\n")
        self._text_f.write(f"{'='*80}\n\n")
        self._text_f.flush()

    def _maybe_flush(self):
        self._writes_since_flush += 1
        if self._writes_since_flush >= self._flush_every:
            self._jsonl_f.flush()
            self._text_f.flush()
            self._writes_since_flush = 0

    def write_jsonl(self, record):
        self._jsonl_f.write(json.dumps(record) + "\n")
        self._maybe_flush()

    def write_text(self, pkt_num, gs_ts, frame_type, raw, inner_payload,
                   stripped_hdr, csp, csp_plausible, ts_result, cmd, cmd_tail,
                   text, warnings, delta_t, fp, crc_status, is_dup=False):
        lines = []
        if delta_t is not None:
            lines.append(f"    Delta-T: {delta_t:.3f}s")
        dup_str = " [DUP]" if is_dup else ""
        lines.append("-" * 80)
        lines.append(
            f"Packet #{pkt_num:<4} | {gs_ts} | {frame_type:<7}{dup_str} | "
            f"PDU: {len(raw)} B -> Payload: {len(inner_payload)} B"
        )
        for w in warnings:
            lines.append(f"  WARNING: {w}")
        if stripped_hdr:
            lines.append(f"  AX.25 HDR   {stripped_hdr}")
        if csp:
            tag = "CSP V1" if csp_plausible else "CSP V1 [UNVERIFIED]"
            lines.append(
                f"  {tag}  Prio: {csp['prio']} | Src: {csp['src']} | "
                f"Dest: {csp['dest']} | DPort: {csp['dport']} | "
                f"SPort: {csp['sport']} | Flags: 0x{csp['flags']:02x}"
            )
        if ts_result:
            dt_utc, dt_local, raw_ms = ts_result
            lines.append(
                f"  SAT TIME    {dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC')} | "
                f"{dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')}  (epoch-ms: {raw_ms})"
            )
        else:
            lines.append(f"  SAT TIME    --")
        if cmd:
            lines.append(
                f"  CMD         Src: {node_label(cmd['src'])} | "
                f"Dest: {node_label(cmd['dest'])} | "
                f"Echo: {node_label(cmd['echo'])} | "
                f"Type: {ptype_label(cmd['pkt_type'])}"
            )
            lines.append(f"  CMD ID      {cmd['cmd_id']}")

            # Schema path: named typed args
            if cmd.get("schema_match"):
                for ta in cmd["typed_args"]:
                    label = ta["name"].upper()
                    if ta["type"] == "epoch_ms" and isinstance(ta["value"], dict):
                        lines.append(f"  {label:<12}  {ta['value']['ms']}")
                    else:
                        lines.append(f"  {label:<12}  {ta['value']}")
                for i, extra in enumerate(cmd["extra_args"]):
                    lines.append(f"  ARG +{i}       {extra}")
            # Unknown command: raw args + warning
            else:
                if cmd.get("schema_warning"):
                    lines.append(f"  WARNING: {cmd['schema_warning']}")
                for i, arg in enumerate(cmd['args']):
                    lines.append(f"  ARG {i}       {arg}")

        lines.append(f"  HEX         {raw.hex(' ')}")
        if text:
            lines.append(f"  ASCII       {text}")

        # CRC status
        if cmd and cmd.get('crc') is not None:
            tag = "OK" if cmd.get("crc_valid") else "FAIL"
            lines.append(f"  CRC-16      0x{cmd['crc']:04x}  [{tag}]")
        if crc_status["csp_crc32_valid"] is not None:
            tag = "OK" if crc_status["csp_crc32_valid"] else "FAIL"
            lines.append(f"  CRC-32C     0x{crc_status['csp_crc32_rx']:08x}  [{tag}]")

        lines.append(f"  SHA256      {fp}")
        lines.append("-" * 80)
        lines.append("")
        self._text_f.write("\n".join(lines) + "\n")
        self._maybe_flush()

    def write_summary(self, packet_count, session_start, first_pkt_ts, last_pkt_ts):
        duration = time.time() - session_start
        summary = [
            "", f"{'='*80}", f"  Session Summary", f"{'='*80}",
            f"  Packets received:  {packet_count}",
            f"  Session duration:  {duration:.1f}s ({duration/60:.1f} min)",
        ]
        if first_pkt_ts and last_pkt_ts:
            summary.append(f"  First packet:      {first_pkt_ts}")
            summary.append(f"  Last packet:       {last_pkt_ts}")
        summary.append(f"{'='*80}\n")
        self._text_f.write("\n".join(summary) + "\n")
        self._text_f.flush()

    def close(self):
        self._jsonl_f.close()
        self._text_f.close()


# =============================================================================
#  DISPLAY
# =============================================================================

def render_packet(pkt_num, gs_ts, frame_type, raw, inner_payload,
                  stripped_hdr, csp, csp_plausible, ts_result, cmd,
                  warnings, delta_t, crc_status,
                  loud=False, text=None, fp=None, is_dup=False):
    """Render one received packet inside an 80-column box."""

    color = C.frame_color(frame_type)

    if delta_t is not None:
        print(f"  {C.DIM}\u0394t{C.END} {C.LABEL}{delta_t:.3f}s{C.END}")

    print(f"{C.DIM}{TOP}{C.END}")

    dup_tag = f"  {C.ERROR}[DUP]{C.END}" if is_dup else ""
    dup_vis = 7 if is_dup else 0

    h_left  = f"{C.BOLD}{color}PKT #{pkt_num}{C.END}    {color}{frame_type}{C.END}{dup_tag}"
    h_mid   = f"{gs_ts}"
    h_right = f"{C.DIM}{len(raw)} B PDU \u2192 {len(inner_payload)} B payload{C.END}"

    h_lv = len(f"PKT #{pkt_num}    {frame_type}") + dup_vis
    h_mv = len(gs_ts)
    h_rv = len(f"{len(raw)} B PDU \u2192 {len(inner_payload)} B payload")

    gap1 = max(2, (INN_W - h_lv - h_mv - h_rv) // 2)
    gap2 = INN_W - h_lv - h_mv - h_rv - gap1
    print(row(f"{h_left}{' '*gap1}{h_mid}{' '*gap2}{h_right}"))

    print(f"{C.DIM}{MID}{C.END}")
    print(row())

    for w in warnings:
        print(row(f"{C.ERROR}  \u26a0 {w}{C.END}"))

    if stripped_hdr:
        print(row(f"  {C.DIM}AX.25 HDR{C.END}   {C.DIM}{stripped_hdr}{C.END}"))
        print(row())

    if csp:
        tag = f"{C.LABEL}CSP V1{C.END}" if csp_plausible else f"{C.LABEL}CSP V1{C.END} {C.DIM}[UNVERIFIED]{C.END}"
        vals = (f"Prio {C.VALUE}{csp['prio']}{C.END}  "
                f"Src {C.VALUE}{csp['src']}{C.END}  "
                f"Dest {C.VALUE}{csp['dest']}{C.END}  "
                f"DPort {C.VALUE}{csp['dport']}{C.END}  "
                f"SPort {C.VALUE}{csp['sport']}{C.END}  "
                f"Flags {C.VALUE}0x{csp['flags']:02x}{C.END}")
        print(row(f"  {tag}      {vals}"))

    if ts_result:
        dt_utc, dt_local, _ = ts_result
        utc_s = dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC')
        loc_s = dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')
        print(row(f"  {C.LABEL}SAT TIME{C.END}    {utc_s}  {C.DIM}\u2502{C.END}  {loc_s}"))
    else:
        print(row(f"  {C.LABEL}SAT TIME{C.END}    {C.DIM}--{C.END}"))
    print(row())

    if cmd:
        print(row(
            f"  {C.LABEL}CMD{C.END}         "
            f"Src {C.VALUE}{node_label(cmd['src'])}{C.END}  "
            f"Dest {C.VALUE}{node_label(cmd['dest'])}{C.END}  "
            f"Echo {C.VALUE}{node_label(cmd['echo'])}{C.END}  "
            f"Type {C.VALUE}{ptype_label(cmd['pkt_type'])}{C.END}"
        ))
        print(row(f"  {C.LABEL}CMD ID{C.END}      {C.VALUE}{cmd['cmd_id']}{C.END}"))

        # Schema path: named typed args -- no guessing
        if cmd.get("schema_match"):
            for ta in cmd["typed_args"]:
                label = ta["name"].upper()
                if ta["type"] == "epoch_ms" and isinstance(ta["value"], dict):
                    print(row(f"  {C.LABEL}{label}{C.END}   {C.VALUE}{ta['value']['ms']}{C.END}"))
                else:
                    print(row(f"  {C.LABEL}{label}{C.END}   {C.VALUE}{ta['value']}{C.END}"))
            for i, extra in enumerate(cmd["extra_args"]):
                print(row(f"  {C.LABEL}ARG +{i}{C.END}       {C.VALUE}{extra}{C.END}"))

        # Unknown command: raw args + warning
        else:
            if cmd.get("schema_warning"):
                print(row(f"  {C.WARNING}\u26a0 {cmd['schema_warning']}{C.END}"))
            for i, arg in enumerate(cmd['args']):
                print(row(f"  {C.LABEL}ARG {i}{C.END}       {C.VALUE}{arg}{C.END}"))

        print(row())

    if loud:
        print(f"{C.DIM}{MID}{C.END}")
        print(row())
        for hl in wrap_hex(raw.hex(' ')):
            print(hl)
        print(row())
        if text:
            print(row(f"  {C.DIM}ASCII{C.END}   {C.DIM}{text}{C.END}"))

        # CRC status
        if cmd and cmd.get('crc') is not None:
            valid = cmd.get("crc_valid")
            color = C.SUCCESS if valid else C.ERROR
            tag = "OK" if valid else "FAIL"
            print(row(f"  {C.DIM}CRC-16{C.END}  {color}0x{cmd['crc']:04x}  [{tag}]{C.END}"))

        if crc_status["csp_crc32_valid"] is not None:
            valid = crc_status["csp_crc32_valid"]
            color = C.SUCCESS if valid else C.ERROR
            tag = "OK" if valid else "FAIL"
            print(row(f"  {C.DIM}CRC-32C{C.END} {color}0x{crc_status['csp_crc32_rx']:08x}  [{tag}]{C.END}"))

        if fp:
            print(row(f"  {C.DIM}SHA256{C.END}  {C.DIM}{fp}{C.END}"))
        print(row())

    print(f"{C.DIM}{BOT}{C.END}")


# =============================================================================
#  MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="MAV_RX -- MAVERIC Ground Station Monitor")
    parser.add_argument("--nolog", action="store_true",
                        help="Disable logging to disk")
    parser.add_argument("--loud", action="store_true",
                        help="Show hex dump, ASCII, SHA256")
    args = parser.parse_args()

    context, sock = init_zmq_sub(ZMQ_ADDR, ZMQ_RECV_TIMEOUT_MS)
    log = None if args.nolog else SessionLog(LOG_DIR, ZMQ_ADDR)
    loud = args.loud

    # Load command schema -- empty dict if file missing or no PyYAML
    cmd_defs = load_command_defs(CMD_DEFS_PATH)

    packet_count = 0
    last_arrival = None
    last_watchdog = time.time()
    session_start = time.time()
    first_pkt_ts = None
    last_pkt_ts = None
    seen_fps = set()
    pkt_times = []
    last_render = 0.0
    render_skipped = 0
    RENDER_INTERVAL = 0.25

    spinner = ["\u2588", "\u2593", "\u2592", "\u2591", "\u2592", "\u2593"]
    spin_idx = 0

    banner("MAVERIC RX", VERSION)
    print()
    info_line("ZMQ", ZMQ_ADDR)
    info_line("Timeout", f"{ZMQ_RECV_TIMEOUT_MS}ms")
    info_line("Display", "loud" if loud else "normal")
    if cmd_defs:
        info_line("Schema", f"{len(cmd_defs)} commands from {CMD_DEFS_PATH}")
    else:
        print(f" {C.WARNING}{'Schema':<12}MISSING -- unknown commands will not be parsed{C.END}")
    if log:
        print(f" {C.DIM}Log (txt){C.END}  {log.text_path}")
        print(f" {C.DIM}Log (json){C.END} {log.jsonl_path}")
    else:
        print(f" {C.DIM}Logging{C.END}     disabled")
    print()

    try:
        while True:
            result = receive_pdu(sock)

            if result is None:
                elapsed = time.time() - last_watchdog
                if elapsed <= 10:
                    tc = C.LABEL
                elif elapsed <= 30:
                    tc = C.WARNING
                else:
                    tc = C.ERROR
                pkt_str = f" | {C.DIM}{packet_count} pkts{C.END}" if packet_count > 0 else ""
                if pkt_times:
                    cutoff = time.time() - 60.0
                    recent = sum(1 for t in pkt_times if t > cutoff)
                    if recent > 0:
                        pkt_str += f" | {C.DIM}{recent:.0f} pkt/min{C.END}"
                sys.stdout.write(
                    f"\r{C.BOLD}{C.LABEL} {spinner[spin_idx]} {C.END} "
                    f"Waiting... {tc}[SILENCE: {elapsed:04.1f}s]{C.END}{pkt_str}  "
                )
                sys.stdout.flush()
                spin_idx = (spin_idx + 1) % len(spinner)
                continue

            # -- Packet received --
            meta, raw = result
            now = time.time()
            sys.stdout.write("\r" + " " * 80 + "\r")

            delta_t = (now - last_arrival) if last_arrival is not None else None
            last_arrival = now
            last_watchdog = now
            packet_count += 1
            gs_ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
            if first_pkt_ts is None:
                first_pkt_ts = gs_ts
            last_pkt_ts = gs_ts

            # Phase 1: Detect + normalize
            frame_type = detect_frame_type(meta)
            inner_payload, stripped_hdr, warnings = normalize_frame(frame_type, raw)

            # Phase 2: Parse
            csp, csp_plausible = try_parse_csp_v1(inner_payload)
            fp = fingerprint(raw)

            cmd, cmd_tail = (None, None)
            ts_result = None

            if len(inner_payload) > 4:
                cmd, cmd_tail = try_parse_command(inner_payload[4:])
                if cmd:
                    apply_schema(cmd, cmd_defs)

            # CRC-32C verification (over full CSP packet)
            crc_valid, crc_rx, crc_comp = (None, None, None)
            if cmd and cmd.get("csp_crc32") is not None:
                crc_valid, crc_rx, crc_comp = verify_csp_crc32(inner_payload)
                if crc_valid is False:
                    warnings.append(f"CRC-32C mismatch: rx 0x{crc_rx:08x} != computed 0x{crc_comp:08x}")
            crc_status = {"csp_crc32_valid": crc_valid, "csp_crc32_rx": crc_rx, "csp_crc32_comp": crc_comp}

            # SAT TIME: only available from schema-resolved epoch_ms fields
            if cmd and cmd.get("sat_time"):
                ts_result = cmd["sat_time"]

            text = clean_text(inner_payload)

            is_dup = fp in seen_fps
            seen_fps.add(fp)
            pkt_times.append(now)
            pkt_times[:] = [t for t in pkt_times if t > now - 60.0]

            # Phase 3: Log
            if log:
                log_record = {
                    "v": VERSION, "pkt": packet_count, "gs_ts": gs_ts,
                    "frame_type": frame_type,
                    "tx_meta": str(meta.get("transmitter", "")),
                    "raw_hex": raw.hex(), "payload_hex": inner_payload.hex(),
                    "raw_len": len(raw), "payload_len": len(inner_payload),
                    "sha256": fp, "duplicate": is_dup,
                }
                if delta_t is not None:
                    log_record["delta_t"] = round(delta_t, 4)
                if csp:
                    log_record["csp_candidate"] = csp
                    log_record["csp_plausible"] = csp_plausible
                if ts_result:
                    log_record["sat_ts_ms"] = ts_result[2]

                # CRC status in log
                if crc_status["csp_crc32_valid"] is not None:
                    log_record["csp_crc32"] = {
                        "valid": crc_status["csp_crc32_valid"],
                        "received": f"0x{crc_status['csp_crc32_rx']:08x}",
                    }

                if cmd:
                    cmd_log = {
                        "src": cmd["src"], "dest": cmd["dest"],
                        "echo": cmd["echo"], "pkt_type": cmd["pkt_type"],
                        "cmd_id": cmd["cmd_id"], "crc": cmd["crc"],
                        "crc_valid": cmd.get("crc_valid"),
                    }

                    # Schema path: log typed args as named fields
                    if cmd.get("schema_match"):
                        typed_log = {}
                        for ta in cmd["typed_args"]:
                            if ta["type"] == "epoch_ms" and isinstance(ta["value"], dict):
                                typed_log[ta["name"]] = ta["value"]["ms"]
                            else:
                                typed_log[ta["name"]] = ta["value"]
                        cmd_log["args"] = typed_log
                        if cmd["extra_args"]:
                            cmd_log["extra_args"] = cmd["extra_args"]
                    # Unknown command: log raw args as list
                    else:
                        cmd_log["args"] = cmd["args"]
                        if cmd.get("schema_warning"):
                            cmd_log["schema_warning"] = cmd["schema_warning"]

                    log_record["cmd"] = cmd_log
                    if cmd_tail:
                        log_record["tail_hex"] = cmd_tail.hex()

                log.write_jsonl(log_record)
                log.write_text(
                    packet_count, gs_ts, frame_type, raw, inner_payload,
                    stripped_hdr, csp, csp_plausible, ts_result, cmd, cmd_tail,
                    text, warnings, delta_t, fp, crc_status, is_dup,
                )

            # Phase 4: Display (throttled)
            if now - last_render >= RENDER_INTERVAL:
                if render_skipped > 0:
                    recent = sum(1 for t in pkt_times if t > now - 60.0)
                    print(f"  {C.DIM}... +{render_skipped} received | "
                          f"{packet_count} total | {recent} pkt/min{C.END}")
                render_packet(
                    packet_count, gs_ts, frame_type, raw, inner_payload,
                    stripped_hdr, csp, csp_plausible, ts_result, cmd,
                    warnings, None if render_skipped > 0 else delta_t,
                    crc_status, loud, text, fp, is_dup,
                )
                last_render = now
                render_skipped = 0
            else:
                render_skipped += 1

    except KeyboardInterrupt:
        if log:
            log.write_summary(packet_count, session_start, first_pkt_ts, last_pkt_ts)
            log.close()

        duration = time.time() - session_start
        dup_count = packet_count - len(seen_fps)
        print(f"\n")
        separator()
        print(f"  {C.BOLD}Session ended{C.END}")
        print(f"  Packets:    {C.BOLD}{packet_count}{C.END}  "
              f"({len(seen_fps)} unique, {dup_count} duplicate)")
        print(f"  Duration:   {duration:.0f}s ({duration/60:.1f} min)")
        separator()
        if log:
            print(f"  {C.DIM}{log.text_path}{C.END}")
            print(f"  {C.DIM}{log.jsonl_path}{C.END}")
        print()
        sock.close()
        context.term()


if __name__ == "__main__":
    main()