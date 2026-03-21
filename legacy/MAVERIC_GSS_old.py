"""
MAVERIC GSS — Ground Station Software

Packet monitor for the MAVERIC CubeSat mission. Subscribes to decoded PDUs
from a GNU Radio / gr-satellites flowgraph over ZMQ PUB/SUB and displays
packet contents for live debugging.

Designed to run continuously. The flowgraph can be started and stopped
independently — the monitor will idle and resume when packets arrive.

Raw hex is ground truth. All parsed fields (CSP, timestamps, command structure)
are diagnostic until the telemetry map is finalized.

Author:  Irfan Annuar
Org:     USC ISI SERC
"""

import zmq
import pmt
import re
import sys
import time
import json
import os
import hashlib
import argparse
from datetime import datetime, timezone

# --- CONFIGURATION ---
VERSION = "3.1"
ZMQ_PORT = "52001"                       # Must match the ZMQ PUB Message Sink in GNU Radio
ZMQ_ADDR = f"tcp://127.0.0.1:{ZMQ_PORT}"
ZMQ_RECV_TIMEOUT_MS = 200                # How long recv() blocks before returning to idle loop
LOG_DIR = "logs"

# Known node IDs — from CommandManager.node_lbl_to_id
NODE_NAMES = {
    0: "NONE",
    1: "LPPM",
    2: "EPS",
    3: "UPPM",
    4: "HOLONAV",
    5: "ASTROBOARD",
    6: "GS",
    7: "FTDI",
}

# Packet type IDs — from CommandManager.ptype_lbl_to_id
PTYPE_NAMES = {
    0: "NONE",
    1: "REQ",
    2: "RES",
    3: "ACK",
}

def node_label(node_id):
    """Return 'ID (Name)' if known, otherwise just 'ID'."""
    name = NODE_NAMES.get(node_id)
    return f"{node_id} ({name})" if name else str(node_id)

def ptype_label(ptype_id):
    """Return 'ID (Name)' if known, otherwise just 'ID'."""
    name = PTYPE_NAMES.get(ptype_id)
    return f"{ptype_id} ({name})" if name else str(ptype_id)

# Plausible epoch-ms range for timestamp detection (~2024-01-01 to ~2028-01-01).
# Prevents false positives from random 13-digit byte sequences.
# Widen this range if the mission timeline extends.
TS_MIN_MS = 1_704_067_200_000
TS_MAX_MS = 1_830_297_600_000

# ANSI Colors — used for terminal display only, stripped for log files.
# Yellow = AX.25 frames, Green = AX100 frames, Red = unknown / errors,
# Cyan = protocol fields, Dim = secondary info, Bold = values.
C_CYAN    = "\033[96m"
C_GREEN   = "\033[92m"
C_YELLOW  = "\033[93m"
C_RED     = "\033[91m"
C_DIM     = "\033[2m"
C_BOLD    = "\033[1m"
C_END     = "\033[0m"

# Precompiled regex patterns — avoids recompiling on every call.
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")
_TS_RE   = re.compile(rb"\d{13}")


# =============================================================================
#  TRANSPORT
# =============================================================================

