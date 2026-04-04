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

import warnings
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
_initialized = False


def init_nodes(cfg):
    """Populate node/ptype tables from a loaded config dict.

    Must be called once at startup after load_gss_config().
    """
    global NODE_NAMES, NODE_IDS, PTYPE_NAMES, PTYPE_IDS, GS_NODE, _initialized

    NODE_NAMES = {int(k): v for k, v in cfg["nodes"].items()}
    NODE_IDS   = {v: k for k, v in NODE_NAMES.items()}

    PTYPE_NAMES = {int(k): v for k, v in cfg["ptypes"].items()}
    PTYPE_IDS   = {v: k for k, v in PTYPE_NAMES.items()}

    gs_name = cfg.get("general", {}).get("gs_node", "GS")
    GS_NODE = NODE_IDS.get(gs_name, 6)
    _initialized = True


def _lookup_name(id_val, names):
    """Short name from ID: 'EPS' or '99' if unknown."""
    return names.get(id_val, str(id_val))

def _format_label(id_val, names):
    """Format ID for display: 'EPS' or '99' if unknown."""
    return names.get(id_val, str(id_val))

def _resolve_id(s, name_to_id, id_to_name):
    """Resolve a name ('EPS') or numeric string ('2') to an int ID.
    Returns int ID or None if unrecognized."""
    upper = s.upper()
    if upper in name_to_id:
        return name_to_id[upper]
    if s.isdigit():
        val = int(s)
        if val in id_to_name:
            return val
    return None

