"""
mav_gss_lib.config -- Shared Configuration Loader

Reads maveric_gss.yml from the project root and returns a dict with
all configurable values.  Falls back to hardcoded defaults if the
file is missing so the scripts still work without it.

Author:  Irfan Annuar - USC ISI SERC
"""

import os
import yaml


_DEFAULTS = {
    "nodes": {
        0: "NONE", 1: "LPPM", 2: "EPS", 3: "UPPM",
        4: "HOLONAV", 5: "ASTROBOARD", 6: "GS", 7: "FTDI",
    },
    "ptypes": {
        0: "NONE", 1: "REQ", 2: "RES", 3: "ACK",
    },
    "ax25": {
        "src_call":  "WM2XBB",
        "src_ssid":  0,
        "dest_call": "WS9XSW",
        "dest_ssid": 0,
    },
    "csp": {
        "priority":    2,
        "source":      0,
        "destination": 8,
        "dest_port":   0,
        "src_port":    24,
        "flags":       0x00,
    },
    "tx": {
        "zmq_addr":  "tcp://127.0.0.1:52002",
        "frequency": "437.25 MHz",
        "delay_ms":  500,
    },
    "rx": {
        "zmq_port": 52001,
        "zmq_addr": "tcp://127.0.0.1:52001",
    },
    "general": {
        "version":      "2.3.5",
        "log_dir":      "logs",
        "command_defs": "maveric_commands.yml",
        "decoder_yml":  "maveric_decoder.yml",
        "gs_node":      "GS",
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


def load_gss_config(path="maveric_gss.yml"):
    """Load config from YAML, falling back to defaults for missing keys."""
    if os.path.isfile(path):
        with open(path, "r") as f:
            user = yaml.safe_load(f) or {}
        return _deep_merge(_DEFAULTS, user)
    return dict(_DEFAULTS)


def apply_ax25(cfg, ax25):
    """Apply config dict values to an AX25Config object."""
    a = cfg["ax25"]
    ax25.src_call  = a["src_call"]
    ax25.src_ssid  = int(a["src_ssid"])
    ax25.dest_call = a["dest_call"]
    ax25.dest_ssid = int(a["dest_ssid"])


def apply_csp(cfg, csp):
    """Apply config dict values to a CSPConfig object."""
    c = cfg["csp"]
    csp.prio  = int(c["priority"])
    csp.src   = int(c["source"])
    csp.dest  = int(c["destination"])
    csp.dport = int(c["dest_port"])
    csp.sport = int(c["src_port"])
    csp.flags = int(c["flags"])


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
        return (f"CSP  Prio:{csp.prio} Src:{csp.src} "
                f"Dest:{csp.dest} DPort:{csp.dport} SPort:{csp.sport} "
                f"Flags:0x{csp.flags:02X}  ({hdr.hex(' ')})")
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
