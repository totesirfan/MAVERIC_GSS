"""EPS HK decoder — mirrors HK Decoder.py from the firmware team.

48 signed int16 little-endian values with fixed names. v1 ships raw
values (no calibration); the EPS is in-house and published scale
factors do not exist yet. When calibration arrives, edit the table
here and the v1 invariant test will break loudly, forcing the golden
values to be updated in the same commit.
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
    return [
        TelemetryField(name=name, value=raw, unit="", raw=raw)
        for name, raw in zip(_EPS_HK_NAMES, raws)
    ]
