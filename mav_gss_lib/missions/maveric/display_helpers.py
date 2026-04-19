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


def has_decoded_gnc(mission_data: dict) -> bool:
    """True if any GNC register decoded successfully.

    When a register decode succeeds the decoded block carries the full
    operator-useful value, so the raw `reg_id`/`raw_bytes` request args
    are redundant — suppress them the same way `eps_hk` telemetry does.
    """
    regs = mission_data.get("gnc_registers") or {}
    return any(snap.get("decode_ok") for snap in regs.values())


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