def init_zmq(addr, timeout_ms):
    """Initialize ZMQ SUB socket with receive timeout.

    Uses PUB/SUB instead of PUSH/PULL because PUSH/PULL round-robins
    messages across consumers — stale processes from previous runs
    silently steal half the packets. PUB/SUB delivers to all subscribers
    independently and allows multiple monitors on the same stream.
    """
    context = zmq.Context()
    sock = context.socket(zmq.SUB)
    sock.setsockopt(zmq.SUBSCRIBE, b"")      # receive all messages, no topic filter
    sock.setsockopt(zmq.RCVHWM, 10000)      # receive buffer — generous for a cubesat beacon rate
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

    Depends on gr-satellites populating the 'transmitter' key with
    the transmitter name from MAVERIC_DECODER.yml. If gr-satellites
    changes its metadata format, this will fall through to UNKNOWN.
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
        # 03 f0 = AX.25 UI frame control byte (0x03) + PID no-layer-3 (0xf0).
        # Everything before this is AX.25 header (callsigns, SSIDs).
        # If the satellite ever uses a different frame type or PID,
        # this search will fail and return raw with a warning.
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

    CSP v1 header is a 32-bit big-endian word:
      [31:30] priority  [29:25] source  [24:20] destination
      [19:14] dest port  [13:8] source port  [7:0] flags

    This will produce a valid-looking parse for ANY 4 bytes.
    Plausibility check is a heuristic — update the thresholds
    once the CSP address plan is confirmed.
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
    for match in _TS_RE.finditer(payload):
        ms = int(match.group())
        if TS_MIN_MS <= ms <= TS_MAX_MS:
            try:
                dt_utc = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
                dt_local = dt_utc.astimezone()
                return dt_utc, dt_local, ms
            except (OSError, ValueError):
                continue
    return None


def try_parse_command(payload):
    """
    Attempt to parse payload as a MAVERIC command structure.
    Expects the payload AFTER the CSP header (bytes 4+).

    Command structure (from Commands.py):
      [0]    Src node ID
      [1]    Dest node ID
      [2]    Echo node ID
      [3]    Packet Type (REQ=1, RES=2, ACK=3)
      [4]    Command ID string length
      [5]    Args string length
      [6..]  Command ID string
      [..]   0x00 null terminator
      [..]   Args string (space-delimited)
      [..]   0x00 null terminator
      [2]    CRC-16 XMODEM (little-endian)

    Returns (parsed_dict, remaining_bytes) or (None, None) on failure.
    Parses based on length fields, not hardcoded offsets.
    """
    if len(payload) < 6:
        return None, None

    src       = payload[0]
    dest      = payload[1]
    echo      = payload[2]
    pkt_type  = payload[3]
    id_len    = payload[4]
    args_len  = payload[5]

    # Sanity check: lengths should fit within the remaining payload
    if 6 + id_len + 1 + args_len + 1 > len(payload):
        return None, None

    # Extract command ID string
    id_start = 6
    id_end   = id_start + id_len
    cmd_id   = payload[id_start:id_end].decode("ascii", errors="replace")

    # Skip null terminator after command ID
    null_pos = id_end
    if null_pos < len(payload) and payload[null_pos] == 0x00:
        null_pos += 1

    # Extract args string
    args_start = null_pos
    args_end   = args_start + args_len
    args_str   = payload[args_start:args_end].decode("ascii", errors="replace").strip()

    # Skip null terminator after args
    tail_start = args_end
    if tail_start < len(payload) and payload[tail_start] == 0x00:
        tail_start += 1

    # CRC-16 XMODEM — 2 bytes, little-endian
    crc = None
    if tail_start + 2 <= len(payload):
        crc = payload[tail_start] | (payload[tail_start + 1] << 8)
        tail_start += 2

    # Any remaining bytes after CRC
    tail = payload[tail_start:]

    cmd = {
        "src":       src,
        "dest":      dest,
        "echo":      echo,
        "pkt_type":  pkt_type,
        "cmd_id":    cmd_id,
        "args":      args_str.split(),
        "crc":       crc,
    }

    return cmd, tail


def clean_text(data: bytes) -> str:
    """Convert payload bytes to a readable ASCII string.
    Printable characters are kept as-is, non-printable bytes
    (including nulls and control characters) are shown as '·'
    so field boundaries and structure remain visible."""
    return "".join(chr(b) if 32 <= b < 127 else "·" for b in data)


def fingerprint(data: bytes) -> str:
    """Return a short SHA-256 fingerprint of the raw PDU.
    First 12 hex characters (48 bits) — enough to identify
    unique vs duplicate packets at cubesat beacon rates."""
    return hashlib.sha256(data).hexdigest()[:12]


# =============================================================================
#  LOGGING
# =============================================================================

def strip_ansi(s):
    """Remove ANSI escape codes, return visible text only."""
    return _ANSI_RE.sub("", s)


