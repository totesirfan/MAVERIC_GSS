import zmq
import pmt
import re
import struct
import sys
import time
import json
import os
from datetime import datetime, timezone

# --- CONFIGURATION ---
VERSION = "3.1"
ZMQ_PORT = "52001"
ZMQ_ADDR = f"tcp://127.0.0.1:{ZMQ_PORT}"
ZMQ_RECV_TIMEOUT_MS = 200
LOG_DIR = "logs"

# Plausible epoch-ms range (~2024-01-01 to ~2028-01-01)
TS_MIN_MS = 1_704_067_200_000
TS_MAX_MS = 1_830_297_600_000

# ANSI Colors
C_CYAN    = "\033[96m"
C_GREEN   = "\033[92m"
C_YELLOW  = "\033[93m"
C_RED     = "\033[91m"
C_DIM     = "\033[2m"
C_BOLD    = "\033[1m"
C_END     = "\033[0m"


# =============================================================================
#  TRANSPORT
# =============================================================================

def init_zmq(addr, timeout_ms):
    """Initialize ZMQ SUB socket with receive timeout."""
    context = zmq.Context()
    sock = context.socket(zmq.SUB)
    sock.setsockopt(zmq.SUBSCRIBE, b"")
    sock.setsockopt(zmq.RCVHWM, 10000)
    sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sock.connect(addr)
    return context, sock


def receive_pdu(sock):
    """
    Receive and deserialize one PMT PDU from ZMQ.
    Returns (meta_dict, raw_bytes), None on timeout, or raises nothing —
    malformed messages are caught and logged to stderr.
    """
    try:
        msg = sock.recv()
    except zmq.Again:
        return None

    try:
        pdu = pmt.deserialize_str(msg)
        meta = pmt.to_python(pmt.car(pdu))
        raw = bytes(pmt.u8vector_elements(pmt.cdr(pdu)))
    except Exception as e:
        ts = datetime.now().astimezone().strftime("%H:%M:%S")
        print(f"\n  {C_RED}[{ts}] PMT deserialize error: {e} — skipping {len(msg)} bytes{C_END}",
              file=sys.stderr)
        return None

    if meta is None:
        meta = {}

    return meta, raw


# =============================================================================
#  FRAME NORMALIZATION
# =============================================================================

def detect_frame_type(meta):
    """
    Determine frame type from gr-satellites metadata.
    Returns ("AX.25", "AX100", or "UNKNOWN").
    """
    tx_info = str(meta.get("transmitter", ""))
    if not tx_info:
        return "UNKNOWN"
    if "AX.25" in tx_info:
        return "AX.25"
    if "AX100" in tx_info:
        return "AX100"
    return "UNKNOWN"


def normalize_frame(frame_type, raw):
    """
    Strip outer framing and return (inner_payload, stripped_header_hex, warnings).

    For AX.25:  find 03 f0, inner payload starts at idx+2.
    For AX100:  inner payload starts at byte 0 (gr-satellites strips ASM+Golay).
    For UNKNOWN: return raw as-is with a warning.

    Returns (inner_payload_bytes, stripped_header_hex_or_None, list_of_warnings)
    """
    warnings = []

    if frame_type == "AX.25":
        idx = raw.find(b"\x03\xf0")
        if idx == -1:
            warnings.append("AX.25 frame but no 03 f0 delimiter found — returning raw")
            return raw, None, warnings
        header = raw[:idx + 2]
        inner = raw[idx + 2:]
        return inner, header.hex(" "), warnings

    elif frame_type == "AX100":
        # gr-satellites strips ASM+Golay framing; payload should start directly.
        # No additional stripping needed unless you discover otherwise.
        return raw, None, warnings

    else:
        warnings.append("Unknown frame type — cannot strip headers, returning raw")
        return raw, None, warnings


# =============================================================================
#  CANDIDATE PARSERS
# =============================================================================