def node_name(node_id):    return _lookup_name(node_id, NODE_NAMES)
def ptype_name(ptype_id):  return _lookup_name(ptype_id, PTYPE_NAMES)
def node_label(node_id):   return _format_label(node_id, NODE_NAMES)
def ptype_label(ptype_id): return _format_label(ptype_id, PTYPE_NAMES)
def resolve_node(s):       return _resolve_id(s, NODE_IDS, NODE_NAMES)
def resolve_ptype(s):      return _resolve_id(s, PTYPE_IDS, PTYPE_NAMES)


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
    Identical to Commands.py create_cmd() KISS section.
    DB must be escaped before C0 to avoid double-escaping."""
    escaped = raw_cmd.replace(b'\xDB', b'\xDB\xDD').replace(b'\xC0', b'\xDB\xDC')
    return b'\xC0\x00' + escaped + b'\xC0'


# =============================================================================
#  CRC-16 XMODEM & CRC-32C (Castagnoli)
#
#  CRC-16 uses the 'crc' package when available, pure-Python fallback otherwise.
#  CRC-32C uses a pure-Python reflected loop — faster than the 'crc'
#  package's generic Configuration-based calculator for this polynomial.
#
#  CRC-32C verified against captured MAVERIC downlink traffic:
#    Packet 1 (AX.25):  CRC-32C = 0x3AA1DDAB  ✓
#    Packet 2 (AX100):  CRC-32C = 0xB23EFBC3  ✓
# =============================================================================

try:
    import crcmod.predefined as _crcmod
except ImportError:
    raise ImportError(
        "crcmod is required for CRC computation but not installed. "
        "Install with: pip install crcmod   (or: conda install crcmod)"
    ) from None

_crc16_fn = _crcmod.mkCrcFun('xmodem')
_crc32c_fn = _crcmod.mkCrcFun('crc-32c')


def crc16(data):
    """CRC-16 XMODEM checksum (C-accelerated via crcmod)."""
    return _crc16_fn(data)


def crc32c(data):
    """CRC-32C (Castagnoli) checksum for CSP v1 packet integrity (C-accelerated via crcmod)."""
    return _crc32c_fn(data)


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
#    [CSP v1 header 4B][command + CRC-16][CRC-32C 4B BE]  (csp_crc=true)
#    [CSP v1 header 4B][command + CRC-16]                 (csp_crc=false)
#
#  CommandFrame is the single source of truth for this layout --
#  both build_cmd_raw() and try_parse_command() delegate to it.
# =============================================================================

# Header offsets (shared between encode and decode)
_CMD_HDR_LEN = 6  # origin, dest, echo, ptype, id_len, args_len

class CommandFrame:
    """Symmetric encode/decode for the MAVERIC command wire format."""
    __slots__ = ("src", "dest", "echo", "pkt_type", "cmd_id", "args_str",
                 "args_raw", "crc", "crc_valid", "csp_crc32")

    def __init__(self, src, dest, echo, pkt_type, cmd_id, args_str="",
                 args_raw=b"", crc=None, crc_valid=None, csp_crc32=None):
        self.src = src
        self.dest = dest
        self.echo = echo
        self.pkt_type = pkt_type
        self.cmd_id = cmd_id
        self.args_str = args_str
        self.args_raw = args_raw
        self.crc = crc
        self.crc_valid = crc_valid
        self.csp_crc32 = csp_crc32

    def to_bytes(self):
        """Encode to raw wire bytes including CRC-16."""
        header = bytes([self.src & 0xFF, self.dest & 0xFF,
                        self.echo & 0xFF, self.pkt_type & 0xFF,
                        len(self.cmd_id) & 0xFF, len(self.args_str) & 0xFF])
        packet = bytearray(header)
        packet.extend(self.cmd_id.encode('ascii'))
        packet.append(0x00)
        packet.extend(self.args_str.encode('ascii'))
        packet.append(0x00)
        crc_val = crc16(packet)
        packet.extend(crc_val.to_bytes(2, byteorder='little'))
        return packet

    @classmethod
    def from_bytes(cls, payload):
        """Decode wire bytes into (CommandFrame, tail) or (None, None)."""
        if len(payload) < _CMD_HDR_LEN:
            return None, None

        src, dest, echo, pkt_type = payload[0], payload[1], payload[2], payload[3]
        id_len, args_len = payload[4], payload[5]

        if _CMD_HDR_LEN + id_len + 1 + args_len + 1 > len(payload):
            return None, None

        id_start = _CMD_HDR_LEN
        cmd_id = payload[id_start:id_start + id_len].decode("ascii", errors="replace").lower()

        null_pos = id_start + id_len
        if null_pos < len(payload) and payload[null_pos] == 0x00:
            null_pos += 1

        args_end = null_pos + args_len
        args_raw = bytes(payload[null_pos:args_end])
        args_str = args_raw.decode("ascii", errors="replace").strip()

        tail_start = args_end
        if tail_start < len(payload) and payload[tail_start] == 0x00:
            tail_start += 1

        # CRC-16 XMODEM (command integrity)
        crc_val = None
        crc_valid = None
        if tail_start + 2 <= len(payload):
            crc_val = payload[tail_start] | (payload[tail_start + 1] << 8)
            crc_valid = crc_val == crc16(payload[:tail_start])
            tail_start += 2

        # CRC-32C (CSP packet integrity) — consume if exactly 4 bytes remain
        csp_crc32 = None
        tail = payload[tail_start:]
        if len(tail) == 4:
            csp_crc32 = int.from_bytes(tail, 'big')
            tail = b""

        frame = cls(src, dest, echo, pkt_type, cmd_id, args_str,
                    args_raw, crc_val, crc_valid, csp_crc32)
        return frame, tail

    def to_dict(self):
        """Convert to dict (backward-compatible with old try_parse_command output)."""
        d = {
            "src": self.src, "dest": self.dest, "echo": self.echo,
            "pkt_type": self.pkt_type, "cmd_id": self.cmd_id,
            "args": self.args_str.split(), "crc": self.crc,
            "crc_valid": self.crc_valid, "csp_crc32": self.csp_crc32,
        }
        if self.args_raw:
            d["args_raw"] = self.args_raw
        return d


def build_cmd_raw(dest, cmd, args="", echo=0, ptype=1, origin=None):
    """Build raw MAVERIC command payload with CRC-16.
    Returns bytearray matching Commands.py wire format.
    Ready for CSP wrapping via CSPConfig.wrap()."""
    if origin is None:
        origin = GS_NODE
    return CommandFrame(origin, dest, echo, ptype, cmd, args).to_bytes()


def build_kiss_cmd(dest, cmd, args="", echo=0, ptype=1, origin=None):
    """Build a complete KISS-wrapped command.
    Returns (kiss_bytes, raw_bytes)."""
    raw = build_cmd_raw(dest, cmd, args, echo, ptype, origin)
    return kiss_wrap(raw), raw


def try_parse_command(payload):
    """Attempt to parse a byte payload as a MAVERIC command structure.

    Returns (parsed_dict, remaining_bytes) or (None, None) on failure.
    Uses CommandFrame.from_bytes() internally."""
    frame, tail = CommandFrame.from_bytes(payload)
    if frame is None:
        return None, None
    return frame.to_dict(), tail


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
        to 6 characters. SSID byte: 0b0RR_SSSS_E (E=1 if last address).

        *ssid* accepts either a 0-15 SSID value (standard) or a raw
        SSID byte (> 0x0F, e.g. 0x60 from GomSpace AX100 config).
        The extension bit is always managed automatically."""
        call = call.upper().ljust(6)[:6]
        addr = bytearray(ord(c) << 1 for c in call)
        if ssid > 0x0F:
            # Raw SSID byte — use directly, manage extension bit
            ssid_byte = ssid & 0xFE
            if last:
                ssid_byte |= 0x01
        else:
            # Standard 0-15 SSID value
            ssid_byte = 0x60 | ((ssid & 0x0F) << 1)
            if last:
                ssid_byte |= 0x01
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
        self.csp_crc = True   # append CRC-32C; set False if AX100 has csp_crc=false

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
        """Number of bytes the CSP header + optional CRC-32C add to a payload."""
        if not self.enabled:
            return 0
        return 8 if self.csp_crc else 4  # 4B header + optional 4B CRC-32C

    def wrap(self, payload):
        """Prepend CSP header and optionally append CRC-32C.

        Output: [CSP header 4B] [payload] [CRC-32C 4B BE] (if csp_crc)
                [CSP header 4B] [payload]                  (if not csp_crc)

        When csp_crc is False, no CRC-32C is appended — matching AX100
        config with csp_crc=false.  RS(255,223) still provides error
        detection/correction on the RF link."""
        if self.enabled:
            packet = self.build_header() + payload
            if self.csp_crc:
                checksum = crc32c(packet).to_bytes(4, 'big')
                return packet + checksum
            return packet
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

