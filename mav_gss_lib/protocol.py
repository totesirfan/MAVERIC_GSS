"""
mav_gss_lib.protocol -- MAVERIC Mission Protocol Definitions

Node addressing, packet types, CSP v1 header (build and parse),
KISS framing, CRC-16 XMODEM, command wire format (build and parse),
timestamp detection, and packet fingerprinting.

Mirrors the wire format of Commands.py (satellite side) without
importing it. Both build_cmd_raw() and try_parse_command() operate
on the same byte layout -- one encodes, the other decodes.

Author:  Irfan Annuar - USC ISI SERC
"""

import re
import hashlib
from datetime import datetime, timezone
from crc import Calculator, Crc16


# =============================================================================
#  NODE & PACKET TYPE DEFINITIONS
# =============================================================================

NODE_NAMES = {
    0: "NONE", 1: "LPPM", 2: "EPS", 3: "UPPM",
    4: "HOLONAV", 5: "ASTROBOARD", 6: "GS", 7: "FTDI",
}
NODE_IDS = {v: k for k, v in NODE_NAMES.items()}

PTYPE_NAMES = {0: "NONE", 1: "REQ", 2: "RES", 3: "ACK"}
PTYPE_IDS = {v: k for k, v in PTYPE_NAMES.items()}

GS_NODE = NODE_IDS["GS"]  # 6


def node_label(node_id):
    """Format node ID for display: '2 (EPS)' or '99' if unknown."""
    name = NODE_NAMES.get(node_id)
    return f"{node_id} ({name})" if name else str(node_id)


def ptype_label(ptype_id):
    """Format packet type for display: '1 (REQ)' or '99' if unknown."""
    name = PTYPE_NAMES.get(ptype_id)
    return f"{ptype_id} ({name})" if name else str(ptype_id)


def resolve_node(s):
    """Resolve a node name ('EPS') or numeric string ('2') to an int.
    Returns int node ID or None if unrecognized."""
    upper = s.upper()
    if upper in NODE_IDS:
        return NODE_IDS[upper]
    if s.isdigit():
        nid = int(s)
        if nid in NODE_NAMES:
            return nid
    return None


# =============================================================================
#  KISS FRAMING
#
#  Mirrors Commands.py create_cmd() output format exactly.
#  Satellite's kiss_process_byte() expects: C0 00 [escaped data] C0
# =============================================================================

FEND  = 0xC0
FESC  = 0xDB
TFEND = 0xDC
TFESC = 0xDD


def kiss_wrap(raw_cmd):
    """KISS-wrap a raw command payload.
    Output: C0 00 [kiss-escaped data] C0
    Identical to Commands.py create_cmd() KISS section."""
    escaped = bytearray()
    for b in raw_cmd:
        if b == FEND:
            escaped.extend(bytes([FESC, TFEND]))
        elif b == FESC:
            escaped.extend(bytes([FESC, TFESC]))
        else:
            escaped.append(b)
    frame = bytearray([FEND, 0x00])
    frame.extend(escaped)
    frame.append(FEND)
    return bytes(frame)


# =============================================================================
#  CRC-16 XMODEM
# =============================================================================

crc_calc = Calculator(Crc16.XMODEM)


# =============================================================================
#  COMMAND WIRE FORMAT
#
#  Layout (from Commands.py):
#    [orgn][dest][echo][ptype][id_len][args_len]
#    [id_str][0x00][args_str][0x00][CRC-16 LE]
# =============================================================================

def build_cmd_raw(dest, cmd, args="", echo=0, ptype=1, origin=GS_NODE):
    """Build raw MAVERIC command payload with CRC-16 (before KISS wrapping).
    Returns bytearray matching Commands.py wire format."""
    p = bytearray()
    p.append(origin & 0xFF)
    p.append(dest & 0xFF)
    p.append(echo & 0xFF)
    p.append(ptype & 0xFF)
    p.append(len(cmd) & 0xFF)
    p.append(len(args) & 0xFF)
    p.extend(cmd.encode('ascii'))
    p.append(0x00)
    p.extend(args.encode('ascii'))
    p.append(0x00)
    crc = crc_calc.checksum(p)
    p.extend(crc.to_bytes(2, byteorder='little'))
    return p