def try_parse_csp_v1(payload):
    """
    Attempt to parse first 4 bytes as a CSP v1 header.
    Returns (parsed_dict, is_plausible) or (None, False).
    """
    if len(payload) < 4:
        return None, False

    h = int.from_bytes(payload[0:4], "big")
    csp = {
        "prio":  (h >> 30) & 0x03,
        "src":   (h >> 25) & 0x1F,
        "dest":  (h >> 20) & 0x1F,
        "dport": (h >> 14) & 0x3F,
        "sport": (h >> 8)  & 0x3F,
        "flags": h & 0xFF,
    }

    # Plausibility: source and dest should be small node IDs for a cubesat mission.
    # Adjust these ranges based on your actual CSP address plan.
    plausible = csp["src"] <= 20 and csp["dest"] <= 20
    return csp, plausible


def try_extract_timestamp(payload):
    """
    Search for a plausible 13-digit epoch-ms timestamp in the payload.
    Returns (dt_utc, dt_local, raw_ms) or None.
    """
    for match in re.finditer(rb"\d{13}", payload):
        ms = int(match.group())
        if TS_MIN_MS <= ms <= TS_MAX_MS:
            try:
                dt_utc = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
                dt_local = dt_utc.astimezone()
                return dt_utc, dt_local, ms
            except (OSError, ValueError):
                continue
    return None


def scan_numeric(payload):
    """
    Interpret leading bytes of payload as various numeric types.
    Returns dict with both little-endian and big-endian interpretations,
    or None if payload is too short.
    """
    if len(payload) < 8:
        return None

    def safe_float(fmt, data):
        val = struct.unpack(fmt, data)[0]
        if -1e6 < val < 1e6 and val == val:  # exclude NaN
            return f"{val:<12.4f}"
        return "---"

    return {
        "le": {
            "u8":  struct.unpack("<B", payload[0:1])[0],
            "u16": struct.unpack("<H", payload[0:2])[0],
            "u32": struct.unpack("<I", payload[0:4])[0],
            "u64": struct.unpack("<Q", payload[0:8])[0],
            "f32": safe_float("<f", payload[0:4]),
            "f64": safe_float("<d", payload[0:8]),
        },
        "be": {
            "u8":  struct.unpack(">B", payload[0:1])[0],
            "u16": struct.unpack(">H", payload[0:2])[0],
            "u32": struct.unpack(">I", payload[0:4])[0],
            "u64": struct.unpack(">Q", payload[0:8])[0],
            "f32": safe_float(">f", payload[0:4]),
            "f64": safe_float(">d", payload[0:8]),
        },
    }


def clean_text(data: bytes) -> str:
    """Extract printable ASCII from payload."""
    text = data.decode("ascii", errors="ignore")
    return "".join(c for c in text if c.isprintable()).strip()


# =============================================================================
#  LOGGING
# =============================================================================

def strip_ansi(s):
    """Remove ANSI escape codes, return visible text only."""
    return re.sub(r"\033\[[0-9;]*m", "", s)


