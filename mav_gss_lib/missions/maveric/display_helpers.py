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


# ---------- shared shape-dispatch table ----------
#
# One entry per decoded-value shape. Each entry ships three callables:
#   matches       — predicate (already defined above)
#   compact_fn    — render as one display string
#   detail_fn     — render as a list[{name, value}] (packet-detail rows)
#
# Iterating this list once (first match wins) means a new decoded shape
# is added by registering ONE tuple here. Previously the same shape
# needed a branch in `gnc_compact_value` and a branch in
# `_gnc_register_detail_fields` — parallel duplication flagged as
# smell #2 in the architectural audit.
#
# _format_gnc_register_lines (text log summary layout) stays standalone
# — its output shape (summary line + indented subfields with register
# name as left gutter) is legitimately different from both compact
# strings and name/value dicts, and unifying would force the dispatch
# into lowest-common-denominator output.


def _nvg_sensor_compact(v: dict, unit: str) -> str:
    return f"{v.get('display', '')} (status={v.get('status')})"


def _nvg_sensor_detail(v: dict, unit: str) -> list[dict]:
    suffix = f" {unit}" if unit else ""
    fields = [
        {"name": "Display", "value": str(v.get("display", ""))},
        {"name": "Status",  "value": str(v.get("status"))},
    ]
    ts = v.get("timestamp")
    if ts is not None:
        fields.append({"name": "Timestamp", "value": str(ts)})
    names = v.get("fields") or []
    vals  = v.get("values") or []
    if names and len(vals) == len(names):
        for n, x in zip(names, vals):
            fields.append({"name": n, "value": f"{x}{suffix}"})
    else:
        for i, x in enumerate(vals):
            fields.append({"name": f"v[{i}]", "value": f"{x}{suffix}"})
    return fields


def _bcd_compact(v: dict, unit: str) -> str:
    return v["display"]


def _bcd_detail(v: dict, unit: str) -> list[dict]:
    return [{"name": "Display", "value": v["display"]}]


def _adcs_tmp_compact(v: dict, unit: str) -> str:
    if v.get("comm_fault"):
        return "SENSOR FAULT"
    c = v.get("celsius")
    return f"{c:.2f} °C" if c is not None else "—"


def _adcs_tmp_detail(v: dict, unit: str) -> list[dict]:
    if v.get("comm_fault"):
        return [{"name": "Status", "value": "SENSOR FAULT"}]
    return [
        {"name": "Celsius", "value": f"{v.get('celsius'):.2f} °C"},
        {"name": "Raw",     "value": str(v.get("brdtmp"))},
    ]


def _nvg_hb_compact(v: dict, unit: str) -> str:
    return f"{v.get('label')} (status={v.get('status')})"


def _nvg_hb_detail(v: dict, unit: str) -> list[dict]:
    return [
        {"name": "Label",  "value": str(v.get("label"))},
        {"name": "Status", "value": str(v.get("status"))},
    ]


def _gnc_mode_compact(v: dict, unit: str) -> str:
    return f"{v.get('mode_name')} ({v.get('mode')})"


def _gnc_mode_detail(v: dict, unit: str) -> list[dict]:
    return [
        {"name": "Mode", "value": str(v.get("mode_name"))},
        {"name": "Code", "value": str(v.get("mode"))},
    ]


def _gnc_counters_compact(v: dict, unit: str) -> str:
    return (
        f"reboot={v.get('reboot')}  "
        f"detumble={v.get('detumble')}  "
        f"sunspin={v.get('sunspin')}"
    )


def _gnc_counters_detail(v: dict, unit: str) -> list[dict]:
    return [
        {"name": "Reboot",    "value": str(v.get("reboot"))},
        {"name": "De-Tumble", "value": str(v.get("detumble"))},
        {"name": "Sunspin",   "value": str(v.get("sunspin"))},
    ]


def _bitfield_compact(v: dict, unit: str) -> str:
    parts: list[str] = []
    if "MODE" in v:
        parts.append(f"mode={v.get('MODE_NAME', v.get('MODE'))}")
    truthy = [k for k, x in v.items() if x is True]
    if truthy:
        parts.append(",".join(truthy))
    elif any(isinstance(x, bool) for x in v.values()) and not parts:
        parts.append("nominal")
    return "  ".join(parts) if parts else "—"


