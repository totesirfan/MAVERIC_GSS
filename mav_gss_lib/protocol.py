"""
mav_gss_lib.protocol -- MAVERIC Mission Protocol Definitions

Node addressing, packet types, CSP v1 header (build and parse),
KISS framing, CRC-16 XMODEM, command wire format (build and parse),
timestamp detection, packet fingerprinting, and command schema for
deterministic parsing.

Mirrors the wire format of Commands.py (satellite side) without
importing it. Both build_cmd_raw() and try_parse_command() operate
on the same byte layout -- one encodes, the other decodes.

When a command schema is loaded from maveric_commands.yml, the parser
skips heuristic scanning and maps args directly by position and type.
Commands not in the schema fall back to the original heuristic path.

Author:  Irfan Annuar - USC ISI SERC
"""

import re
import hashlib
from datetime import datetime, timezone
from crc import Calculator, Crc16

try:
    import yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False


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
#  TIMESTAMP DETECTION (heuristic fallback)
# =============================================================================

TS_MIN_MS = 1_704_067_200_000  # ~2024-01-01
TS_MAX_MS = 1_830_297_600_000  # ~2028-01-01

_TS_RE = re.compile(rb"\d{13}")


def try_extract_timestamp(payload):
    """Search for a plausible 13-digit epoch-ms timestamp in raw bytes.
    Returns (dt_utc, dt_local, raw_ms) or None.

    HEURISTIC FALLBACK -- only needed when the command schema does not
    cover the packet. If apply_schema() succeeds and has epoch_ms fields,
    use schema_timestamps() instead of this function."""
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
#  COMMAND SCHEMA — Deterministic Parsing
#
#  Loaded from maveric_commands.yml. When a received command's cmd_id
#  matches an entry, args are parsed by position and type instead of
#  heuristic scanning. Commands not in the schema fall through to the
#  original try_extract_timestamp / per-arg guessing path.
#
#  Schema eliminates:
#    - Regex timestamp scanning (try_extract_timestamp)
#    - Per-arg 13-digit guessing in display/log code
#    - Ambiguity about what each argument means
#
#  If PyYAML is not installed or the file is missing, everything falls
#  back to heuristic mode silently. No crash, no degradation in existing
#  functionality.
# =============================================================================

def _parse_epoch_ms(value_str):
    """Convert string to fully resolved timestamp.

    Returns {"ms": int, "utc": datetime, "local": datetime} if plausible.
    Returns original string if not a valid epoch-ms value.

    This is the ONLY timestamp resolution path for schema-matched commands.
    No regex scan, no second pass, no separate schema_timestamps() call."""
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
    Returns empty dict on any failure (missing file, no PyYAML, bad YAML)."""
    if not _YAML_OK:
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
            defs[cmd_id] = {
                "args": args,
                "variadic": spec.get("variadic", False),
            }
        return defs
    except (OSError, yaml.YAMLError, AttributeError, TypeError):
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
        schema_match: False

    The raw 'args' list is always preserved unchanged.
    Returns True if schema was applied, False otherwise."""
    if not cmd_defs or cmd["cmd_id"] not in cmd_defs:
        cmd["schema_match"] = False
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

    return len(issues) == 0, issues


# =============================================================================
#  UTILITIES
# =============================================================================

def clean_text(data: bytes) -> str:
    """Printable ASCII representation with non-printable bytes as middle dot."""
    return "".join(chr(b) if 32 <= b < 127 else "\u00b7" for b in data)


def fingerprint(data: bytes) -> str:
    """Short SHA-256 fingerprint (first 12 hex chars / 48 bits)."""
    return hashlib.sha256(data).hexdigest()[:12]