class SessionLog:
    """Manages persistent file handles for JSONL and text logs."""

    def __init__(self, log_dir, zmq_addr):
        os.makedirs(log_dir, exist_ok=True)
        session_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.jsonl_path = os.path.join(log_dir, f"maveric_{session_ts}.jsonl")
        self.text_path  = os.path.join(log_dir, f"maveric_{session_ts}.txt")

        self._jsonl_f = open(self.jsonl_path, "a")
        self._text_f  = open(self.text_path, "w")

        # Write text log header
        self._text_f.write(f"{'='*80}\n")
        self._text_f.write(f"  MAVERIC Ground Station Log  (GSS v{VERSION})\n")
        self._text_f.write(f"  Session started: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}\n")
        self._text_f.write(f"  ZMQ source:      {zmq_addr}\n")
        self._text_f.write(f"{'='*80}\n\n")
        self._text_f.flush()

    def write_jsonl(self, record):
        self._jsonl_f.write(json.dumps(record) + "\n")
        self._jsonl_f.flush()

    def write_text(self, pkt_num, gs_ts, frame_type, raw, inner_payload,
                   stripped_hdr, csp, csp_plausible, ts_result, scan, text,
                   warnings, delta_t):
        lines = []

        if delta_t is not None:
            lines.append(f"    Delta-T: {delta_t:.3f}s")

        lines.append("-" * 80)
        lines.append(
            f"Packet #{pkt_num:<4} | {gs_ts} | {frame_type:<7} | "
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
                f"Dest: {csp['dest']} | DPort: {csp['dport']} | SPort: {csp['sport']} | "
                f"Flags: 0x{csp['flags']:02x}"
            )

        if ts_result:
            dt_utc, dt_local, raw_ms = ts_result
            lines.append(
                f"  SAT TIME    {dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC')} | "
                f"{dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')}  (epoch-ms: {raw_ms})"
            )
        else:
            lines.append(f"  SAT TIME    --")

        if scan:
            le, be = scan["le"], scan["be"]
            lines.append(
                f"  SCAN little-endian   u8: {le['u8']:<3} | u16: {le['u16']:<5} | "
                f"u32: {le['u32']:<10} | f32: {le['f32']}"
            )
            lines.append(
                f"  SCAN big-endian      u8: {be['u8']:<3} | u16: {be['u16']:<5} | "
                f"u32: {be['u32']:<10} | f32: {be['f32']}"
            )

        lines.append(f"  HEX         {raw.hex(' ')}")
        if text:
            lines.append(f"  ASCII       {text}")

        lines.append("-" * 80)
        lines.append("")

        self._text_f.write("\n".join(lines) + "\n")
        self._text_f.flush()

    def write_summary(self, packet_count, session_start, first_pkt_ts, last_pkt_ts, delta_ts):
        """Write session summary to the text log."""
        duration = time.time() - session_start
        summary = [
            "",
            f"{'='*80}",
            f"  Session Summary",
            f"{'='*80}",
            f"  Packets received:  {packet_count}",
            f"  Session duration:  {duration:.1f}s ({duration/60:.1f} min)",
        ]
        if first_pkt_ts and last_pkt_ts:
            summary.append(f"  First packet:      {first_pkt_ts}")
            summary.append(f"  Last packet:       {last_pkt_ts}")
        if delta_ts:
            avg_dt = sum(delta_ts) / len(delta_ts)
            min_dt = min(delta_ts)
            max_dt = max(delta_ts)
            summary.append(f"  Avg delta-t:       {avg_dt:.3f}s")
            summary.append(f"  Min delta-t:       {min_dt:.3f}s")
            summary.append(f"  Max delta-t:       {max_dt:.3f}s")
        summary.append(f"{'='*80}\n")

        self._text_f.write("\n".join(summary) + "\n")
        self._text_f.flush()

    def close(self):
        self._jsonl_f.close()
        self._text_f.close()


# =============================================================================
#  DISPLAY
# =============================================================================

BOX_W = 80  # total box width including borders
INN_W = BOX_W - 4  # inner content width (│ + space ... space + │)

TOP    = f"┌{'─' * (BOX_W - 2)}┐"
MID    = f"├{'─' * (BOX_W - 2)}┤"
BOT    = f"└{'─' * (BOX_W - 2)}┘"


def _row(content=""):
    """
    Format one box row. Measures visible width by stripping ANSI codes,
    then pads to align the right border.
    """
    visible_len = len(strip_ansi(content))
    pad_needed = INN_W - visible_len
    if pad_needed < 0:
        pad_needed = 0
    return f"{C_DIM}│{C_END} {content}{' ' * pad_needed} {C_DIM}│{C_END}"


def _wrap_hex(hex_str, label, bytes_per_line=20):
    """Wrap a hex string into multiple rows with a label on the first line."""
    parts = hex_str.split(" ")
    lines = []
    for i in range(0, len(parts), bytes_per_line):
        chunk = " ".join(parts[i:i + bytes_per_line])
        if i == 0:
            lines.append(f"{C_GREEN}{label}{C_END} {chunk}")
        else:
            lines.append(f"{'':>{len(label)}} {chunk}")
    return lines


