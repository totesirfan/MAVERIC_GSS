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
        "version":      "2.2.1",
        "log_dir":      "logs",
        "command_defs": "maveric_commands.yml",
        "decoder_yml":  "maveric_decoder.yml",
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
