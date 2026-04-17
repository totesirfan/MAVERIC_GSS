"""NaviGuider virtual-sensor decoder for `nvg_get_1` responses.

Wire format (per `commands.yml::nvg_get_1`):
    <Status> <Sensor ID> <Timestamp> <Values…>

where Status = 1 on success (0 = no data for the requested sensor),
Sensor ID is one of the virtual-sensor IDs defined in the NaviGuider
UART Users Manual V1.7 Table 4-2 (pp. 12), Timestamp is the on-board
sample-time counter (1/32000 s units), and trailing values are the
per-sensor payload listed in the manual (pp. 14-18).

This module stores decoded snapshots under register names prefixed
`NVG_` so they share the same name-keyed cache as the MTQ registers
but cannot collide with them. The store overwrites the last snapshot
per sensor on every successful RES.

We decode *every* sensor ID the manual defines so the full table can
render any sensor the MAVERIC flight software emits — the dashboard
card itself picks the subset it wants (Orientation, Gyro, Temp, Mag).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ── Sensor catalog ──────────────────────────────────────────────────

@dataclass(frozen=True)
class NvgSensorDef:
    """One NaviGuider virtual-sensor definition.

    `fields` lists the expected payload labels in order, per manual
    pp. 14-18. Actual arriving payload may be shorter (the MAVERIC
    cache truncates) or longer (user changes firmware); the decoder
    is lenient — it coerces whatever tokens are present and stores
    them alongside the expected-field metadata.
    """
    sensor_id: int
    name: str                # Stored as NVG_<name>
    display: str             # Human label for the dashboard/table
    fields: tuple[str, ...]  # Expected payload field names, per manual
    unit: str                # Engineering unit


# Per NVG Manual V1.7 Table 4-2 + detail sections pp. 14-18.
SENSORS: dict[int, NvgSensorDef] = {
    1:  NvgSensorDef(1,  "ACCELEROMETER",      "Accelerometer",        ("X", "Y", "Z", "Accuracy"),                            "m/s^2"),
    2:  NvgSensorDef(2,  "MAGNETOMETER",       "Magnetometer",         ("X", "Y", "Z", "Accuracy"),                            "uT"),
    3:  NvgSensorDef(3,  "ORIENTATION",        "Orientation",          ("Yaw", "Pitch", "Roll", "Accuracy"),                   "deg"),
    4:  NvgSensorDef(4,  "GYROSCOPE",          "Gyroscope",            ("X", "Y", "Z", "Accuracy"),                            "rad/s"),
    6:  NvgSensorDef(6,  "PRESSURE",           "Pressure",             ("Value",),                                             "Pa"),
    7:  NvgSensorDef(7,  "TEMPERATURE",        "Temperature",          ("Value",),                                             "degC"),
    9:  NvgSensorDef(9,  "GRAVITY",            "Gravity",              ("X", "Y", "Z", "Accuracy"),                            "m/s^2"),
    10: NvgSensorDef(10, "LINEAR_ACCEL",       "Linear Acceleration",  ("X", "Y", "Z", "Accuracy"),                            "m/s^2"),
    11: NvgSensorDef(11, "ROTATION_VECTOR",    "Rotation Vector 9DOF", ("Qx", "Qy", "Qz", "Qw", "Accuracy"),                   ""),
    14: NvgSensorDef(14, "MAG_UNCAL",          "Magnetometer Uncal",   ("X", "Y", "Z", "Xoff", "Yoff", "Zoff", "Accuracy"),    "uT"),
    15: NvgSensorDef(15, "GAME_ROTATION",      "Game Rotation 6DOF",   ("Qx", "Qy", "Qz", "Qw", "Accuracy"),                   ""),
    16: NvgSensorDef(16, "GYRO_UNCAL",         "Gyroscope Uncal",      ("X", "Y", "Z", "Xbias", "Ybias", "Zbias", "Accuracy"), "rad/s"),
    17: NvgSensorDef(17, "SIGNIFICANT_MOTION", "Significant Motion",   ("Value",),                                             ""),
    20: NvgSensorDef(20, "GEOMAG_ROTATION",    "Geo-mag Rotation 6DOF",("Qx", "Qy", "Qz", "Qw", "Accuracy"),                   ""),
    254: NvgSensorDef(254, "META_EVENT",       "Meta Event",           ("EventType", "Value2", "Value3"),                      ""),
}


# ── Decoder ─────────────────────────────────────────────────────────

def _coerce_float(t: str) -> float | str:
    """Best-effort float coercion. Returns the raw token if it won't
    parse so the operator can still see what the spacecraft sent."""
    try:
        return float(t)
    except (ValueError, TypeError):
        return t


def _decode_nvg_entry(status: int, sensor_id: int, tokens: list[str]) -> dict[str, Any]:
    """Decode one sensor's tokens into a structured entry.

    `tokens` is whatever trailing args remained after Status + Sensor.
    By the schema the first trailing token is `Timestamp`, the rest
    are the sensor's payload values (variadic).
    """
    entry = SENSORS.get(sensor_id)
    expected_fields = entry.fields if entry else ()

    timestamp: float | str | None = None
    values_raw: list[str] = []
    if tokens:
        timestamp = _coerce_float(tokens[0])
        values_raw = list(tokens[1:])
    values = [_coerce_float(t) for t in values_raw]

    # Align into a dict if we have enough trailing values for the
    # manual-declared payload; fall back to a list otherwise.
    values_by_field: dict[str, Any] | None = None
    if expected_fields and len(values) >= len(expected_fields):
        values_by_field = {name: values[i] for i, name in enumerate(expected_fields)}

    return {
        "sensor_id": sensor_id,
        "sensor_name": entry.name if entry else f"UNKNOWN_{sensor_id}",
        "display": entry.display if entry else f"Unknown sensor {sensor_id}",
        "unit": entry.unit if entry else "",
        "status": status,
        "timestamp": timestamp,
        "fields": list(expected_fields),
        "values": values,
        "values_by_field": values_by_field,
        "raw_tokens": values_raw,
    }


def _handle_nvg_get_1(cmd: dict) -> dict[str, dict] | None:
    """Decode an `nvg_get_1` RES into `{register_name: decoded_dict}`.

    Registered in `gnc_registers.COMMAND_HANDLERS` so the existing
    adapter hook automatically persists + broadcasts the snapshot.
    The `Status` field on nvg_get_1 is a per-sensor "data valid"
    indicator, not the module-level on/off — that lives on
    `nvg_heartbeat` instead and updates the `NVG_STATUS` slot.
    """
    typed = cmd.get("typed_args") or []
    extras = cmd.get("extra_args") or []

    if len(typed) < 2:
        return None
    try:
        status = int(typed[0]["value"])
        sensor_id = int(typed[1]["value"])
    except (ValueError, TypeError, KeyError):
        return None

    # typed_args[2] is Timestamp slot; typed_args[3] is Sensor Values
    # slot (the first data token); remaining payload is in extras.
    trailing: list[str] = []
    if len(typed) > 2:
        trailing.append(str(typed[2]["value"]))
    if len(typed) > 3:
        trailing.append(str(typed[3]["value"]))
    trailing.extend(str(t) for t in extras)

    entry = _decode_nvg_entry(status, sensor_id, trailing)
    register_name = f"NVG_{entry['sensor_name']}"
    return {
        register_name: {
            "name": register_name,
            "module": None,
            "register": sensor_id,
            "type": f"nvg_sensor_{sensor_id}",
            "unit": entry["unit"],
            "value": entry,
            "raw_tokens": entry["raw_tokens"],
            "decode_ok": True,
            "decode_error": None,
        }
    }


def _handle_nvg_heartbeat(cmd: dict) -> dict[str, dict] | None:
    """Decode an `nvg_heartbeat` RES into the `NVG_STATUS` register.

    Wire format: single Status arg, 1 = module on, 0 = module off
    (per MAVERIC flight software).
    """
    typed = cmd.get("typed_args") or []
    if len(typed) < 1:
        return None
    try:
        status = int(typed[0]["value"])
    except (ValueError, TypeError, KeyError):
        return None
    return {
        "NVG_STATUS": {
            "name": "NVG_STATUS",
            "module": None,
            "register": None,
            "type": "nvg_status",
            "unit": "",
            "value": {
                "status": status,
                "label": "On" if status == 1 else "Off",
            },
            "raw_tokens": [str(status)],
            "decode_ok": True,
            "decode_error": None,
        }
    }


__all__ = ["SENSORS", "NvgSensorDef", "_handle_nvg_get_1", "_handle_nvg_heartbeat"]