class SessionLog:
    """Manages persistent file handles for JSONL and text logs.

    Opens both files at session start and keeps them open to avoid
    per-packet open/close overhead. Each write is flushed immediately
    so data survives if the process is killed.

    Two log formats:
      .jsonl — one JSON object per packet, for scripted analysis and replay
      .txt   — human-readable plain text, for review and sharing
    """

    def __init__(self, log_dir, zmq_addr, flush_every=10):
        os.makedirs(log_dir, exist_ok=True)
        session_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.jsonl_path = os.path.join(log_dir, f"maveric_{session_ts}.jsonl")
        self.text_path  = os.path.join(log_dir, f"maveric_{session_ts}.txt")

        self._jsonl_f = open(self.jsonl_path, "a")
        self._text_f  = open(self.text_path, "w")
        self._flush_every = flush_every
        self._writes_since_flush = 0

        # Write text log header
        self._text_f.write(f"{'='*80}\n")
        self._text_f.write(f"  MAVERIC Ground Station Log  (GSS v{VERSION})\n")
        self._text_f.write(f"  Session started: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}\n")
        self._text_f.write(f"  ZMQ source:      {zmq_addr}\n")
        self._text_f.write(f"{'='*80}\n\n")
        self._text_f.flush()

    def _maybe_flush(self):
        """Flush log files every N packets instead of every write.
        Reduces I/O overhead during bursts while still ensuring
        data reaches disk regularly."""
        self._writes_since_flush += 1
        if self._writes_since_flush >= self._flush_every:
            self._jsonl_f.flush()
            self._text_f.flush()
            self._writes_since_flush = 0

    def write_jsonl(self, record):
        """Append one JSON-lines record. Contains raw_hex (ground truth),
        payload_hex (after stripping), and all candidate parse results."""
        self._jsonl_f.write(json.dumps(record) + "\n")
        self._maybe_flush()

    def write_text(self, pkt_num, gs_ts, frame_type, raw, inner_payload,
                   stripped_hdr, csp, csp_plausible, ts_result, cmd, cmd_tail,
                   text, warnings, delta_t, fp, is_dup=False):
        """Append one human-readable packet entry. Mirrors the terminal
        display but without ANSI color codes or box-drawing borders."""
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

        if cmd:
            lines.append(
                f"  CMD         Src: {node_label(cmd['src'])} | Dest: {node_label(cmd['dest'])} | "
                f"Echo: {node_label(cmd['echo'])} | Type: {ptype_label(cmd['pkt_type'])}"
            )
            lines.append(f"  CMD ID      {cmd['cmd_id']}")
            for i, arg in enumerate(cmd['args']):
                if len(arg) == 13 and arg.isdigit() and TS_MIN_MS <= int(arg) <= TS_MAX_MS:
                    lines.append(f"  UNIX TIME   {arg}")
                else:
                    lines.append(f"  ARG {i}       {arg}")

        lines.append(f"  HEX         {raw.hex(' ')}")
        if text:
            lines.append(f"  ASCII       {text}")
        if cmd and cmd.get('crc') is not None:
            lines.append(f"  CRC-16      0x{cmd['crc']:04x}")
        lines.append(f"  SHA256      {fp}")

        lines.append("-" * 80)
        lines.append("")

        self._text_f.write("\n".join(lines) + "\n")

    def write_summary(self, packet_count, session_start, first_pkt_ts, last_pkt_ts):
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
        summary.append(f"{'='*80}\n")

        self._text_f.write("\n".join(summary) + "\n")
        self._text_f.flush()

    def close(self):
        self._jsonl_f.close()
        self._text_f.close()


# =============================================================================
#  DISPLAY
#
#  Terminal rendering uses box-drawing characters at a fixed 80-column width.
#  Each packet is drawn inside a bordered box with three sections:
#  header (packet metadata), protocol (parsed candidates), and raw data.
# =============================================================================

