"""MAVERIC command schema loading and validation.

Loads command definitions from `commands.yml`, applies typed argument
parsing to received commands (`enrich_cmd_in_place`), and validates TX
arguments before sending (`validate_args`).

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import os
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mav_gss_lib.missions.maveric.nodes import NodeTable


_MISSION_DIR = Path(__file__).resolve().parent

try:
    import yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False


TS_MIN_MS = 1_704_067_200_000  # ~2024-01-01
TS_MAX_MS = 1_830_297_600_000  # ~2028-01-01

class _LazyEpochMs:
    """Lazy epoch-ms timestamp -- stores raw ms, resolves to datetime on access.

    Behaves like a dict with keys "ms", "utc", "local" for backward
    compatibility with code that does isinstance(value, dict) checks
    or value["ms"] access.  The datetime objects are only created when
    first accessed, and cached thereafter."""
    __slots__ = ('ms', '_resolved')
    ms: int
    _resolved: dict | None

    def __init__(self, ms: int) -> None:
        self.ms = ms
        self._resolved = None

    def _ensure(self) -> dict[str, Any]:
        if self._resolved is None:
            dt_utc = datetime.fromtimestamp(self.ms / 1000.0, tz=timezone.utc)
            self._resolved = {"ms": self.ms, "utc": dt_utc, "local": dt_utc.astimezone()}
        return self._resolved

    def __contains__(self, key: str) -> bool:
        return key in ("ms", "utc", "local")

    def __getitem__(self, key: str) -> Any:
        return self._ensure()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._ensure().get(key, default)


def _parse_epoch_ms(value_str: str) -> "_LazyEpochMs | str":
    """Convert string to a lazy timestamp wrapper."""
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


def _coerce_arg(arg_def: dict, raw: str) -> tuple[object, bool]:
    """Return ``(value, ok)`` for a single scalar schema arg.

    ``ok`` is False when the type parser raised; the caller decides
    whether to treat that as a validation issue (``validate_args``) or to
    keep the raw string as the value (``enrich_cmd_in_place``).

    Not valid for ``blob`` args — callers must handle blob before dispatch.
    """
    arg_type = arg_def["type"]
    if arg_type == "blob":
        raise ValueError("_coerce_arg called for blob; handle upstream")
    parser = _TYPE_PARSERS.get(arg_type, str)
    try:
        return parser(raw), True
    except (ValueError, TypeError):
        return raw, False


def _parse_arg_list(raw_list: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Parse a list of arg dicts from YAML into internal format."""
    args: list[dict[str, Any]] = []
    for a in (raw_list or []):
        name = a.get("name", f"arg{len(args)}")
        typ = a.get("type", "str")
        if typ not in _TYPE_PARSERS and typ != "blob":
            typ = "str"
        entry = {"name": name, "type": typ}
        if a.get("important"):
            entry["important"] = True
        if a.get("optional"):
            entry["optional"] = True
        args.append(entry)
    return args


