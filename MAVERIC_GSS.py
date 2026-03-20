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
    Returns (meta_dict, raw_bytes) or None on timeout.
    """
    try:
        msg = sock.recv()
    except zmq.Again:
        return None

    pdu = pmt.deserialize_str(msg)
    meta = pmt.to_python(pmt.car(pdu))
    raw = bytes(pmt.u8vector_elements(pmt.cdr(pdu)))

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

def init_logs(log_dir):
    """Create log directory and return paths for JSONL and human-readable logs."""
    os.makedirs(log_dir, exist_ok=True)
    session_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    jsonl_path = os.path.join(log_dir, f"maveric_{session_ts}.jsonl")
    text_path  = os.path.join(log_dir, f"maveric_{session_ts}.txt")

    # Write text log header
    with open(text_path, "w") as f:
        f.write(f"{'='*80}\n")
        f.write(f"  MAVERIC Ground Station Log\n")
        f.write(f"  Session started: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}\n")
        f.write(f"  ZMQ source:      {ZMQ_ADDR}\n")
        f.write(f"{'='*80}\n\n")

    return jsonl_path, text_path


def log_packet_jsonl(jsonl_path, record):
    """Append one JSON-lines record to the machine-readable log."""
    with open(jsonl_path, "a") as f:
        f.write(json.dumps(record) + "\n")


def log_packet_text(text_path, pkt_num, gs_ts, frame_type, raw, inner_payload,
                    stripped_hdr, csp, csp_plausible, ts_result, scan, text,
                    warnings, delta_t):
    """Append a human-readable packet entry to the text log."""
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
        tag = "CSP v1" if csp_plausible else "CSP v1 [UNVERIFIED]"
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
    lines.append("")  # blank line between packets

    with open(text_path, "a") as f:
        f.write("\n".join(lines) + "\n")


# =============================================================================
#  DISPLAY
# =============================================================================

SEPARATOR = "─" * 80


def render_packet(pkt_num, gs_ts, frame_type, raw, inner_payload,
                  stripped_hdr, csp, csp_plausible, ts_result, scan, text,
                  warnings, delta_t):
    """Print formatted packet to terminal."""

    color = C_YELLOW if frame_type == "AX.25" else (C_GREEN if frame_type == "AX100" else C_RED)

    if delta_t is not None:
        print(f"    Delta-T: {C_CYAN}{delta_t:.3f}s{C_END}")

    print(SEPARATOR)
    print(
        f"{C_BOLD}{color}Packet #{pkt_num:<4}{C_END} | {gs_ts} | "
        f"{color}{frame_type:<7}{C_END} | {C_BOLD}PDU: {len(raw)} B{C_END} → "
        f"{C_BOLD}Payload: {len(inner_payload)} B{C_END}"
    )

    for w in warnings:
        print(f" {C_RED}⚠ {w}{C_END}")

    if stripped_hdr:
        print(f" {C_DIM}AX.25 HDR  {stripped_hdr}{C_END}")

    if csp:
        tag = "CSP v1" if csp_plausible else f"CSP v1 {C_DIM}[UNVERIFIED]{C_END}"
        print(
            f" {C_CYAN}{tag} │ Prio: {csp['prio']} | Src: {csp['src']} | "
            f"Dest: {csp['dest']} | DPort: {csp['dport']} | SPort: {csp['sport']} | "
            f"Flags: 0x{csp['flags']:02x}{C_END}"
        )

    if ts_result:
        dt_utc, dt_local, _ = ts_result
        print(
            f" SAT TIME   {dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC')} | "
            f"{dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        )
    else:
        print(f" SAT TIME   {C_DIM}No plausible timestamp found{C_END}")

    if scan:
        le, be = scan["le"], scan["be"]
        print(
            f" {C_BOLD}SCAN{C_END} {C_DIM}little-endian{C_END}  u8: {le['u8']:<3} | u16: {le['u16']:<5} | "
            f"u32: {le['u32']:<10} | f32: {le['f32']}"
        )
        print(
            f" {C_BOLD}SCAN{C_END} {C_DIM}big-endian{C_END}     u8: {be['u8']:<3} | u16: {be['u16']:<5} | "
            f"u32: {be['u32']:<10} | f32: {be['f32']}"
        )

    print(f" HEX        {raw.hex(' ')}")
    if text:
        print(f" ASCII      {text}")

    print(SEPARATOR)


# =============================================================================
#  MAIN
# =============================================================================

def main():
    context, sock = init_zmq(ZMQ_ADDR, ZMQ_RECV_TIMEOUT_MS)
    jsonl_path, text_path = init_logs(LOG_DIR)

    packet_count = 0
    last_arrival = None
    last_watchdog = time.time()

    spinner = ["█", "▓", "▒", "░", "▒", "▓"]
    spin_idx = 0

    print(f"\n{C_BOLD}┌──────────────────────────────────────────────────────────┐")
    print(f"│                MAVERIC GS SOFTWARE v3.0                  │")
    print(f"└──────────────────────────────────────────────────────────┘{C_END}")
    print(f" ZMQ:  {C_BOLD}{ZMQ_ADDR}{C_END}")
    print(f" Logs: {C_BOLD}{text_path}{C_END}  (human-readable)")
    print(f"       {C_BOLD}{jsonl_path}{C_END}  (machine)\n")

    try:
        while True:
            result = receive_pdu(sock)

            if result is None:
                # --- IDLE / WAITING ---
                elapsed = time.time() - last_watchdog
                tc = C_CYAN if elapsed <= 10 else (C_YELLOW if elapsed <= 30 else C_RED)
                sys.stdout.write(
                    f"\r{C_BOLD}{C_CYAN} {spinner[spin_idx]} {C_END} "
                    f"Waiting... {tc}[SILENCE: {elapsed:04.1f}s]{C_END}  "
                )
                sys.stdout.flush()
                spin_idx = (spin_idx + 1) % len(spinner)
                continue

            # --- PACKET RECEIVED ---
            meta, raw = result
            now = time.time()
            sys.stdout.write("\r" + " " * 70 + "\r")

            delta_t = (now - last_arrival) if last_arrival is not None else None
            last_arrival = now
            last_watchdog = now

            packet_count += 1
            gs_ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

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

            log_packet_jsonl(jsonl_path, log_record)

            # Phase 3b: Log — human-readable text
            log_packet_text(
                text_path, packet_count, gs_ts, frame_type, raw, inner_payload,
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
        print(f"\n{C_YELLOW}Monitor stopped. {packet_count} packets logged.{C_END}")
        print(f" {C_DIM}{text_path}{C_END}")
        print(f" {C_DIM}{jsonl_path}{C_END}")
        sock.close()
        context.term()


if __name__ == "__main__":
    main()