BOX_W = 80                         # total box width including border characters
INN_W = BOX_W - 4                  # usable content width (│ + space ... space + │)

TOP    = f"┌{'─' * (BOX_W - 2)}┐"  # box top
MID    = f"├{'─' * (BOX_W - 2)}┤"  # section divider
BOT    = f"└{'─' * (BOX_W - 2)}┘"  # box bottom


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


def render_packet(pkt_num, gs_ts, frame_type, raw, inner_payload,
                  stripped_hdr, csp, csp_plausible, ts_result, cmd,
                  warnings, delta_t, loud=False, text=None, fp=None, is_dup=False):
    """Print one packet to terminal inside an 80-column box.

    Layout:
      Δt (if not first packet)
      ┌─ header: packet #, frame type, [DUP], timestamp, byte counts ─┐
      ├─ protocol: AX.25 header, CSP V1, SAT TIME                     ─┤
      │  command: src, dest, echo, type, ID, per-arg values             │
      └────────────────────────────────────────────────────────────────┘

    Hex dump, ASCII, CRC, and SHA256 are shown in --loud mode only.

    Alignment is handled by _row() which uses strip_ansi() to
    measure visible width, so adding or changing ANSI color codes
    will not break the right border.
    """

    color = C_YELLOW if frame_type == "AX.25" else (C_GREEN if frame_type == "AX100" else C_RED)

    # Delta-T left-aligned above the box
    if delta_t is not None:
        print(f"  {C_DIM}Δt{C_END} {C_CYAN}{delta_t:.3f}s{C_END}")

    # Header — build left and right parts, fill middle with spaces
    print(f"{C_DIM}{TOP}{C_END}")

    dup_tag = f"  {C_RED}[DUP]{C_END}" if is_dup else ""
    dup_vis = 7 if is_dup else 0  # "  [DUP]" = 7 visible chars

    h_left  = f"{C_BOLD}{color}PKT #{pkt_num}{C_END}    {color}{frame_type}{C_END}{dup_tag}"
    h_mid   = f"{gs_ts}"
    h_right = f"{C_DIM}{len(raw)} B PDU → {len(inner_payload)} B payload{C_END}"

    h_left_vis  = len(f"PKT #{pkt_num}    {frame_type}") + dup_vis
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

    # Satellite timestamp (human-readable)
    if ts_result:
        dt_utc, dt_local, _ = ts_result
        utc_s = dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC')
        loc_s = dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')
        print(_row(f"  {C_CYAN}SAT TIME{C_END}    {utc_s}  {C_DIM}│{C_END}  {loc_s}"))
    else:
        print(_row(f"  {C_CYAN}SAT TIME{C_END}    {C_DIM}--{C_END}"))

    print(_row())

    # Command structure
    if cmd:
        print(_row(
            f"  {C_CYAN}CMD{C_END}         "
            f"Src {C_BOLD}{node_label(cmd['src'])}{C_END}  "
            f"Dest {C_BOLD}{node_label(cmd['dest'])}{C_END}  "
            f"Echo {C_BOLD}{node_label(cmd['echo'])}{C_END}  "
            f"Type {C_BOLD}{ptype_label(cmd['pkt_type'])}{C_END}"
        ))
        print(_row(
            f"  {C_CYAN}CMD ID{C_END}      {C_BOLD}{cmd['cmd_id']}{C_END}"
        ))

        # Display each arg on its own line, labeling known fields.
        # Timestamp detection is position-independent — arg order may change.
        for i, arg in enumerate(cmd['args']):
            if len(arg) == 13 and arg.isdigit() and TS_MIN_MS <= int(arg) <= TS_MAX_MS:
                print(_row(f"  {C_CYAN}UNIX TIME{C_END}   {C_BOLD}{arg}{C_END}"))
            else:
                print(_row(f"  {C_CYAN}ARG {i}{C_END}       {C_BOLD}{arg}{C_END}"))

        print(_row())

    # Hex dump, ASCII, CRC, SHA256 — only in loud mode
    if loud:
        print(f"{C_DIM}{MID}{C_END}")
        print(_row())

        hex_str = raw.hex(' ')
        parts = hex_str.split(" ")
        for i in range(0, len(parts), 20):
            chunk = " ".join(parts[i:i + 20])
            if i == 0:
                print(_row(f"  {C_GREEN}HEX{C_END}     {chunk}"))
            else:
                print(_row(f"          {chunk}"))

        print(_row())

        if text:
            print(_row(f"  {C_DIM}ASCII{C_END}   {C_DIM}{text}{C_END}"))

        if cmd and cmd.get('crc') is not None:
            print(_row(f"  {C_DIM}CRC-16{C_END}  {C_DIM}0x{cmd['crc']:04x}{C_END}"))

        if fp:
            print(_row(f"  {C_DIM}SHA256{C_END}  {C_DIM}{fp}{C_END}"))

        print(_row())

    print(f"{C_DIM}{BOT}{C_END}")