def build_kiss_cmd(dest, cmd, args="", echo=0, ptype=1, origin=GS_NODE):
    """Build a complete KISS-wrapped command.
    Returns (kiss_bytes, raw_bytes)."""
    raw = build_cmd_raw(dest, cmd, args, echo, ptype, origin)
    return kiss_wrap(raw), raw


def try_parse_command(payload):
    """Attempt to parse a byte payload as a MAVERIC command structure.
    Expects the payload AFTER the CSP header (bytes 4+).

    Returns (parsed_dict, remaining_bytes) or (None, None) on failure.
    Parses based on length fields, not hardcoded offsets."""
    if len(payload) < 6:
        return None, None

    src       = payload[0]
    dest      = payload[1]
    echo      = payload[2]
    pkt_type  = payload[3]
    id_len    = payload[4]
    args_len  = payload[5]

    if 6 + id_len + 1 + args_len + 1 > len(payload):
        return None, None

    id_start = 6
    id_end   = id_start + id_len
    cmd_id   = payload[id_start:id_end].decode("ascii", errors="replace")

    null_pos = id_end
    if null_pos < len(payload) and payload[null_pos] == 0x00:
        null_pos += 1

    args_start = null_pos
    args_end   = args_start + args_len
    args_str   = payload[args_start:args_end].decode("ascii", errors="replace").strip()

    tail_start = args_end
    if tail_start < len(payload) and payload[tail_start] == 0x00:
        tail_start += 1

    crc = None
    if tail_start + 2 <= len(payload):
        crc = payload[tail_start] | (payload[tail_start + 1] << 8)
        tail_start += 2

    tail = payload[tail_start:]

    cmd = {
        "src": src, "dest": dest, "echo": echo, "pkt_type": pkt_type,
        "cmd_id": cmd_id, "args": args_str.split(), "crc": crc,
    }
    return cmd, tail


# =============================================================================
#  CSP V1 HEADER
#
#  32-bit big-endian word:
#    [31:30] priority  [29:25] source  [24:20] destination
#    [19:14] dest_port [13:8]  src_port [7:0] flags
# =============================================================================

def try_parse_csp_v1(payload):
    """Parse first 4 bytes as CSP v1 header (RX direction).
    Returns (parsed_dict, is_plausible) or (None, False)."""
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
    plausible = csp["src"] <= 20 and csp["dest"] <= 20
    return csp, plausible


class CSPConfig:
    """Configurable CSP v1 header for uplink (TX direction).

    Defaults derived from observed MAVERIC downlink traffic:
      Prio:2 Src:8 Dest:0 DPort:24 -- reversed for uplink.
    These are placeholders until the CSP address plan is confirmed."""

    def __init__(self):
        self.enabled = True
        self.prio    = 2
        self.src     = 0      # GS address
        self.dest    = 8      # satellite address
        self.dport   = 24     # service port
        self.sport   = 0
        self.flags   = 0x00

    def build_header(self):
        """Pack CSP fields into 4-byte big-endian header."""
        h = ((self.prio  & 0x03) << 30 |
             (self.src   & 0x1F) << 25 |
             (self.dest  & 0x1F) << 20 |
             (self.dport & 0x3F) << 14 |
             (self.sport & 0x3F) << 8  |
             (self.flags & 0xFF))
        return h.to_bytes(4, 'big')

    def overhead(self):
        """Number of bytes the CSP header adds to a payload."""
        return 4 if self.enabled else 0

    def wrap(self, payload):
        """Prepend CSP header to payload if enabled, otherwise pass through."""
        if self.enabled:
            return self.build_header() + payload
        return payload


# =============================================================================
#  TIMESTAMP DETECTION
# =============================================================================

TS_MIN_MS = 1_704_067_200_000  # ~2024-01-01
TS_MAX_MS = 1_830_297_600_000  # ~2028-01-01

_TS_RE = re.compile(rb"\d{13}")


def try_extract_timestamp(payload):
    """Search for a plausible 13-digit epoch-ms timestamp in raw bytes.
    Returns (dt_utc, dt_local, raw_ms) or None."""
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


# =============================================================================
#  UTILITIES
# =============================================================================

def clean_text(data: bytes) -> str:
    """Printable ASCII representation with non-printable bytes as middle dot."""
    return "".join(chr(b) if 32 <= b < 127 else "\u00b7" for b in data)


def fingerprint(data: bytes) -> str:
    """Short SHA-256 fingerprint (first 12 hex chars / 48 bits)."""
    return hashlib.sha256(data).hexdigest()[:12]