def _bitfield_detail(v: dict, unit: str) -> list[dict]:
    fields: list[dict] = []
    has_bool = any(isinstance(x, bool) for x in v.values())
    if "MODE" in v:
        mode_name = v.get("MODE_NAME", str(v.get("MODE")))
        fields.append({"name": "Mode", "value": f"{mode_name} ({v.get('MODE')})"})
    if "TARGET_ELEV" in v:
        fields.append({"name": "Target Elev", "value": f"{v['TARGET_ELEV']}°"})
    truthy = [k for k, x in v.items() if x is True]
    if truthy:
        fields.append({"name": "Flags", "value": ", ".join(truthy)})
    elif has_bool and "MODE" not in v:
        fields.append({"name": "Status", "value": "All nominal"})
    return fields


def _generic_dict_compact(v: dict, unit: str) -> str:
    return "  ".join(
        f"{k}={x}" for k, x in v.items() if not str(k).startswith("_")
    )


def _generic_dict_detail(v: dict, unit: str) -> list[dict]:
    return [{"name": str(k), "value": str(x)} for k, x in v.items()]


# Shape dispatch table. Order matches the existing first-match-wins
# priority — NVG sensor before BCD (which matches any `display` key),
# GNC mode before bitfield (GNC mode is a special dict that would
# otherwise be caught by is_bitfield via its bool values), etc.
_SHAPE_DISPATCH: tuple[tuple, ...] = (
    (is_nvg_sensor,    _nvg_sensor_compact,    _nvg_sensor_detail),
    (is_bcd_display,   _bcd_compact,           _bcd_detail),
    (is_adcs_tmp,      _adcs_tmp_compact,      _adcs_tmp_detail),
    (is_nvg_heartbeat, _nvg_hb_compact,        _nvg_hb_detail),
    (is_gnc_mode,      _gnc_mode_compact,      _gnc_mode_detail),
    (is_gnc_counters,  _gnc_counters_compact,  _gnc_counters_detail),
    (is_bitfield,      _bitfield_compact,      _bitfield_detail),
    (is_generic_dict,  _generic_dict_compact,  _generic_dict_detail),
)


def compact_value(value: Any, unit: str = "") -> str:
    """Collapse one decoded telemetry value into a single display string.

    Used in the beacon path by both rendering.py (packet-detail block
    rows) and log_format.py (text log lines) so a beacon snapshot
    renders as one row per register in both surfaces. Also handles
    spacecraft-domain structured values like time (which has a
    `display` key and flows through the is_bcd_display branch).
    """
    suffix = f" {unit}" if unit else ""

    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{value}{suffix}"
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        body = ", ".join(
            f"{v:.4f}" if isinstance(v, float) else str(v)
            for v in value
        )
        return f"[{body}]{suffix}"
    if isinstance(value, dict):
        for matches, compact_fn, _detail_fn in _SHAPE_DISPATCH:
            if matches(value):
                return compact_fn(value, unit)
    return f"{value}{suffix}"


def detail_fields(value: Any, unit: str = "") -> list[dict]:
    """Render one decoded value as a list of {name, value} rows for the
    packet-detail block layout. Mirror of compact_value but returns
    structured rows instead of a summary string. Dispatches through
    the same _SHAPE_DISPATCH table so a new shape is registered in
    one place.
    """
    suffix = f" {unit}" if unit else ""

    if isinstance(value, dict):
        for matches, _compact_fn, detail_fn in _SHAPE_DISPATCH:
            if matches(value):
                return detail_fn(value, unit)
    if isinstance(value, list):
        joined = ", ".join(
            f"{v:.4f}" if isinstance(v, float) else str(v)
            for v in value
        )
        return [{"name": "Value", "value": f"{joined}{suffix}"}]
    return [{"name": "Value", "value": f"{value}{suffix}"}]


# Back-compat aliases — callers used `gnc_compact_value` before the
# rename to `compact_value` (which reflects that the helper is now
# domain-agnostic: spacecraft time flows through it too). Keep the old
# name wired so downstream grep-then-import doesn't break.
gnc_compact_value = compact_value
