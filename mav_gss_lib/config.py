"""
mav_gss_lib.config -- Shared Configuration Loader

Reads maveric_gss.yml from the project root and returns a dict with
all configurable values.  Falls back to hardcoded defaults if the
file is missing so the scripts still work without it.

Author:  Irfan Annuar - USC ISI SERC
"""

import os
import tempfile
from pathlib import Path

import yaml

# Resolve config directory relative to this file, not CWD
_CONFIG_DIR = Path(__file__).resolve().parent / "config"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


_DEFAULTS = {
    "nodes": {},
    "ptypes": {},
    "node_descriptions": {},
    "ax25": {
        "src_call":  "NOCALL",
        "src_ssid":  0,
        "dest_call": "NOCALL",
        "dest_ssid": 0,
    },
    "csp": {
        "priority":    2,
        "source":      0,
        "destination": 0,
        "dest_port":   0,
        "src_port":    0,
        "flags":       0x00,
        "csp_crc":     True,
    },
    "tx": {
        "zmq_addr":  "tcp://127.0.0.1:52002",
        "frequency": "",
        "delay_ms":  500,
        "uplink_mode": "AX.25",
    },
    "rx": {
        "zmq_port": 52001,
        "zmq_addr": "tcp://127.0.0.1:52001",
    },
    "general": {
        "version":      "4.3.1",
        "log_dir":      "logs",
        "generated_commands_dir": "generated_commands",
    },
}


def _deep_merge(base, override):
    """Merge *override* into *base*, returning a new dict."""
    merged = dict(base)
    for k, v in override.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def load_gss_config(path=None):
    """Load config from YAML, falling back to defaults for missing keys."""
    if path is None:
        path = str(_CONFIG_DIR / "maveric_gss.yml")
    user = {}
    if os.path.isfile(path):
        with open(path, "r") as f:
            raw = yaml.safe_load(f)
        if isinstance(raw, dict):
            user = raw
    return _deep_merge(_DEFAULTS, user)


def resolve_project_path(path_value, *, base_dir=None):
    """Resolve a config path relative to the chosen base directory when needed."""
    path = Path(path_value)
    if path.is_absolute():
        return path
    root = _PROJECT_ROOT if base_dir is None else Path(base_dir)
    return (root / path).resolve()


def get_decoder_yml_path(cfg):
    """Return the resolved decoder YAML path from config."""
    general = cfg.get("general", {})
    raw = general.get("decoder_yml", "maveric_decoder.yml")
    return str(resolve_project_path(raw, base_dir=_CONFIG_DIR))


def get_generated_commands_dir(cfg):
    """Return the resolved import/export directory for queue JSONL files."""
    general = cfg.get("general", {})
    raw = general.get("generated_commands_dir", "generated_commands")
    return resolve_project_path(raw)


def save_gss_config(cfg, path=None):
    """Atomically write current config back to YAML.

    Writes to a temp file first, then renames — prevents truncated files
    if the process is killed mid-write.
    """
    if path is None:
        path = str(_CONFIG_DIR / "maveric_gss.yml")
    dir_name = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=dir_name)
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# -- Bidirectional config mapping ---------------------------------------------
#
# Each entry maps:  (cfg_section, cfg_key) <-> (object_attr)
# apply_*() reads cfg -> object;  update_cfg_from_state() writes object -> cfg.

_AX25_MAP = [
    ("src_call",  "src_call"),
    ("src_ssid",  "src_ssid",  int),
    ("dest_call", "dest_call"),
    ("dest_ssid", "dest_ssid", int),
]

_CSP_MAP = [
    ("priority",    "prio",    int),
    ("source",      "src",     int),
    ("destination", "dest",    int),
    ("dest_port",   "dport",   int),
    ("src_port",    "sport",   int),
    ("flags",       "flags",   int),
    ("csp_crc",     "csp_crc", bool),
]


def _apply_map(cfg_section, obj, mapping):
    """Apply config dict values to an object using a mapping list."""
    for cfg_key, attr, *rest in mapping:
        val = cfg_section[cfg_key]
        setattr(obj, attr, rest[0](val) if rest else val)


def _sync_to_cfg(cfg_section, obj, mapping):
    """Sync object values back into a config dict section."""
    for entry in mapping:
        cfg_key, attr = entry[0], entry[1]
        cfg_section[cfg_key] = getattr(obj, attr)


def apply_ax25(cfg, ax25):
    """Apply config dict values to an AX25Config object."""
    _apply_map(cfg["ax25"], ax25, _AX25_MAP)


def apply_csp(cfg, csp):
    """Apply config dict values to a CSPConfig object."""
    _apply_map(cfg["csp"], csp, _CSP_MAP)


def update_cfg_from_state(cfg, csp, ax25, freq=None, zmq_addr=None, tx_delay_ms=None,
                          uplink_mode=None):
    """Sync runtime state back into the config dict for saving."""
    _sync_to_cfg(cfg["ax25"], ax25, _AX25_MAP)
    _sync_to_cfg(cfg["csp"], csp, _CSP_MAP)
    tx_updates = {"frequency": freq, "zmq_addr": zmq_addr,
                  "delay_ms": tx_delay_ms, "uplink_mode": uplink_mode}
    for key, val in tx_updates.items():
        if val is not None:
            cfg["tx"][key] = val


def ax25_handle_msg(ax25, args):
    """Handle AX.25 config command, return status message."""
    if not args:
        return (f"AX.25  Dest:{ax25.dest_call}-{ax25.dest_ssid}  "
                f"Src:{ax25.src_call}-{ax25.src_ssid}")
    parts = args.split()
    cmd = parts[0].lower()
    if cmd == 'dest' and len(parts) > 1:
        ax25.dest_call = parts[1].upper()[:6]
        if len(parts) > 2 and parts[2].isdigit():
            ax25.dest_ssid = int(parts[2]) & 0x0F
        return f"AX.25 dest = {ax25.dest_call}-{ax25.dest_ssid}"
    elif cmd == 'src' and len(parts) > 1:
        ax25.src_call = parts[1].upper()[:6]
        if len(parts) > 2 and parts[2].isdigit():
            ax25.src_ssid = int(parts[2]) & 0x0F
        return f"AX.25 src = {ax25.src_call}-{ax25.src_ssid}"
    return "ax25 [dest <call> [ssid]|src <call> [ssid]]"


def csp_handle_msg(csp, args):
    """Handle CSP config command, return status message."""
    if not args:
        hdr = csp.build_header()
        crc_label = "ON" if csp.csp_crc else "OFF"
        return (f"CSP  Prio:{csp.prio} Src:{csp.src} "
                f"Dest:{csp.dest} DPort:{csp.dport} SPort:{csp.sport} "
                f"Flags:0x{csp.flags:02X} CRC32:{crc_label}  ({hdr.hex(' ')})")
    parts = args.split()
    cmd = parts[0].lower()
    if cmd in ('prio', 'src', 'dest', 'dport', 'sport', 'flags') and len(parts) > 1:
        try:
            val = int(parts[1], 0)
        except ValueError:
            return f"Invalid value: {parts[1]}"
        setattr(csp, cmd, val)
        return f"CSP {cmd} = {val}"
    return "csp [prio|src|dest|dport|sport|flags] [value]"