class _LazyEpochMs:
    """Lazy epoch-ms timestamp — stores raw ms, resolves to datetime on access.

    Behaves like a dict with keys "ms", "utc", "local" for backward
    compatibility with code that does isinstance(value, dict) checks
    or value["ms"] access.  The datetime objects are only created when
    first accessed, and cached thereafter."""
    __slots__ = ('ms', '_resolved')

    def __init__(self, ms):
        self.ms = ms
        self._resolved = None

    def _ensure(self):
        if self._resolved is None:
            dt_utc = datetime.fromtimestamp(self.ms / 1000.0, tz=timezone.utc)
            self._resolved = {"ms": self.ms, "utc": dt_utc, "local": dt_utc.astimezone()}
        return self._resolved

    def __contains__(self, key):
        return key in ("ms", "utc", "local")

    def __getitem__(self, key):
        return self._ensure()[key]

    def get(self, key, default=None):
        return self._ensure().get(key, default)


def _parse_epoch_ms(value_str):
    """Convert string to a lazy timestamp wrapper.

    Returns a _LazyEpochMs (dict-like with "ms", "utc", "local") if plausible.
    Returns original string if not a valid epoch-ms value.

    This is the only timestamp resolution path -- called by apply_schema()
    for epoch_ms typed args.  The datetime objects inside the wrapper are
    created lazily on first access, avoiding the cost for packets whose
    detail panel is never opened."""
    try:
        ms = int(value_str)
        if TS_MIN_MS <= ms <= TS_MAX_MS:
            return _LazyEpochMs(ms)
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


