"""MAVERIC display helpers — calibrator-plugin dispatch.

The legacy shape predicates (`is_bcd_display`, `is_nvg_sensor`, …)
inspected the value dict to detect what the extractor produced. The
declarative replacement dispatches on the parameter type's calibrator —
the plugin name conveys "what kind of value the walker emitted".

Used by both the detail-block renderer (rendering.py) and the text-log
formatter (log_format.py).

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from typing import Any, Mapping

from mav_gss_lib.platform.spec import (
    EnumeratedParameterType,
    Mission,
    PythonCalibrator,
)


# Operator-facing labels for fragment keys. Canonical keys stay
# unchanged everywhere (fragment.to_dict, JSONL, text log, router);
# this map only affects detail-block field names in the web UI. Missing
# entries fall through to the key verbatim.
_DISPLAY_LABELS: dict[str, str] = {
    # Spacecraft
    "callsign":        "Callsign",
    "time":            "SAT Clock",
    "ops_stage":       "Ops Stage",
    "lppm_rbt_cnt":    "LPPM Reboots",
    "lppm_rbt_cause":  "LPPM Reboot Cause",
    "uppm_rbt_cnt":    "UPPM Reboots",
    "uppm_rbt_cause":  "UPPM Reboot Cause",
    "ertc_heartbeat":  "ERTC Heartbeat",
    "hn_state":        "HoloNav State",
    "ab_state":        "AstroBoard State",
    # GNC
    "mtq_heartbeat":   "MTQ Heartbeat",
    "nvg_heartbeat":   "NVG Heartbeat",
    "ACT_ERR":         "Actuator Errors",
    "STAT":            "MTQ Status",
    "GYRO_RATE_SRC":   "Gyro Source",
    "MAG_SRC":         "Mag Source",
    "RATE":            "Gyro Rate",
    "MAG":             "Magnetic Field",
    "MTQ":             "MTQ Dipole",
    "ADCS_TMP":        "ADCS Temp",
    "GNC_MODE":        "GNC Mode",
    "GNC_COUNTERS":    "GNC Counters",
    # EPS
    "I_BUS":           "Bus Current",
    "I_BAT":           "Battery Current",
    "V_BUS":           "Bus Voltage",
    "V_BAT":           "Battery Voltage",
    "V_SYS":           "System Voltage",
    "TS_ADC":          "TS ADC (BQ)",
    "T_DIE":           "Die Temp",
    "eps_heartbeat":   "EPS Heartbeat",
    "eps_mode":        "EPS Mode",
}


def display_label(key: str) -> str:
    """Map a canonical fragment key to its operator-facing label.

    Falls back to the key itself if no label exists. Use only on the
    render path (detail blocks); logs and JSONL keep canonical keys.
    """
    return _DISPLAY_LABELS.get(key, key)


# ---------- calibrator-plugin dispatch ----------

def display_kind(mission: Mission, key: str) -> str | None:
    """Pick a render dispatch tag for a fragment key.

    Returns:
      - the calibrator plugin name (e.g. 'maveric.bcd_time'), if the
        parameter type uses a Python plugin
      - '_enum' if the parameter type is an EnumeratedParameterType
      - '_absolute_time' if the parameter type is absolute_time
      - None for plain scalars (caller falls back to _compact_value)

    Returns None for keys not in mission.parameters (handler-emitted
    canonical keys like GNC_MODE / GNC_COUNTERS / ertc_heartbeat — these
    have no Parameter declaration in mission.yml and render via the
    scalar fallback)."""
    p = mission.parameters.get(key)
    if p is None:
        return None
    t = mission.parameter_types.get(p.type_ref)
    if t is None:
        return None
    cal = getattr(t, "calibrator", None)
    if isinstance(cal, PythonCalibrator):
        return cal.callable_ref
    if isinstance(t, EnumeratedParameterType):
        return "_enum"
    kind = getattr(t, "kind", None)
    if kind == "absolute_time":
        return "_absolute_time"
    return None


def render_value(value: Any, dispatch: str | None, unit: str = "") -> str:
    """Format a fragment value for compact display."""
    if dispatch is None:
        return _compact_value(value, unit)
    if dispatch == "maveric.bcd_time":         return _format_bcd_time(value)
    if dispatch == "maveric.bcd_date":         return _format_bcd_date(value)
    if dispatch == "maveric.adcs_tmp":         return _format_adcs_tmp(value)
    if dispatch == "maveric.fss_tmp":          return _format_fss_tmp(value)
    if dispatch == "maveric.gnc_planner_mode": return _format_gnc_mode(value)
    if dispatch == "_enum":                    return _format_enum(value)
    if dispatch == "_absolute_time":           return _format_absolute_time(value)
    return _compact_value(value, unit)


def render_detail_fields(value: Any, dispatch: str | None, unit: str = "") -> list[dict]:
    """Render a single fragment value as a list of {name, value} rows for
    the packet-detail block layout. Mirror of `render_value` but
    structured. Falls through to a single-row representation when no
    plugin dispatch matches."""
    if dispatch == "maveric.bcd_time" and isinstance(value, dict):
        return _bcd_time_detail(value)
    if dispatch == "maveric.bcd_date" and isinstance(value, dict):
        return _bcd_date_detail(value)
    if dispatch == "maveric.adcs_tmp" and isinstance(value, dict):
        return _adcs_tmp_detail(value)
    if dispatch == "maveric.fss_tmp" and isinstance(value, dict):
        return _fss_tmp_detail(value)
    if dispatch == "maveric.gnc_planner_mode" and isinstance(value, dict):
        return _gnc_mode_detail(value)
    suffix = f" {unit}" if unit else ""
    if isinstance(value, dict):
        return [{"name": str(k), "value": str(x)} for k, x in value.items()]
    if isinstance(value, list):
        joined = ", ".join(
            f"{v:.4f}" if isinstance(v, float) else str(v) for v in value
        )
        return [{"name": "Value", "value": f"{joined}{suffix}"}]
    return [{"name": "Value", "value": f"{value}{suffix}"}]


# Plugin-name parity guard: every plugin path render_value dispatches on
# must exist in plugins.PLUGINS — otherwise mission.yml or the dispatch
# table is out of sync and we'd silently fall through to scalar formatting.
def _assert_dispatch_plugins_registered(plugins: Mapping[str, Any]) -> None:
    expected = {
        "maveric.bcd_time", "maveric.bcd_date",
        "maveric.adcs_tmp", "maveric.fss_tmp",
        "maveric.gnc_planner_mode",
    }
    missing = expected - set(plugins.keys())
    if missing:
        raise RuntimeError(
            f"render_value dispatches on plugins not in PLUGINS registry: {sorted(missing)}"
        )


# ---------- per-plugin formatters ----------

def _format_bcd_time(value: Any) -> str:
    if isinstance(value, dict):
        display = value.get("display", "")
        unix_ms = value.get("unix_ms")
        if unix_ms is not None and display:
            return f"{display}  ({unix_ms})"
        return display or _compact_value(value)
    return _compact_value(value)


def _format_bcd_date(value: Any) -> str:
    if isinstance(value, dict):
        return value.get("display") or _compact_value(value)
    return _compact_value(value)


def _format_adcs_tmp(value: Any) -> str:
    if not isinstance(value, dict):
        return _compact_value(value)
    if value.get("comm_fault"):
        return "SENSOR FAULT"
    c = value.get("celsius")
    if c is None:
        return "—"
    return f"{c:.2f} °C"


def _format_fss_tmp(value: Any) -> str:
    if not isinstance(value, dict):
        return _compact_value(value)
    parts = []
    for label, key in (("FSS0", "fss0_celsius"), ("FSS1", "fss1_celsius")):
        v = value.get(key)
        if isinstance(v, (int, float)):
            parts.append(f"{label}:{v:.2f}°C")
    return "  ".join(parts) if parts else _compact_value(value)


def _format_gnc_mode(value: Any) -> str:
    if not isinstance(value, dict):
        return _compact_value(value)
    return f"{value.get('mode_name', '?')} ({value.get('mode')})"


def _format_enum(value: Any) -> str:
    """Walker emits enums as the resolved string label (or the raw int
    if the value isn't in the enum table). Render verbatim."""
    if value is None:
        return "—"
    return str(value)


def _format_absolute_time(value: Any) -> str:
    """absolute_time values arrive as int unix_ms scalars from the walker."""
    if isinstance(value, (int, float)):
        return f"{int(value)} ms"
    return _compact_value(value)


# ---------- detail-block formatters ----------

def _bcd_time_detail(v: dict) -> list[dict]:
    fields = [{"name": "Display", "value": str(v.get("display", ""))}]
    unix_ms = v.get("unix_ms")
    if unix_ms is not None:
        fields.append({"name": "Unix ms", "value": str(unix_ms)})
    for k in ("hour", "minute", "second"):
        if k in v:
            fields.append({"name": k.capitalize(), "value": str(v[k])})
    return fields


def _bcd_date_detail(v: dict) -> list[dict]:
    fields = [{"name": "Display", "value": str(v.get("display", ""))}]
    for k in ("year", "month", "day", "weekday"):
        if k in v:
            fields.append({"name": k.capitalize(), "value": str(v[k])})
    return fields


def _adcs_tmp_detail(v: dict) -> list[dict]:
    if v.get("comm_fault"):
        return [{"name": "Status", "value": "SENSOR FAULT"}]
    return [
        {"name": "Celsius", "value": f"{v.get('celsius'):.2f} °C"},
        {"name": "Raw", "value": str(v.get("brdtmp"))},
    ]


def _fss_tmp_detail(v: dict) -> list[dict]:
    fields: list[dict] = []
    for label, raw_key, c_key in (
        ("FSS0", "fss0_raw", "fss0_celsius"),
        ("FSS1", "fss1_raw", "fss1_celsius"),
    ):
        c = v.get(c_key)
        if isinstance(c, (int, float)):
            fields.append({"name": label, "value": f"{c:.2f} °C"})
            fields.append({"name": f"{label} raw", "value": str(v.get(raw_key))})
    return fields


def _gnc_mode_detail(v: dict) -> list[dict]:
    return [
        {"name": "Mode", "value": str(v.get("mode_name"))},
        {"name": "Code", "value": str(v.get("mode"))},
    ]


# ---------- scalar fallback ----------

def _compact_value(value: Any, unit: str = "") -> str:
    """Collapse any value into a single display string. Used for fragments
    that have no calibrator dispatch (handler-emitted canonical keys,
    plain ints/floats/strings, lists)."""
    suffix = f" {unit}" if unit else ""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return f"{value}{suffix}"
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, list):
        body = ", ".join(
            f"{v:.6g}" if isinstance(v, float) else str(v)
            for v in value
        )
        return f"[{body}]{suffix}"
    if isinstance(value, dict):
        # Generic dict fallback — flatten as space-separated k=v.
        return "  ".join(
            f"{k}={x}" for k, x in value.items() if not str(k).startswith("_")
        )
    return f"{value}{suffix}"


# Public re-export for callers that want the raw scalar formatter.
compact_value = _compact_value
