"""EPS HK decoder — mirrors HK Decoder.py from the firmware team.

48 signed int16 little-endian values with fixed names. Voltages are
transmitted in mV, currents in mA, powers in mW; the decoder emits
engineering values (V, A, W). TS_ADC and T_DIE come from the BQ25672
charger registers with firmware-specified scales (0.0976563 %/LSB and
0.5 °C/LSB respectively).
"""

from __future__ import annotations

import struct

from .types import TelemetryField


_EPS_HK_NAMES = [
    "I_BUS", "I_BAT", "V_BUS", "V_AC1", "V_AC2", "V_BAT", "V_SYS",
    "TS_ADC", "T_DIE", "V3V3", "I3V3", "P3V3",
    "V5V0", "I5V0", "P5V0",
    "VOUT1", "IOUT1", "POUT1",
    "VOUT2", "IOUT2", "POUT2",
    "VOUT3", "IOUT3", "POUT3",
    "VOUT4", "IOUT4", "POUT4",
    "VOUT5", "IOUT5", "POUT5",
    "VOUT6", "IOUT6", "POUT6",
    "VBRN1", "IBRN1", "PBRN1",
    "VBRN2", "IBRN2", "PBRN2",
    "VSIN1", "ISIN1", "PSIN1",
    "VSIN2", "ISIN2", "PSIN2",
    "VSIN3", "ISIN3", "PSIN3",
]
assert len(_EPS_HK_NAMES) == 48, f"_EPS_HK_NAMES length: {len(_EPS_HK_NAMES)}"

_STRUCT = struct.Struct("<48h")
_EXPECTED_BYTES = _STRUCT.size

_PREFIX_SCALE = {"V": (0.001, "V"), "I": (0.001, "A"), "P": (0.001, "W")}
_SPECIAL_SCALE = {"TS_ADC": (0.0976563, "%"), "T_DIE": (0.5, "°C")}


def _scale_and_unit(name: str) -> tuple[float, str]:
    if name in _SPECIAL_SCALE:
        return _SPECIAL_SCALE[name]
    return _PREFIX_SCALE.get(name[0], (1.0, ""))


def decode_eps_hk(cmd: dict) -> list[TelemetryField]:
    """Decode eps_hk args_raw (96 bytes) into 48 TelemetryField entries.

    Raises ValueError if args_raw is missing or shorter than 96 bytes.
    Trailing bytes past 96 are silently ignored (forward-compat with
    longer future HK frames).
    """
    args_raw = cmd.get("args_raw") or b""
    if len(args_raw) < _EXPECTED_BYTES:
        raise ValueError(
            f"eps_hk needs {_EXPECTED_BYTES} bytes, got {len(args_raw)}"
        )
    raws = _STRUCT.unpack_from(bytes(args_raw), 0)
    fields = []
    for name, raw in zip(_EPS_HK_NAMES, raws):
        scale, unit = _scale_and_unit(name)
        fields.append(TelemetryField(
            name=name,
            value=round(raw * scale, 6),
            unit=unit,
            raw=raw,
        ))
    return fields