# =============================================================================
#  MAIN
# =============================================================================

def main():
    """Main receive loop.

    Runs continuously until Ctrl+C. The flowgraph can be started
    and stopped independently — the monitor idles between packets
    and resumes when new data arrives.

    Each packet goes through four phases:
      1. Detect frame type + strip transport headers → inner payload
      2. Parse CSP header, timestamp, and MAVERIC command structure
      3. Log to both JSONL and text files (unless --nolog)
      4. Render to terminal
    """
    parser = argparse.ArgumentParser(description="MAVERIC GSS — Ground Station Packet Monitor")
    parser.add_argument("--nolog", action="store_true",
                        help="Disable logging to disk (display only)")
    parser.add_argument("--loud", action="store_true",
                        help="Show hex dump, ASCII, and SHA256 in terminal display")
    args = parser.parse_args()

    context, sock = init_zmq(ZMQ_ADDR, ZMQ_RECV_TIMEOUT_MS)
    log = None if args.nolog else SessionLog(LOG_DIR, ZMQ_ADDR)
    loud = args.loud

    packet_count = 0
    last_arrival = None
    last_watchdog = time.time()
    session_start = time.time()
    first_pkt_ts = None
    last_pkt_ts = None
    seen_fps = set()               # fingerprints seen this session, for duplicate detection
    pkt_times = []                 # recent packet arrival times, for rolling rate
    last_render = 0.0              # timestamp of last terminal render
    render_skipped = 0             # packets not rendered since last render
    RENDER_INTERVAL = 0.25         # minimum seconds between terminal renders

    spinner = ["█", "▓", "▒", "░", "▒", "▓"]
    spin_idx = 0

    print(f"\n{C_BOLD}┌──────────────────────────────────────────────────────────┐")
    print(f"│                       MAVERIC GSS                        │")
    print(f"│                           {C_END}{C_DIM}v{VERSION}{C_END}{C_BOLD}                           │")
    print(f"└──────────────────────────────────────────────────────────┘{C_END}")
    print()
    print(f" {C_DIM}ZMQ{C_END}         {C_BOLD}{ZMQ_ADDR}{C_END}")
    print(f" {C_DIM}Timeout{C_END}     {ZMQ_RECV_TIMEOUT_MS}ms")
    print(f" {C_DIM}Display{C_END}     {'loud' if loud else 'normal'}")
    if log:
        print(f" {C_DIM}Log (txt){C_END}  {log.text_path}")
        print(f" {C_DIM}Log (json){C_END} {log.jsonl_path}")
    else:
        print(f" {C_DIM}Logging{C_END}     disabled")
    print()

    try:
        while True:
            result = receive_pdu(sock)

            if result is None:
                # --- IDLE / WAITING ---
                elapsed = time.time() - last_watchdog
                tc = C_CYAN if elapsed <= 10 else (C_YELLOW if elapsed <= 30 else C_RED)
                pkt_str = f" | {C_DIM}{packet_count} pkts{C_END}" if packet_count > 0 else ""
                # Rolling packet rate — count packets in the last 60 seconds
                if pkt_times:
                    cutoff = time.time() - 60.0
                    recent = sum(1 for t in pkt_times if t > cutoff)
                    if recent > 0:
                        pkt_str += f" | {C_DIM}{recent:.0f} pkt/min{C_END}"
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

            # Phase 1: Detect + normalize
            frame_type = detect_frame_type(meta)
            inner_payload, stripped_hdr, warnings = normalize_frame(frame_type, raw)

            # Phase 2: Candidate parsing on inner payload
            csp, csp_plausible = try_parse_csp_v1(inner_payload)
            ts_result = try_extract_timestamp(inner_payload)
            text = clean_text(inner_payload)
            fp = fingerprint(raw)

            # Duplicate detection — same raw PDU seen before this session
            is_dup = fp in seen_fps
            seen_fps.add(fp)

            # Track arrival time for rolling rate calculation
            pkt_times.append(now)
            # Trim old entries beyond 60 seconds
            cutoff = now - 60.0
            pkt_times[:] = [t for t in pkt_times if t > cutoff]

            # Parse command structure from payload after CSP header
            cmd, cmd_tail = (None, None)
            if len(inner_payload) > 4:
                cmd, cmd_tail = try_parse_command(inner_payload[4:])

            # Phase 3: Log (unless --nolog)
            if log:
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
                    "sha256":     fp,
                    "duplicate":  is_dup,
                }
                if delta_t is not None:
                    log_record["delta_t"] = round(delta_t, 4)
                if csp:
                    log_record["csp_candidate"] = csp
                    log_record["csp_plausible"] = csp_plausible
                if cmd:
                    log_record["cmd"] = cmd
                    if ts_result:
                        log_record["sat_ts_ms"] = ts_result[2]
                    if cmd_tail:
                        log_record["tail_hex"] = cmd_tail.hex()

                log.write_jsonl(log_record)

                log.write_text(
                    packet_count, gs_ts, frame_type, raw, inner_payload,
                    stripped_hdr, csp, csp_plausible, ts_result, cmd, cmd_tail,
                    text, warnings, delta_t, fp, is_dup,
                )

            # Phase 4: Display (throttled during bursts)
            # Every packet is logged, but terminal rendering is limited
            # to at most 4 per second to prevent I/O blocking the receive loop.
            # During bursts the spinner never shows, so rate info goes here.
            if now - last_render >= RENDER_INTERVAL:
                if render_skipped > 0:
                    cutoff = now - 60.0
                    recent = sum(1 for t in pkt_times if t > cutoff)
                    print(f"  {C_DIM}... +{render_skipped} received | {packet_count} total | {recent} pkt/min{C_END}")
                render_packet(
                    packet_count, gs_ts, frame_type, raw, inner_payload,
                    stripped_hdr, csp, csp_plausible, ts_result, cmd,
                    warnings, None if render_skipped > 0 else delta_t,
                    loud, text, fp, is_dup,
                )
                last_render = now
                render_skipped = 0
            else:
                render_skipped += 1

    except KeyboardInterrupt:
        if log:
            log.write_summary(packet_count, session_start, first_pkt_ts, last_pkt_ts)
            log.close()

        # Terminal summary
        duration = time.time() - session_start
        dup_count = packet_count - len(seen_fps)
        print(f"\n")
        print(f"{C_DIM}{'─' * 50}{C_END}")
        print(f"  {C_BOLD}Session ended{C_END}")
        print(f"  Packets:    {C_BOLD}{packet_count}{C_END}  ({len(seen_fps)} unique, {dup_count} duplicate)")
        print(f"  Duration:   {duration:.0f}s ({duration/60:.1f} min)")
        print(f"{C_DIM}{'─' * 50}{C_END}")
        if log:
            print(f"  {C_DIM}{log.text_path}{C_END}")
            print(f"  {C_DIM}{log.jsonl_path}{C_END}")
        print()

        sock.close()
        context.term()


if __name__ == "__main__":
    main()