def _parse_arg_list(raw_list):
    """Parse a list of arg dicts from YAML into internal format."""
    args = []
    for a in (raw_list or []):
        name = a.get("name", f"arg{len(args)}")
        typ = a.get("type", "str")
        if typ not in _TYPE_PARSERS and typ != "blob":
            typ = "str"
        entry = {"name": name, "type": typ}
        if a.get("important"):
            entry["important"] = True
        args.append(entry)
    return args


def load_command_defs(path="maveric_commands.yml"):
    """Load command definitions from YAML.

    Schema format — per command (all fields optional):
      dest:     node name → resolved to int (enables shorthand TX entry)
      echo:     node name (default from defaults block)
      ptype:    ptype name (default from defaults block)
      tx_args:  args the operator sends (TX validation)
      rx_args:  args in the downlink response (RX parsing)
      rx_only:  true if command only appears in downlink
      variadic: true if extra args beyond tx_args are allowed

    Returns (defs, warning) where:
      defs: {cmd_id: {"tx_args", "rx_args", "variadic", "rx_only",
                       "dest", "echo", "ptype"}}
      warning: str or None — set when schema could not be loaded.
    Returns (empty dict, warning) on any failure."""
    if not _YAML_OK:
        msg = ("PyYAML not installed -- command schema unavailable. "
               "Install with: pip install pyyaml")
        warnings.warn(msg, stacklevel=2)
        return {}, msg
    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
        # Global defaults
        gd = raw.get("defaults") or {}
        def_echo = resolve_node(str(gd.get("echo", "NONE")))
        def_ptype = resolve_ptype(str(gd.get("ptype", "CMD")))
        if def_echo is None:
            def_echo = 0
        if def_ptype is None:
            def_ptype = 1

        defs = {}
        for cmd_id, spec in (raw.get("commands") or {}).items():
            spec = spec or {}
            tx_args = _parse_arg_list(spec.get("tx_args"))
            rx_args = _parse_arg_list(spec.get("rx_args"))

            # Resolve routing
            dest = None
            if "dest" in spec:
                dest = resolve_node(str(spec["dest"]))
            echo = resolve_node(str(spec["echo"])) if "echo" in spec else def_echo
            ptype = resolve_ptype(str(spec["ptype"])) if "ptype" in spec else def_ptype

            defs[cmd_id.lower()] = {
                "tx_args":  tx_args,
                "rx_args":  rx_args,
                "variadic": spec.get("variadic", False),
                "rx_only":  spec.get("rx_only", False),
                "dest":     dest,
                "echo":     echo if echo is not None else 0,
                "ptype":    ptype if ptype is not None else 1,
            }
        return defs, None
    except (OSError, yaml.YAMLError, AttributeError):
        msg = f"Could not load {path} -- all commands will be unrecognized"
        warnings.warn(msg, stacklevel=2)
        return {}, msg


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
    rx_args = defn["rx_args"]
    typed = []
    sat_time = None

    for i, arg_def in enumerate(rx_args):
        if arg_def["type"] == "blob":
            # Extract remaining raw bytes after preceding text args
            args_raw = cmd.get("args_raw", b"")
            offset = 0
            for _ in range(i):
                sp = args_raw.find(0x20, offset)
                if sp == -1:
                    break
                offset = sp + 1
            value = bytes(args_raw[offset:])
            typed.append({"name": arg_def["name"], "type": "blob", "value": value})
            break  # blob consumes everything remaining
        if i < len(raw_args):
            parser = _TYPE_PARSERS.get(arg_def["type"], str)
            try:
                value = parser(raw_args[i])
            except (ValueError, TypeError):
                value = raw_args[i]
            ta = {
                "name":  arg_def["name"],
                "type":  arg_def["type"],
                "value": value,
            }
            if arg_def.get("important"):
                ta["important"] = True
            typed.append(ta)
            # Surface the first resolved timestamp for SAT TIME display
            if arg_def["type"] == "epoch_ms" and isinstance(value, (_LazyEpochMs, dict)) and sat_time is None:
                sat_time = (value["utc"], value["local"], value["ms"])

    extra = raw_args[len(rx_args):]

    cmd["typed_args"]   = typed
    cmd["extra_args"]   = extra
    cmd["sat_time"]     = sat_time
    cmd["schema_match"] = True
    cmd["dest_default"] = defn.get("dest")
    cmd["rx_only"]      = defn.get("rx_only", False)
    return True


