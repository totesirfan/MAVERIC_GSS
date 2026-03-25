"""
mav_gss_lib.protocol -- MAVERIC Mission Protocol Definitions

Node addressing, packet types, CSP v1 header (build and parse),
KISS framing, CRC-16 XMODEM, CRC-32C (CSP integrity), command wire
format (build and parse), and command schema
for deterministic parsing.

Mirrors the wire format of Commands.py (satellite side) without
importing it. Both build_cmd_raw() and try_parse_command() operate
on the same byte layout -- one encodes, the other decodes.

When a command schema is loaded from maveric_commands.yml, the parser
maps args directly by position and type. Commands not in the schema
display raw args with a warning.

Author:  Irfan Annuar - USC ISI SERC
"""

import sys
from datetime import datetime, timezone

try:
    import yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False


# =============================================================================
#  NODE & PACKET TYPE DEFINITIONS
# =============================================================================

NODE_NAMES = {}   # int → str, populated by init_nodes()
NODE_IDS   = {}   # str → int
PTYPE_NAMES = {}  # int → str, populated by init_nodes()
PTYPE_IDS   = {}  # str → int
GS_NODE     = 6   # default, updated by init_nodes()


def init_nodes(cfg):
    """Populate node/ptype tables from a loaded config dict.

    Must be called once at startup after load_gss_config().
    """
    global NODE_NAMES, NODE_IDS, PTYPE_NAMES, PTYPE_IDS, GS_NODE

    NODE_NAMES = {int(k): v for k, v in cfg["nodes"].items()}
    NODE_IDS   = {v: k for k, v in NODE_NAMES.items()}

    PTYPE_NAMES = {int(k): v for k, v in cfg["ptypes"].items()}
    PTYPE_IDS   = {v: k for k, v in PTYPE_NAMES.items()}

    gs_name = cfg.get("general", {}).get("gs_node", "GS")
    GS_NODE = NODE_IDS.get(gs_name, 6)


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


def resolve_ptype(s):
    """Resolve a packet type name ('REQ') or numeric string ('1') to an int.
    Returns int ptype ID or None if unrecognized."""
    upper = s.upper()
    if upper in PTYPE_IDS:
        return PTYPE_IDS[upper]
    if s.isdigit():
        pid = int(s)
        if pid in PTYPE_NAMES:
            return pid
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

def _crc16_xmodem(data):
    """CRC-16 XMODEM (poly 0x1021, init 0x0000).
    Pure Python fallback -- used when the 'crc' package is unavailable."""
    crc = 0x0000
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


try:
    from crc import Calculator, Crc16
    crc_calc = Calculator(Crc16.XMODEM)
    def crc16(data):
        return crc_calc.checksum(data)
except ImportError:
    crc_calc = None
    crc16 = _crc16_xmodem


# =============================================================================
#  CRC-32C (Castagnoli) — CSP Packet Integrity
#
#  CSP v1 uses CRC-32C (poly 0x1EDC6F41, reflected as 0x82F63B78)
#  over the entire CSP packet: header + payload (including the command's
#  own CRC-16). Appended as 4 bytes big-endian.
#
#  Verified against captured MAVERIC downlink traffic:
#    Packet 1 (AX.25):  CRC-32C = 0x3AA1DDAB  ✓
#    Packet 2 (AX100):  CRC-32C = 0xB23EFBC3  ✓
# =============================================================================

def crc32c(data):
    """CRC-32C (Castagnoli) checksum.

    Used by CSP v1 for packet integrity. Covers CSP header + full payload
    (including any inner checksums like the command CRC-16)."""
    crc = 0xFFFFFFFF
    poly = 0x82F63B78  # reflected polynomial
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc >> 1) ^ poly) if crc & 1 else (crc >> 1)
    return crc ^ 0xFFFFFFFF


def verify_csp_crc32(inner_payload):
    """Verify CRC-32C over a complete CSP packet (header + data + CRC-32C).

    Last 4 bytes are the received CRC-32C (big-endian); computed over
    everything preceding them.

    Returns (is_valid, received_crc, computed_crc).
    Returns (None, None, None) if payload is too short to contain a CRC."""
    if len(inner_payload) < 8:  # need at least 4B CSP header + 4B CRC
        return None, None, None
    received = int.from_bytes(inner_payload[-4:], 'big')
    computed = crc32c(inner_payload[:-4])
    return received == computed, received, computed


# =============================================================================
#  COMMAND WIRE FORMAT
#
#  Layout (from Commands.py):
#    [orgn][dest][echo][ptype][id_len][args_len]
#    [id_str][0x00][args_str][0x00][CRC-16 LE]
#
#  Full CSP packet on the wire:
#    [CSP v1 header 4B][command + CRC-16][CRC-32C 4B BE]
# =============================================================================