def render_packet(pkt_num, gs_ts, frame_type, raw, inner_payload,
                  stripped_hdr, csp, csp_plausible, ts_result, scan, text,
                  warnings, delta_t):
    """Print formatted packet to terminal."""

    color = C_YELLOW if frame_type == "AX.25" else (C_GREEN if frame_type == "AX100" else C_RED)

    # Delta-T left-aligned above the box
    if delta_t is not None:
        print(f"  {C_DIM}Δt{C_END} {C_CYAN}{delta_t:.3f}s{C_END}")

    # Header — build left and right parts, fill middle with spaces
    print(f"{C_DIM}{TOP}{C_END}")

    h_left  = f"{C_BOLD}{color}PKT #{pkt_num}{C_END}    {color}{frame_type}{C_END}"
    h_mid   = f"{gs_ts}"
    h_right = f"{C_DIM}{len(raw)} B PDU → {len(inner_payload)} B payload{C_END}"

    h_left_vis  = len(f"PKT #{pkt_num}    {frame_type}")
    h_mid_vis   = len(gs_ts)
    h_right_vis = len(f"{len(raw)} B PDU → {len(inner_payload)} B payload")

    gap1 = max(2, (INN_W - h_left_vis - h_mid_vis - h_right_vis) // 2)
    gap2 = INN_W - h_left_vis - h_mid_vis - h_right_vis - gap1

    header = f"{h_left}{' ' * gap1}{h_mid}{' ' * gap2}{h_right}"
    print(_row(header))

    print(f"{C_DIM}{MID}{C_END}")
    print(_row())

    # Warnings
    for w in warnings:
        print(_row(f"{C_RED}  ⚠ {w}{C_END}"))

    # AX.25 stripped header
    if stripped_hdr:
        print(_row(f"  {C_DIM}AX.25 HDR{C_END}   {C_DIM}{stripped_hdr}{C_END}"))
        print(_row())

    # CSP header
    if csp:
        if csp_plausible:
            tag = f"{C_CYAN}CSP V1{C_END}"
        else:
            tag = f"{C_CYAN}CSP V1{C_END} {C_DIM}[UNVERIFIED]{C_END}"

        vals = (f"Prio {C_BOLD}{csp['prio']}{C_END}  "
                f"Src {C_BOLD}{csp['src']}{C_END}  "
                f"Dest {C_BOLD}{csp['dest']}{C_END}  "
                f"DPort {C_BOLD}{csp['dport']}{C_END}  "
                f"SPort {C_BOLD}{csp['sport']}{C_END}  "
                f"Flags {C_BOLD}0x{csp['flags']:02x}{C_END}")

        print(_row(f"  {tag}      {vals}"))

    # Satellite timestamp
    if ts_result:
        dt_utc, dt_local, _ = ts_result
        utc_s = dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC')
        loc_s = dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')
        print(_row(f"  {C_CYAN}SAT TIME{C_END}    {utc_s}  {C_DIM}│{C_END}  {loc_s}"))
    else:
        print(_row(f"  {C_CYAN}SAT TIME{C_END}    {C_DIM}--{C_END}"))

    print(_row())

    # Scanner
    if scan:
        le, be = scan["le"], scan["be"]
        print(_row(
            f"  {C_DIM}SCAN LE{C_END}     "
            f"u8 {C_BOLD}{le['u8']:<3}{C_END}   "
            f"u16 {C_BOLD}{le['u16']:<5}{C_END}   "
            f"u32 {C_BOLD}{le['u32']:<10}{C_END}   "
            f"f32 {C_BOLD}{le['f32']}{C_END}"
        ))
        print(_row(
            f"  {C_DIM}SCAN BE{C_END}     "
            f"u8 {C_BOLD}{be['u8']:<3}{C_END}   "
            f"u16 {C_BOLD}{be['u16']:<5}{C_END}   "
            f"u32 {C_BOLD}{be['u32']:<10}{C_END}   "
            f"f32 {C_BOLD}{be['f32']}{C_END}"
        ))
        print(_row())

    # Hex dump and ASCII
    print(f"{C_DIM}{MID}{C_END}")
    print(_row())

    hex_lines = _wrap_hex(raw.hex(' '), "  HEX  ")
    for hl in hex_lines:
        print(_row(hl))

    print(_row())

    if text:
        print(_row(f"  {C_GREEN}ASCII{C_END}  {text}"))
        print(_row())

    print(f"{C_DIM}{BOT}{C_END}")


# =============================================================================
#  MAIN
# =============================================================================

def main():
    context, sock = init_zmq(ZMQ_ADDR, ZMQ_RECV_TIMEOUT_MS)
    log = SessionLog(LOG_DIR, ZMQ_ADDR)

    packet_count = 0
    last_arrival = None
    last_watchdog = time.time()
    session_start = time.time()
    first_pkt_ts = None
    last_pkt_ts = None
    delta_ts = []

    spinner = ["█", "▓", "▒", "░", "▒", "▓"]
    spin_idx = 0

    print(f"\n{C_BOLD}┌──────────────────────────────────────────────────────────┐")
    print(f"│                       MAVERIC GSS                        │")
    print(f"│                           {C_END}{C_DIM}v{VERSION}{C_END}{C_BOLD}                           │")
    print(f"└──────────────────────────────────────────────────────────┘{C_END}")
    print(f" ZMQ:  {C_BOLD}{ZMQ_ADDR}{C_END}")
    print(f" Logs: {C_BOLD}{log.text_path}{C_END}  (human-readable)")
    print(f"       {C_BOLD}{log.jsonl_path}{C_END}  (machine)\n")

    try:
        while True:
            result = receive_pdu(sock)

            if result is None:
                # --- IDLE / WAITING ---
                elapsed = time.time() - last_watchdog
                tc = C_CYAN if elapsed <= 10 else (C_YELLOW if elapsed <= 30 else C_RED)
                pkt_str = f" | {C_DIM}{packet_count} pkts{C_END}" if packet_count > 0 else ""
                sys.stdout.write(
                    f"\r{C_BOLD}{C_CYAN} {spinner[spin_idx]} {C_END} "
                    f"Waiting... {tc}[SILENCE: {elapsed:04.1f}s]{C_END}{pkt_str}  "
                )
                sys.stdout.flush()
                spin_idx = (spin_idx + 1) % len(spinner)
                continue

            # --- PACKET RECEIVED ---
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
            if delta_t is not None:
                delta_ts.append(delta_t)

            # Phase 1: Detect + normalize
            frame_type = detect_frame_type(meta)
            inner_payload, stripped_hdr, warnings = normalize_frame(frame_type, raw)

            # Phase 2: Candidate parsing on inner payload
            csp, csp_plausible = try_parse_csp_v1(inner_payload)
            ts_result = try_extract_timestamp(inner_payload)
            scan = scan_numeric(inner_payload)
            text = clean_text(inner_payload)

            # Phase 3: Log — machine (JSONL)
            log_record = {
                "v":          VERSION,
                "pkt":        packet_count,
                "gs_ts":      gs_ts,
                "frame_type": frame_type,
                "tx_meta":    str(meta.get("transmitter", "")),
                "raw_hex":    raw.hex(),
                "payload_hex": inner_payload.hex(),
                "raw_len":    len(raw),
                "payload_len": len(inner_payload),
            }
            if delta_t is not None:
                log_record["delta_t"] = round(delta_t, 4)
            if csp:
                log_record["csp_candidate"] = csp
                log_record["csp_plausible"] = csp_plausible
            if ts_result:
                log_record["sat_ts_ms"] = ts_result[2]

            log.write_jsonl(log_record)

            # Phase 3b: Log — human-readable text
            log.write_text(
                packet_count, gs_ts, frame_type, raw, inner_payload,
                stripped_hdr, csp, csp_plausible, ts_result, scan, text,
                warnings, delta_t,
            )

            # Phase 4: Display
            render_packet(
                packet_count, gs_ts, frame_type, raw, inner_payload,
                stripped_hdr, csp, csp_plausible, ts_result, scan, text,
                warnings, delta_t,
            )

    except KeyboardInterrupt:
        # Session summary to text log
        log.write_summary(packet_count, session_start, first_pkt_ts, last_pkt_ts, delta_ts)
        log.close()

        # Terminal summary
        duration = time.time() - session_start
        print(f"\n")
        print(f"{C_DIM}{'─' * 50}{C_END}")
        print(f"  {C_BOLD}Session ended{C_END}")
        print(f"  Packets:    {C_BOLD}{packet_count}{C_END}")
        print(f"  Duration:   {duration:.0f}s ({duration/60:.1f} min)")
        if delta_ts:
            print(f"  Avg Δt:     {sum(delta_ts)/len(delta_ts):.3f}s")
        print(f"{C_DIM}{'─' * 50}{C_END}")
        print(f"  {C_DIM}{log.text_path}{C_END}")
        print(f"  {C_DIM}{log.jsonl_path}{C_END}")
        print()

        sock.close()
        context.term()


if __name__ == "__main__":
    main()