def validate_args(cmd_id, args_str, cmd_defs):
    """Validate args string against schema before sending (TX side).

    Returns (is_valid, list_of_issues).
    If cmd_id is not in schema, returns (True, []) -- unknown commands
    are allowed through without validation."""
    if not cmd_defs or cmd_id not in cmd_defs:
        return True, []

    defn = cmd_defs[cmd_id]
    if defn.get("rx_only"):
        return False, [f"'{cmd_id}' is receive-only"]

    raw_args = args_str.split() if args_str else []
    tx_args = defn["tx_args"]
    issues = []

    if len(raw_args) < len(tx_args):
        issues.append(
            f"expected {len(tx_args)} args, got {len(raw_args)}"
        )

    if len(raw_args) > len(tx_args) and not defn["variadic"]:
        issues.append(
            f"extra args: expected {len(tx_args)}, got {len(raw_args)}"
        )

    for i, arg_def in enumerate(tx_args):
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
    for keyword, label in (("AX.25", "AX.25"), ("AX100", "ASM+GOLAY")):
        if keyword in tx_info:
            return label
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
    if frame_type != "ASM+GOLAY":
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

    Returns (src, dest, echo, ptype, cmd, args).
    Raises ValueError with a specific message on failure."""
    parts = line.split(None, 5)
    if len(parts) < 4:
        raise ValueError("need at least: <dest> <echo> <type> <cmd>")

    # Detect format: if parts[3] is a valid ptype, first token is SRC
    ptype3 = resolve_ptype(parts[3]) if len(parts) >= 5 else None
    if ptype3 is not None:
        offset, src = 1, resolve_node(parts[0])
        if src is None:
            raise ValueError(f"unknown source node '{parts[0]}'")
        ptype = ptype3
    else:
        offset, src = 0, GS_NODE
        ptype = resolve_ptype(parts[2])
        if ptype is None:
            raise ValueError(f"unknown packet type '{parts[2]}'")

    dest = resolve_node(parts[offset])
    if dest is None:
        raise ValueError(f"unknown destination node '{parts[offset]}'")
    echo = resolve_node(parts[offset + 1])
    if echo is None:
        raise ValueError(f"unknown echo node '{parts[offset + 1]}'")

    cmd_idx = offset + 3
    args = " ".join(parts[cmd_idx + 1:]) if len(parts) > cmd_idx + 1 else ""
    return (src, dest, echo, ptype, parts[cmd_idx].lower(), args)


# =============================================================================
#  UTILITIES
# =============================================================================

def format_arg_value(typed_arg):
    """Format a schema-typed argument value for display/logging.

    For epoch_ms args with resolved dicts, returns the ms string.
    For all other args, returns str(value)."""
    if typed_arg["type"] == "epoch_ms" and isinstance(typed_arg["value"], (_LazyEpochMs, dict)):
        return str(typed_arg["value"]["ms"])
    return str(typed_arg["value"])


_CLEAN_TABLE = bytearray(0xB7 for _ in range(256))  # middle dot (·) in latin-1
for _b in range(32, 127):
    _CLEAN_TABLE[_b] = _b
_CLEAN_TABLE = bytes(_CLEAN_TABLE)


def clean_text(data: bytes) -> str:
    """Printable ASCII representation with non-printable bytes as middle dot."""
    return data.translate(_CLEAN_TABLE).decode('latin-1')