def load_command_defs(
    path: str | None = None,
    nodes: "NodeTable | None" = None,
) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Load command definitions from YAML.

    Args:
        path: Path to commands.yml. Defaults to mission package dir.
        nodes: NodeTable for resolving routing names to IDs.
               If None, routing defaults (dest/echo/ptype) are not resolved.

    Returns (defs, warning) where:
      defs: {cmd_id: {"tx_args", "rx_args", "variadic", "rx_only",
                       "dest", "echo", "ptype"}}
      warning: str or None -- set when schema could not be loaded.
    """
    if path is None:
        path = str(_MISSION_DIR / "commands.yml")
    elif not os.path.isabs(path):
        path = str((_MISSION_DIR / path).resolve())
    if not _YAML_OK:
        msg = ("PyYAML not installed -- command schema unavailable. "
               "Install with: pip install pyyaml")
        warnings.warn(msg, stacklevel=2)
        return {}, msg

    def _resolve_node(s: str) -> int | None:
        return nodes.resolve_node(s) if nodes else None

    def _resolve_ptype(s: str) -> int | None:
        return nodes.resolve_ptype(s) if nodes else None

    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
        # Global defaults
        gd = raw.get("defaults") or {}
        def_echo = _resolve_node(str(gd.get("echo", "NONE")))
        def_ptype = _resolve_ptype(str(gd.get("ptype", "CMD")))
        if def_echo is None:
            def_echo = 0
        if def_ptype is None:
            def_ptype = 1

        defs = {}
        for cmd_id, spec in (raw.get("commands") or {}).items():
            spec = spec or {}
            tx_args = _parse_arg_list(spec.get("tx_args"))
            rx_args = _parse_arg_list(spec.get("rx_args"))
            if len(tx_args) <= 5:
                for a in tx_args:
                    a["important"] = True
            if len(rx_args) <= 5:
                for a in rx_args:
                    a["important"] = True

            # Resolve routing
            dest = None
            if "dest" in spec:
                dest = _resolve_node(str(spec["dest"]))
            echo = _resolve_node(str(spec["echo"])) if "echo" in spec else def_echo
            ptype = _resolve_ptype(str(spec["ptype"])) if "ptype" in spec else def_ptype

            defs[cmd_id.lower()] = {
                "tx_args":  tx_args,
                "rx_args":  rx_args,
                "variadic": spec.get("variadic", False),
                "rx_only":  spec.get("rx_only", False),
                "nodes":    spec.get("nodes", []),
                "dest":     dest,
                "echo":     echo if echo is not None else 0,
                "ptype":    ptype if ptype is not None else 1,
            }
        return defs, None
    except (OSError, yaml.YAMLError, AttributeError):
        msg = f"Could not load {path} -- all commands will be unrecognized"
        warnings.warn(msg, stacklevel=2)
        return {}, msg


def enrich_cmd_in_place(cmd: dict, cmd_defs: dict) -> bool:
    """Mutate *cmd* in place with typed argument values, schema flags, and
    derived fields.

    If cmd_id is found in cmd_defs, sets on cmd:
        typed_args, extra_args, sat_time, schema_match, dest_default, rx_only.
    If not found, sets: schema_match=False, schema_warning.
    Returns True if the command id matched the schema, False otherwise.
    The return value is consumed only by tests; production callers discard it.
    """
    if not cmd_defs or cmd["cmd_id"] not in cmd_defs:
        cmd["schema_match"] = False
        cmd["schema_warning"] = (
            f"Unknown command '{cmd['cmd_id']}' "
            "-- add to commands.yml for typed parsing"
        )
        return False

    defn = cmd_defs[cmd["cmd_id"]]
    raw_args = cmd["args"]
    rx_args = defn["rx_args"]
    typed = []
    sat_time = None
    blob_consumed_tail = False

    for i, arg_def in enumerate(rx_args):
        if arg_def["type"] == "blob":
            args_raw = cmd.get("args_raw", b"")
            offset = 0
            for _ in range(i):
                sp = args_raw.find(0x20, offset)
                if sp == -1:
                    break
                offset = sp + 1
            value = bytes(args_raw[offset:])
            typed.append({"name": arg_def["name"], "type": "blob", "value": value})
            blob_consumed_tail = True
            break
        if i < len(raw_args):
            value, _ok = _coerce_arg(arg_def, raw_args[i])
            ta = {
                "name":  arg_def["name"],
                "type":  arg_def["type"],
                "value": value,
            }
            if arg_def.get("important"):
                ta["important"] = True
            typed.append(ta)
            if arg_def["type"] == "epoch_ms" and isinstance(value, (_LazyEpochMs, dict)) and sat_time is None:
                sat_time = (value["utc"], value["local"], value["ms"])

    extra = [] if blob_consumed_tail else raw_args[len(rx_args):]

    cmd["typed_args"]   = typed
    cmd["extra_args"]   = extra
    cmd["sat_time"]     = sat_time
    cmd["schema_match"] = True
    cmd["dest_default"] = defn.get("dest")
    cmd["rx_only"]      = defn.get("rx_only", False)
    return True


def validate_args(
    cmd_id: str,
    args_str: str,
    cmd_defs: dict[str, dict[str, Any]],
) -> tuple[bool, list[str]]:
    """Validate args string against schema before sending (TX side).

    Returns (is_valid, list_of_issues)."""
    if not cmd_defs or cmd_id not in cmd_defs:
        return True, []

    defn = cmd_defs[cmd_id]
    if defn.get("rx_only"):
        return False, [f"'{cmd_id}' is receive-only"]

    tx_args = defn["tx_args"]
    # If the final tx_arg is str (non-variadic), let it swallow trailing
    # whitespace — e.g. cfg_set_tle carries a multi-token TLE as one arg.
    if args_str:
        if tx_args and tx_args[-1].get("type") == "str" and not defn["variadic"]:
            raw_args = args_str.split(None, len(tx_args) - 1)
        else:
            raw_args = args_str.split()
    else:
        raw_args = []
    issues = []

    required = sum(1 for a in tx_args if not a.get("optional"))
    if len(raw_args) < required:
        issues.append(
            f"expected at least {required} args, got {len(raw_args)}"
        )

    if len(raw_args) > len(tx_args) and not defn["variadic"]:
        issues.append(
            f"extra args: expected {len(tx_args)}, got {len(raw_args)}"
        )

    for i, arg_def in enumerate(tx_args):
        if i >= len(raw_args):
            break
        if arg_def["type"] == "blob":
            # Blob args are raw bytes on the wire — no scalar validation.
            # Matches the pre-refactor behavior where _TYPE_PARSERS.get
            # defaulted to ``str`` and always accepted.
            continue
        _value, ok = _coerce_arg(arg_def, raw_args[i])
        if not ok:
            issues.append(
                f"arg '{arg_def['name']}': '{raw_args[i]}' is not valid {arg_def['type']}"
            )

    return not issues, issues
