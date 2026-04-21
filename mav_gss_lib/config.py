"""
mav_gss_lib.config -- Shared Configuration Loader

Reads gss.yml from the mav_gss_lib package directory and returns a dict with
platform-level settings. Mission-specific defaults are provided by
the active mission package's mission.yml via the mission loader.
Falls back to hardcoded defaults if the file is missing.

Author:  Irfan Annuar - USC ISI SERC
"""

import copy
import json
import os
import tempfile
from pathlib import Path

import yaml

# Resolve library/project directories relative to this file, not CWD
_LIB_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_GSS_PATH = _LIB_DIR / "gss.yml"


def _read_version() -> str:
    """Single source of truth: web/package.json."""
    pkg_json = _LIB_DIR / "web" / "package.json"
    try:
        with open(pkg_json) as f:
            return json.load(f).get("version", "0.0.0")
    except (OSError, ValueError):
        return "0.0.0"


def _read_build_sha() -> str:
    """Short git SHA of the working tree, resolved at module import.

    Runtime-derived (not baked into the JS bundle), so a backend-only
    commit no longer dirties dist/. Returned via /api/config as
    general.build_sha and displayed on the preflight screen.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if result.returncode == 0:
            return result.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


from mav_gss_lib.constants import (
    DEFAULT_MISSION,
    DEFAULT_RX_ZMQ_ADDR,
    DEFAULT_TX_ZMQ_ADDR,
)

_DEFAULTS = {
    "tx": {
        "zmq_addr":  DEFAULT_TX_ZMQ_ADDR,
        "delay_ms":  500,
    },
    "rx": {
        "zmq_addr": DEFAULT_RX_ZMQ_ADDR,
        "tx_blackout_ms": 0,
    },
    "general": {
        "mission":      DEFAULT_MISSION,
        "version":      _read_version(),
        "build_sha":    _read_build_sha(),
        "log_dir":      "logs",
        "generated_commands_dir": "generated_commands",
        "station_id":   None,
    },
}


def deep_merge(base, override):
    """Merge *override* into *base*, returning a new dict.

    Uses copy.deepcopy on *base* so the returned dict does not alias any
    nested dicts in *base* (important when base is _DEFAULTS — otherwise
    a later in-place mutation would corrupt module-level defaults).
    """
    merged = copy.deepcopy(base)
    for k, v in override.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = deep_merge(merged[k], v)
        else:
            merged[k] = copy.deepcopy(v) if isinstance(v, (dict, list)) else v
    return merged


def deep_merge_inplace(base: dict, override: dict) -> None:
    """Mutate *base* in place, merging *override* into it.

    Deep-copies nested dict/list values from *override* to prevent aliasing
    into the caller's override structure.
    """
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            deep_merge_inplace(base[k], v)
        else:
            base[k] = copy.deepcopy(v) if isinstance(v, (dict, list)) else v


def load_gss_config(path=None):
    """Load config from YAML, falling back to defaults for missing keys."""
    if path is None:
        path = str(_DEFAULT_GSS_PATH)
    user = {}
    if os.path.isfile(path):
        with open(path, "r") as f:
            raw = yaml.safe_load(f)
        if isinstance(raw, dict):
            user = raw
    return deep_merge(_DEFAULTS, user)


def resolve_project_path(path_value, *, base_dir=None):
    """Resolve a config path relative to the chosen base directory when needed."""
    path = Path(path_value)
    if path.is_absolute():
        return path
    root = _PROJECT_ROOT if base_dir is None else Path(base_dir)
    return (root / path).resolve()


def get_rx_zmq_addr(cfg: dict) -> str:
    return cfg.get("rx", {}).get("zmq_addr", DEFAULT_RX_ZMQ_ADDR)


def get_tx_zmq_addr(cfg: dict) -> str:
    return cfg.get("tx", {}).get("zmq_addr", DEFAULT_TX_ZMQ_ADDR)


def get_generated_commands_dir(cfg):
    """Return the resolved import/export directory for queue JSONL files."""
    general = cfg.get("general", {})
    raw = general.get("generated_commands_dir", "generated_commands")
    return resolve_project_path(raw)


def get_operator_config_path() -> Path:
    """Return the on-disk path for the operator gss.yml (used by /api/selfcheck).
    The _DEFAULT_GSS_PATH module constant stays private."""
    return _DEFAULT_GSS_PATH


def load_operator_config_raw() -> dict:
    """Read the operator gss.yml as-is (no defaults merge). Returns {} if absent."""
    p = Path(_DEFAULT_GSS_PATH) if not isinstance(_DEFAULT_GSS_PATH, Path) else _DEFAULT_GSS_PATH
    if not p.is_file():
        return {}
    with open(p) as f:
        return yaml.safe_load(f) or {}


def save_operator_config_raw(merged: dict) -> None:
    """Atomic write *merged* to the operator gss.yml. Caller MUST have stripped
    any keys that should not persist (mission-owned, platform-derived, etc.)."""
    save_gss_config(merged)


def save_gss_config(cfg, path=None):
    """Atomically write current config back to YAML.

    Writes to a temp file first, then renames — prevents truncated files
    if the process is killed mid-write.
    """
    if path is None:
        path = str(_DEFAULT_GSS_PATH)
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
# apply_*() reads cfg -> object.

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


def apply_ax25(cfg, ax25):
    """Apply config dict values to an AX25Config object."""
    section = cfg.get("ax25")
    if section:
        _apply_map(section, ax25, _AX25_MAP)


def apply_csp(cfg, csp):
    """Apply config dict values to a CSPConfig object."""
    section = cfg.get("csp")
    if section:
        _apply_map(section, csp, _CSP_MAP)