def build_cmd_raw(dest, cmd, args="", echo=0, ptype=1, origin=None):
    """Build raw MAVERIC command payload with CRC-16.
    Returns bytearray matching Commands.py wire format.
    Ready for CSP wrapping via CSPConfig.wrap()."""
    if origin is None:
        origin = GS_NODE
    header = bytes([origin & 0xFF, dest & 0xFF, echo & 0xFF, ptype & 0xFF,
                    len(cmd) & 0xFF, len(args) & 0xFF])
    p = bytearray(header)
    p.extend(cmd.encode('ascii'))
    p.append(0x00)
    p.extend(args.encode('ascii'))
    p.append(0x00)
    crc = crc16(p)
    p.extend(crc.to_bytes(2, byteorder='little'))
    return p


def build_kiss_cmd(dest, cmd, args="", echo=0, ptype=1, origin=None):
    """Build a complete KISS-wrapped command.
    Returns (kiss_bytes, raw_bytes)."""
    raw = build_cmd_raw(dest, cmd, args, echo, ptype, origin)
    return kiss_wrap(raw), raw


def try_parse_command(payload):
    """Attempt to parse a byte payload as a MAVERIC command structure.
    Expects the payload AFTER the CSP header (bytes 4+), but INCLUDING
    the trailing CRC-32C if present.

    Returns (parsed_dict, remaining_bytes) or (None, None) on failure.

    The parsed dict includes:
        src, dest, echo, pkt_type, cmd_id, args, crc (CRC-16),
        csp_crc32 (raw value if 4 trailing bytes present, else None)

    CRC-16 is verified here. CRC-32C verification requires the CSP header,
    so use verify_csp_crc32(inner_payload) at the call site."""
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
    cmd_id   = payload[id_start:id_end].decode("ascii", errors="replace").lower()

    null_pos = id_end
    if null_pos < len(payload) and payload[null_pos] == 0x00:
        null_pos += 1

    args_start = null_pos
    args_end   = args_start + args_len
    args_str   = payload[args_start:args_end].decode("ascii", errors="replace").strip()

    tail_start = args_end
    if tail_start < len(payload) and payload[tail_start] == 0x00:
        tail_start += 1

    # CRC-16 XMODEM (command integrity)
    crc = None
    crc_valid = None
    if tail_start + 2 <= len(payload):
        crc = payload[tail_start] | (payload[tail_start + 1] << 8)
        cmd_body = payload[:tail_start]
        crc_valid = crc == crc16(cmd_body)
        tail_start += 2

    # CRC-32C (CSP packet integrity) — consume if exactly 4 bytes remain
    csp_crc32 = None
    tail = payload[tail_start:]
    if len(tail) == 4:
        csp_crc32 = int.from_bytes(tail, 'big')
        tail = b""

    cmd = {
        "src": src, "dest": dest, "echo": echo, "pkt_type": pkt_type,
        "cmd_id": cmd_id, "args": args_str.split(), "crc": crc,
        "crc_valid": crc_valid, "csp_crc32": csp_crc32,
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


# =============================================================================
#  AX.25 HEADER
#
#  16-byte header for HDLC framing (UI frame, no L3 protocol):
#    [dest callsign 6B shifted][dest SSID 1B]
#    [src  callsign 6B shifted][src  SSID 1B]
#    [control 0x03][PID 0xF0]
#
#  Callsign bytes are ASCII shifted left 1 bit, space-padded to 6 chars.
#  SSID byte: 0b0SSSS0E1 where SSID is 0-15, E is end-of-address flag.
# =============================================================================

class AX25Config:
    """Configurable AX.25 header for uplink (TX direction).

    Wraps a payload with a 16-byte AX.25 UI frame header so the PDU
    is ready for an HDLC framer with no custom GRC blocks needed.

    Default callsigns:
        dest  WS9XSW-0  (satellite)
        src   WM2XBB-0  (ground station)
    """

    HEADER_LEN = 16  # 7 dest + 7 src + 1 control + 1 PID

    def __init__(self):
        self.enabled   = True
        self.dest_call = "WS9XSW"
        self.dest_ssid = 0
        self.src_call  = "WM2XBB"
        self.src_ssid  = 0

    @staticmethod
    def _encode_callsign(call, ssid, last=False):
        """Encode callsign + SSID into 7 AX.25 address bytes.

        Each character is shifted left 1 bit. Callsign is space-padded
        to 6 characters. SSID byte: 0b0SSSS0E1 (E=1 if last address)."""
        call = call.upper().ljust(6)[:6]
        addr = bytearray(ord(c) << 1 for c in call)
        ssid_byte = 0x60 | ((ssid & 0x0F) << 1)
        if last:
            ssid_byte |= 0x01  # end-of-address bit
        addr.append(ssid_byte)
        return bytes(addr)

    def overhead(self):
        """Number of bytes the AX.25 header adds to a payload."""
        return self.HEADER_LEN if self.enabled else 0

    def wrap(self, payload):
        """Prepend 16-byte AX.25 UI frame header if enabled.

        Output: [dest 7B][src 7B][0x03][0xF0][payload]"""
        if self.enabled:
            header = (
                self._encode_callsign(self.dest_call, self.dest_ssid, last=False)
                + self._encode_callsign(self.src_call, self.src_ssid, last=True)
                + b'\x03\xF0'
            )
            return header + payload
        return payload


class CSPConfig:
    """Configurable CSP v1 header for uplink (TX direction).

    Defaults derived from observed MAVERIC downlink traffic:
      Prio:2 Src:8 Dest:0 DPort:24 -- reversed for uplink.
    These are placeholders until the CSP address plan is confirmed.

    When enabled, wrap() prepends the 4-byte CSP header and appends
    a 4-byte CRC-32C (Castagnoli) over the entire CSP packet."""

    def __init__(self):
        self.enabled = True
        self.prio    = 2
        self.src     = 0      # GS address
        self.dest    = 8      # satellite address
        self.dport   = 0     # service port
        self.sport   = 24
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
        """Number of bytes the CSP header + CRC-32C add to a payload."""
        return 8 if self.enabled else 0  # 4B header + 4B CRC-32C

    def wrap(self, payload):
        """Prepend CSP header and append CRC-32C if enabled.

        Output: [CSP header 4B] [payload] [CRC-32C 4B BE]

        The CRC-32C covers the header + payload (everything before the
        CRC-32C itself), matching observed satellite downlink format."""
        if self.enabled:
            packet = self.build_header() + payload
            checksum = crc32c(packet).to_bytes(4, 'big')
            return packet + checksum
        return payload


# =============================================================================
#  COMMAND SCHEMA — Deterministic Parsing
#
#  Loaded from maveric_commands.yml. When a received command's cmd_id
#  matches an entry, args are parsed by position and type. Commands not
#  in the schema display raw args with a warning.
#
#  If PyYAML is not installed or the file is missing, a warning is
#  printed at startup. No crash, but all commands will be unrecognized.
# =============================================================================

TS_MIN_MS = 1_704_067_200_000  # ~2024-01-01
TS_MAX_MS = 1_830_297_600_000  # ~2028-01-01

def _parse_epoch_ms(value_str):
    """Convert string to fully resolved timestamp.

    Returns {"ms": int, "utc": datetime, "local": datetime} if plausible.
    Returns original string if not a valid epoch-ms value.

    This is the only timestamp resolution path -- called by apply_schema()
    for epoch_ms typed args."""
    try:
        ms = int(value_str)
        if TS_MIN_MS <= ms <= TS_MAX_MS:
            dt_utc = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
            dt_local = dt_utc.astimezone()
            return {"ms": ms, "utc": dt_utc, "local": dt_local}
    except (ValueError, TypeError, OSError):
        pass
    return value_str


_TYPE_PARSERS = {
    "str":      str,
    "int":      lambda s: int(s, 0),
    "float":    float,
    "epoch_ms": _parse_epoch_ms,
    "bool":     lambda s: s.lower() in ("true", "1", "yes"),
}


def load_command_defs(path="maveric_commands.yml"):
    """Load command definitions from YAML.

    Returns dict: {cmd_id: {"args": [{"name", "type"}, ...], "variadic": bool}}
    Returns empty dict on any failure (missing file, no PyYAML, bad YAML).
    Prints a warning to stderr on failure so the operator knows."""
    if not _YAML_OK:
        print("WARNING: PyYAML not installed -- command schema unavailable. "
              "Install with: pip install pyyaml", file=sys.stderr)
        return {}
    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
        defs = {}
        for cmd_id, spec in (raw.get("commands") or {}).items():
            args = []
            for a in (spec.get("args") or []):
                name = a.get("name", f"arg{len(args)}")
                typ = a.get("type", "str")
                if typ not in _TYPE_PARSERS:
                    typ = "str"
                args.append({"name": name, "type": typ})
            defs[cmd_id.lower()] = {
                "args": args,
                "variadic": spec.get("variadic", False),
            }
        return defs
    except (OSError, yaml.YAMLError):
        print(f"WARNING: Could not load {path} -- all commands will be unrecognized",
              file=sys.stderr)
        return {}


def apply_schema(cmd, cmd_defs):
    """Enrich a parsed command dict with typed argument values.

    If cmd_id is found in cmd_defs, adds to cmd:
        typed_args:   list of {"name", "type", "value"} for defined args
        extra_args:   list of raw strings for args beyond the schema
        sat_time:     first resolved epoch_ms value as (dt_utc, dt_local, ms)
                      or None if no epoch_ms fields exist
        schema_match: True

    If cmd_id is NOT in cmd_defs, adds:
        schema_match:  False
        schema_warning: str describing the unknown command

    The raw 'args' list is always preserved unchanged.
    Returns True if schema was applied, False otherwise."""
    if not cmd_defs or cmd["cmd_id"] not in cmd_defs:
        cmd["schema_match"] = False
        cmd["schema_warning"] = (
            f"Unknown command '{cmd['cmd_id']}' "
            "-- add to maveric_commands.yml for typed parsing"
        )
        return False

    defn = cmd_defs[cmd["cmd_id"]]
    raw_args = cmd["args"]
    schema_args = defn["args"]
    typed = []
    sat_time = None

    for i, arg_def in enumerate(schema_args):
        if i < len(raw_args):
            parser = _TYPE_PARSERS.get(arg_def["type"], str)
            try:
                value = parser(raw_args[i])
            except (ValueError, TypeError):
                value = raw_args[i]
            typed.append({
                "name":  arg_def["name"],
                "type":  arg_def["type"],
                "value": value,
            })
            # Surface the first resolved timestamp for SAT TIME display
            if arg_def["type"] == "epoch_ms" and isinstance(value, dict) and sat_time is None:
                sat_time = (value["utc"], value["local"], value["ms"])

    extra = raw_args[len(schema_args):]

    cmd["typed_args"]   = typed
    cmd["extra_args"]   = extra
    cmd["sat_time"]     = sat_time
    cmd["schema_match"] = True
    return True


def validate_args(cmd_id, args_str, cmd_defs):
    """Validate args string against schema before sending (TX side).

    Returns (is_valid, list_of_issues).
    If cmd_id is not in schema, returns (True, []) -- unknown commands
    are allowed through without validation."""
    if not cmd_defs or cmd_id not in cmd_defs:
        return True, []

    defn = cmd_defs[cmd_id]
    raw_args = args_str.split() if args_str else []
    schema_args = defn["args"]
    issues = []

    if len(raw_args) < len(schema_args):
        issues.append(
            f"expected {len(schema_args)} args, got {len(raw_args)}"
        )

    if len(raw_args) > len(schema_args) and not defn["variadic"]:
        issues.append(
            f"extra args: expected {len(schema_args)}, got {len(raw_args)}"
        )

    for i, arg_def in enumerate(schema_args):
        if i >= len(raw_args):
            break
        parser = _TYPE_PARSERS.get(arg_def["type"], str)
        try:
            parser(raw_args[i])
        except (ValueError, TypeError):
            issues.append(
                f"arg '{arg_def['name']}': '{raw_args[i]}' is not valid {arg_def['type']}"
            )

    return not issues, issues


# =============================================================================
#  FRAME NORMALIZATION (RX direction)
#
#  Detect frame type from gr-satellites metadata and strip outer framing
#  to expose the inner CSP+command payload.
# =============================================================================

def detect_frame_type(meta):
    """Determine frame type from gr-satellites metadata."""
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
#  TX COMMAND LINE PARSER
#
#  Parses user input into structured command fields for uplink.
#  Counterpart to try_parse_command() which parses the wire format (RX).
# =============================================================================

def parse_cmd_line(line):
    """Parse command line: [SRC] DEST ECHO TYPE CMD [ARGS]

    SRC is optional -- if omitted, defaults to GS (node 6).
    Detection: with 5+ tokens, if parts[3] resolves as a ptype then
    the first token is SRC; otherwise the old 4-token format is assumed.

    Returns (src, dest, echo, ptype, cmd, args) or None on failure."""
    parts = line.split(None, 5)
    if len(parts) < 4:
        return None

    # Detect format: if parts[3] is a valid ptype, first token is SRC
    ptype3 = resolve_ptype(parts[3]) if len(parts) >= 5 else None
    if ptype3 is not None:
        offset, src = 1, resolve_node(parts[0])
        if src is None:
            return None
        ptype = ptype3
    else:
        offset, src = 0, GS_NODE
        ptype = resolve_ptype(parts[2])
        if ptype is None:
            return None

    dest = resolve_node(parts[offset])
    if dest is None:
        return None
    echo = resolve_node(parts[offset + 1])
    if echo is None:
        return None

    cmd_idx = offset + 3
    args = " ".join(parts[cmd_idx + 1:]) if len(parts) > cmd_idx + 1 else ""
    return (src, dest, echo, ptype, parts[cmd_idx].lower(), args)


# =============================================================================
#  UTILITIES
# =============================================================================

def clean_text(data: bytes) -> str:
    """Printable ASCII representation with non-printable bytes as middle dot."""
    return "".join(chr(b) if 32 <= b < 127 else "\u00b7" for b in data)


