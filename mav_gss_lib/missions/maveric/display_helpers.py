"""MAVERIC display helpers — shared between rendering.py and log_format.py.

These are the shared scalar helpers and shape predicates used by both the
detail-block renderer (rendering.py) and the text-log formatter
(log_format.py). The formatters themselves differ (dict envelope vs text
line with summary) so they stay in their respective files — only guards
and unwrappers are shared.

Author:  Irfan Annuar - USC ISI SERC
"""
from __future__ import annotations

from typing import Any


# ---------- packet-level helpers ----------

def md(pkt: Any) -> dict:
    """Read mission data from a packet (dataclass or any object)."""
    return getattr(pkt, "mission_data", {}) or {}


def ptype_of(mission_data: dict) -> int | None:
    """Return the display ptype for a packet.

    rx_ops.parse_packet populates mission_data["ptype"] as the single
    normalization point. This helper tolerates fixtures that build
    mission_data by hand and only set cmd["pkt_type"].
    """
    pt = mission_data.get("ptype")
    if pt is not None:
        return pt
    cmd = mission_data.get("cmd")
    return cmd.get("pkt_type") if cmd else None


def has_decoded_gnc(mission_data: dict) -> bool:
    """True iff the packet produced at least one `gnc` fragment.

    When a GNC register is decoded, the decoded block carries the full
    operator-useful value, so the raw `reg_id`/`raw_bytes` request args
    are redundant — suppress them the same way `eps_hk` fragments do.
    Equivalent (post-v2) to the legacy check that walked
    mission_data["gnc_registers"] for any decode_ok=True entry, because
    the extractor already filters decode_ok=False entries out.
    """
    frags = mission_data.get("fragments") or []
    return any(f.get("domain") == "gnc" for f in frags)


# cmd_ids whose raw typed_args would render as garbage (binary parsed as
# ASCII) and should be hidden in favor of their decoded fragments. Kept
# as a mission-local constant so a future additional cmd_id is a one-
# line change in one file.
_HIDE_ARGS_CMD_IDS = frozenset({"eps_hk"})


def should_hide_args(cmd: dict | None, mission_data: dict) -> bool:
    """Shared predicate: should the raw typed_args view be suppressed?

    True when either the cmd_id is in the explicit hide list, or the
    packet produced at least one `gnc` fragment. Both log_format.py and
    rendering.py import this — the hide rule lives in one place, not two.
    """
    cmd_id = (cmd or {}).get("cmd_id")
    if cmd_id in _HIDE_ARGS_CMD_IDS:
        return True
    return has_decoded_gnc(mission_data)


# ---------- typed-arg unwrappers ----------

def _is_epoch_ms_wrapper(v: Any) -> bool:
    """True for dict or _LazyEpochMs epoch_ms wrappers.

    Must NOT use `"ms" in v` duck-typing: for a string like "24ms"
    (which schema._parse_epoch_ms returns on failed parse), substring
    semantics would return True and `v["ms"]` would crash.
    """
    if isinstance(v, dict):
        return True
    return hasattr(v, "ms") and hasattr(v, "__getitem__")


def _read_ms(v: Any) -> Any:
    """Extract `ms` from either a dict or a _LazyEpochMs wrapper."""
    return v["ms"] if isinstance(v, dict) else v.ms


def epoch_ms_of(val: Any) -> int | None:
    """Return the integer ms from a dict wrapper, a _LazyEpochMs, or a
    bare int/str. Returns None if *val* carries no usable ms value.

    Use this at display-path sites that only need the integer and don't
    also read ``utc``/``local``.
    """
    if val is None:
        return None
    if _is_epoch_ms_wrapper(val):
        return _read_ms(val)
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        try:
            return int(val)
        except ValueError:
            return None
    return None


def unwrap_typed_arg_for_log(typed_arg: dict) -> Any:
    """Unwrap a typed_arg dict for JSONL logging. Preserves native types."""
    t = typed_arg["type"]
    v = typed_arg["value"]
    if t == "epoch_ms" and _is_epoch_ms_wrapper(v):
        return _read_ms(v)
    if t == "blob" and isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).hex()
    return v


def format_typed_arg_value(typed_arg: dict) -> str:
    """Format a schema-typed argument value for text-log display.

    Byte-for-byte compatible replacement for schema.format_arg_value.
    """
    if typed_arg["type"] == "epoch_ms" and _is_epoch_ms_wrapper(typed_arg["value"]):
        return str(_read_ms(typed_arg["value"]))
    return str(typed_arg["value"])


def unwrap_typed_arg_for_display(typed_arg: dict) -> Any:
    """Return the raw value of a typed arg, hexing bytes for display.

    Used on the rendering args-rail where each value is then str()'d.
    """
    t = typed_arg["type"]
    v = typed_arg.get("value", "")
    if t == "epoch_ms":
        if hasattr(v, "ms"):
            return v.ms
        if isinstance(v, dict) and "ms" in v:
            return v["ms"]
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    return v


# ---------- register-shape predicates ----------
#
# ORDER IS LOAD-BEARING. Both rendering.py and log_format.py dispatch
# through these in this order. First match wins.


def is_nvg_sensor(value: Any) -> bool:
    return isinstance(value, dict) and "sensor_id" in value and "values" in value


def is_bcd_display(value: Any) -> bool:
    return isinstance(value, dict) and "display" in value and isinstance(value["display"], str)


def is_adcs_tmp(value: Any) -> bool:
    return isinstance(value, dict) and "celsius" in value


def is_nvg_heartbeat(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and "label" in value
        and "status" in value
        and "sensor_id" not in value
        and "mode" not in value
    )


def is_gnc_mode(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and "mode_name" in value
        and "mode" in value
        and "MODE" not in value
    )


def is_gnc_counters(value: Any) -> bool:
    return isinstance(value, dict) and "sunspin" in value and "detumble" in value


def is_bitfield(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    has_bool_flags = any(isinstance(v, bool) for v in value.values())
    return has_bool_flags or "MODE" in value or "TARGET_ELEV" in value


def is_generic_dict(value: Any) -> bool:
    """Dict fallback — last dict probe before scalar/list."""
    return isinstance(value, dict)
