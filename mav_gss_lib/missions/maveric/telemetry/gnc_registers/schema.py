"""MAVERIC TensorADCS register catalog and typed decoding.

Defines the register catalog (`REGISTERS`), per-register bit-field
decoders, `RegisterDef` / `DecodedRegister` dataclasses, and the
`decode_register(module, register, tokens)` entry point that turns
raw ASCII tokens into typed values.

Bit layouts and unit conversions per TensorADCS V2.0.12a User Manual
§6.2 (pp. 24-37).

Scope: v1 covers only the 9 registers the GNC dashboard consumes.
Other registers decode to a generic typed value (array of ints/floats)
so they still surface in raw views.

Command-level dispatch (mtq_get_1, mtq_get_fast, gnc_get_*) lives in
the sibling `handlers` module.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Callable


# ── Type parsing ────────────────────────────────────────────────────

def parse_type(type_str: str) -> tuple[str, int]:
    """Split a type string into (base, count).

    "float[3]"   -> ("float", 3)
    "uint8[4]"   -> ("uint8", 4)
    "float"      -> ("float", 1)
    "char[140]"  -> ("char", 140)
    """
    s = type_str.replace(" ", "")
    if "[" in s:
        base, rest = s.split("[", 1)
        count = int(rest.rstrip("]"))
        return base, count
    return s, 1


_INT_COERCERS: dict[str, Callable[[str], int]] = {
    "uint8":  lambda t: int(t) & 0xFF,
    "int8":   lambda t: int(t) if int(t) < 128 else int(t) - 256,
    "uint16": lambda t: int(t) & 0xFFFF,
    "int16":  lambda t: int(t) if int(t) < 32768 else int(t) - 65536,
    "uint32": lambda t: int(t) & 0xFFFFFFFF,
    "int32":  int,
}


def _coerce(base: str, token: str) -> int | float | str:
    if base == "float":
        return float(token)
    if base == "char":
        return token
    fn = _INT_COERCERS.get(base)
    if fn is None:
        return token
    return fn(token)


# ── Bit-field expansion helpers ─────────────────────────────────────

def _bit(byte_val: int, bit_index_within_byte: int) -> bool:
    return bool((byte_val >> bit_index_within_byte) & 1)


def _nibble_hi(byte_val: int) -> int:
    return (byte_val >> 4) & 0xF


def _nibble_lo(byte_val: int) -> int:
    return byte_val & 0xF


# Referenced by _decode_stat and _decode_conf below.
MODE_NAMES: dict[int, str] = {
    0: "Safe",
    1: "De-tumbling",
    2: "Sun Spin",
    3: "Sun-Pointing",
    4: "Fine Pointing",
    5: "LVLH",
    6: "Target Tracking",
    7: "Manual",
}


def _decode_stat(bytes_le: list[int]) -> dict[str, Any]:
    """STAT (0, 128) uint8[4] little-endian. Manual §6.2 pp. 31-32.

    byte[3] (bits 31..24): HERR, SERR, WDT, UV, OC, OT, GNSS_OC, GNSS_UP_TO_DATE
    byte[2] (bits 23..16): unused
    byte[1] (bits 15.. 8): TLE, DES, SUN, TGL, TUMB, AME, CUSSV, EKF
    byte[0] (bits  7.. 0): unused(7), MODE bits 6..0
    """
    b0, b1, b2, b3 = bytes_le
    mode = b0 & 0x7F
    return {
        # Byte 3 — error/protection flags
        "HERR":      _bit(b3, 7),
        "SERR":      _bit(b3, 6),
        "WDT":       _bit(b3, 5),
        "UV":        _bit(b3, 4),
        "OC":        _bit(b3, 3),
        "OT":        _bit(b3, 2),
        "GNSS_OC":   _bit(b3, 1),
        "GNSS_UP_TO_DATE": _bit(b3, 0),
        # Byte 1 — status flags
        "TLE":       _bit(b1, 7),
        "DES":       _bit(b1, 6),
        "SUN":       _bit(b1, 5),
        "TGL":       _bit(b1, 4),
        "TUMB":      _bit(b1, 3),
        "AME":       _bit(b1, 2),
        "CUSSV":     _bit(b1, 1),
        "EKF":       _bit(b1, 0),
        # Byte 0 — mode (bits 6..0)
        "MODE":      mode,
        "MODE_NAME": MODE_NAMES.get(mode, f"UNKNOWN_{mode}"),
        # Preserve reserved byte so unexpected nonzero values are visible.
        "byte2_raw": b2,
    }


def _decode_act_err(bytes_le: list[int]) -> dict[str, Any]:
    """ACT_ERR (0, 129) uint8[4] little-endian. Manual §6.2 p. 32.

    byte[1] bits 10..8: MTQ2, MTQ1, MTQ0
    byte[0] bits  3..0: CMG3, CMG2, CMG1, CMG0
    """
    b0, b1, b2, b3 = bytes_le
    return {
        "MTQ0": _bit(b1, 0),  # absolute bit 8
        "MTQ1": _bit(b1, 1),  # absolute bit 9
        "MTQ2": _bit(b1, 2),  # absolute bit 10
        "CMG0": _bit(b0, 0),
        "CMG1": _bit(b0, 1),
        "CMG2": _bit(b0, 2),
        "CMG3": _bit(b0, 3),
        "byte2_raw": b2,
        "byte3_raw": b3,
    }


def _decode_sen_err(bytes_le: list[int]) -> dict[str, Any]:
    """SEN_ERR (0, 130) uint8[4] little-endian. Manual §6.2 pp. 32-33.

    byte[3] bits 25..24: STR1, STR0
    byte[2] bits 19..16: IMU3, IMU2, IMU1, IMU0
    byte[1] bits 13.. 8: MAG5..MAG0
    byte[0] bits  5.. 0: FSS5..FSS0
    """
    b0, b1, b2, b3 = bytes_le
    return {
        "FSS0": _bit(b0, 0), "FSS1": _bit(b0, 1), "FSS2": _bit(b0, 2),
        "FSS3": _bit(b0, 3), "FSS4": _bit(b0, 4), "FSS5": _bit(b0, 5),
        "MAG0": _bit(b1, 0), "MAG1": _bit(b1, 1), "MAG2": _bit(b1, 2),
        "MAG3": _bit(b1, 3), "MAG4": _bit(b1, 4), "MAG5": _bit(b1, 5),
        "IMU0": _bit(b2, 0), "IMU1": _bit(b2, 1),
        "IMU2": _bit(b2, 2), "IMU3": _bit(b2, 3),
        "STR0": _bit(b3, 0), "STR1": _bit(b3, 1),
    }


def _decode_time(bytes_le: list[int]) -> dict[str, Any]:
    """TIME (0, 5) uint8[4] BCD little-endian.

    byte[3]: HR10 | HR01
    byte[2]: MIN10 | MIN01
    byte[1]: SEC10 | SEC01
    byte[0]: unused
    """
    b0, b1, b2, b3 = bytes_le
    hr  = _nibble_hi(b3) * 10 + _nibble_lo(b3)
    mn  = _nibble_hi(b2) * 10 + _nibble_lo(b2)
    sec = _nibble_hi(b1) * 10 + _nibble_lo(b1)
    return {
        "hour": hr,
        "minute": mn,
        "second": sec,
        "display": f"{hr:02d}:{mn:02d}:{sec:02d}",
    }


def _decode_date(bytes_le: list[int]) -> dict[str, Any]:
    """DATE (0, 6) uint8[4] BCD little-endian.

    byte[3]: YEAR10 | YEAR01
    byte[2]: MONTH10 | MONTH01
    byte[1]: DAY10 | DAY01
    byte[0]: unused(7..4) | WDAY01(3..0)
    """
    b0, b1, b2, b3 = bytes_le
    yr    = _nibble_hi(b3) * 10 + _nibble_lo(b3)
    month = _nibble_hi(b2) * 10 + _nibble_lo(b2)
    day   = _nibble_hi(b1) * 10 + _nibble_lo(b1)
    wday  = _nibble_lo(b0)
    return {
        "year_yy": yr,
        "year": 2000 + yr,
        "month": month,
        "day": day,
        "weekday": wday,
        "display": f"{2000 + yr:04d}-{month:02d}-{day:02d}",
    }


def _decode_conf(bytes_le: list[int]) -> dict[str, Any]:
    """CONF (0, 4) uint8[4] little-endian. Manual §6.2 p. 25-26.

    byte[3] (bits 31..24): TARGET_ELEV (uint8, 10..90 deg)
    byte[2], byte[1]: unused
    byte[0] (bits  7..0): unused(7) | CMD(6) | MODE (bits 6..0)

    CONF carries the *requested* mode; current running mode is in STAT.
    """
    b0, _b1, _b2, b3 = bytes_le
    mode = b0 & 0x7F
    return {
        "TARGET_ELEV": b3,
        "CMD":         _bit(b0, 7),
        "MODE":        mode,
        "MODE_NAME":   MODE_NAMES.get(mode, f"UNKNOWN_{mode}"),
    }


def _decode_adcs_tmp(int16s_le: list[int]) -> dict[str, Any]:
    """ADCS_TMP (0, 148) int16[2] little-endian. Manual §6.2 p. 36, Eq. 6-1.

    Lower 16 bits = BRDTMP (signed int16). Upper 16 bits unused.
    Temperature [°C] = BRDTMP × 150 / 32768.
    BRDTMP == 0xFFFF (-1 as int16) indicates sensor comm failure.
    """
    brdtmp = int16s_le[0]
    comm_fault = (brdtmp == -1)
    celsius = None if comm_fault else brdtmp * 150.0 / 32768.0
    return {
        "brdtmp": brdtmp,
        "celsius": celsius,
        "comm_fault": comm_fault,
    }


def _decode_fss_tmp(int16s_le: list[int]) -> dict[str, Any]:
    """FSS_TMP1 (0, 153) int16[2] little-endian. Manual §6.2 p. 36, Eq. 6-3.

    Lower 16 bits = FSS0TMP (signed int16). Upper 16 bits = FSS1TMP.
    Temperature [°C] = FSSxTMP × 0.03125.
    """
    fss0 = int16s_le[0]
    fss1 = int16s_le[1] if len(int16s_le) > 1 else 0
    return {
        "fss0_raw":     fss0,
        "fss1_raw":     fss1,
        "fss0_celsius": fss0 * 0.03125,
        "fss1_celsius": fss1 * 0.03125,
    }


# ── Register catalog ────────────────────────────────────────────────

@dataclass(frozen=True)
class RegisterDef:
    name: str
    type: str
    unit: str = ""
    notes: str = ""
    # Optional post-processor that turns the coerced token list into a
    # richer structure (bit flags, BCD date, scaled temperature, etc.).
    # Receives the list of coerced values; returns a dict or None to
    # keep the plain list as the value.
    decode_extra: Callable[[list], dict[str, Any]] | None = None


# Register catalog — mirrors the GNC team's authoritative Registers.csv.
# Registers with custom `decode_extra`
# callbacks unpack their bitfields / BCD / scaled units; all others
# fall through to the generic float/int coercion pipeline and display
# as arrays of typed values in the raw table.
#
# Adding hardware assumptions is disallowed — only extend decoders when
# the TensorADCS manual provides explicit bit layouts. Unknown bitfield
# registers (MAG_STAT, FSS_STAT, IMU_STAT, MAG_INFO, FSS_INFO,
# IMU_INFO, NVM) decode as raw uint8[4] arrays.
REGISTERS: dict[tuple[int, int], RegisterDef] = {
    # ── Module 0 / User ────────────────────────────────────────────
    (0, 4):   RegisterDef("CONF",           "uint8[4]", unit="",         notes="Requested mode + target elevation", decode_extra=_decode_conf),
    (0, 5):   RegisterDef("TIME",           "uint8[4]", unit="",         notes="BCD HH/MM/SS", decode_extra=_decode_time),
    (0, 6):   RegisterDef("DATE",           "uint8[4]", unit="",         notes="BCD YY/MM/DD/WD", decode_extra=_decode_date),
    (0, 14):  RegisterDef("POINTING_AXIS",  "float[3]", unit="",         notes="Target/sun tracking pointing axis"),
    (0, 17):  RegisterDef("TLE",            "char[140]", unit="",        notes="NORAD TLE, two-line set"),
    (0, 100): RegisterDef("SV_USER",        "float[3]", unit="",         notes="Custom sun vector (unit)"),
    (0, 103): RegisterDef("MTQ_USER",       "float[3]", unit="A.m^2",    notes="Custom MTQ dipole"),
    (0, 128): RegisterDef("STAT",           "uint8[4]", unit="",         notes="Status + current mode", decode_extra=_decode_stat),
    (0, 129): RegisterDef("ACT_ERR",        "uint8[4]", unit="",         notes="Actuator errors", decode_extra=_decode_act_err),
    (0, 130): RegisterDef("SEN_ERR",        "uint8[4]", unit="",         notes="Sensor errors", decode_extra=_decode_sen_err),
    (0, 132): RegisterDef("Q",              "float[4]", unit="",         notes="Attitude quaternion Q0..Q3"),
    (0, 136): RegisterDef("RATE",           "float[3]", unit="rad/s",    notes="Attitude rate, body frame"),
    (0, 139): RegisterDef("LLA",            "float[3]", unit="",         notes="Lat (deg), Long (deg), Alt (km)"),
    (0, 142): RegisterDef("ATT_ERROR",      "float[3]", unit="MRP",      notes="Attitude error (Modified Rodrigues)"),
    (0, 145): RegisterDef("ATT_ERROR_RATE", "float[3]", unit="rad/s",    notes="Attitude error rate, body frame"),
    (0, 148): RegisterDef("ADCS_TMP",       "int16[2]", unit="deg_C",    notes="BRDTMP*150/32768", decode_extra=_decode_adcs_tmp),
    (0, 149): RegisterDef("PWR_VOL_5V",     "float",    unit="mV",       notes="5V bus voltage"),
    (0, 150): RegisterDef("PWR_CUR_5V",     "float",    unit="mA",       notes="5V bus current"),
    (0, 151): RegisterDef("PWR_VOL_3V",     "float",    unit="mV",       notes="3.3V bus voltage"),
    # CSV line 21 labels reg 152 "PWR_CUR_5V" — likely a typo for
    # PWR_CUR_3V (mirrors voltage pair). Using the corrected name.
    (0, 152): RegisterDef("PWR_CUR_3V",     "float",    unit="mA",       notes="3.3V bus current (CSV typo: listed as PWR_CUR_5V)"),
    (0, 153): RegisterDef("FSS_TMP1",       "int16[2]", unit="deg_C",    notes="FSS0/FSS1 temperature; Celsius = FSSxTMP * 0.03125", decode_extra=_decode_fss_tmp),
    (0, 156): RegisterDef("SV",             "float[3]", unit="",         notes="Sun vector in body frame (unit)"),
    # Manual §6.2 p. 36 states unit is µT, but CSV bounds (50k..75k) and
    # observed wire values (~-31300) only make physical sense as nT — LEO
    # Earth field is ~30-65 µT, so wire returns nanotesla despite manual
    # documentation. Trusting wire; flag discrepancy in notes.
    (0, 159): RegisterDef("MAG",            "float[3]", unit="nT",       notes="Magnetic field, body frame (wire=nT; manual says µT — wire truth)"),

    # ── Module 1 / Sensor-Actuator ─────────────────────────────────
    (1, 0):   RegisterDef("MAG_MAT",        "float[9]", unit="",         notes="Magnetic sensor calibration matrix"),
    (1, 9):   RegisterDef("MAG_VEC",        "float[3]", unit="T",        notes="Magnetic sensor offset vector"),
    (1, 12):  RegisterDef("MAG_STAT",       "uint8[4]", unit="",         notes="Magnetometer status bitfield (bit layout TBD)"),
    (1, 13):  RegisterDef("MAG0_S",         "float[3]", unit="",         notes="Magnetometer 0 sensor axis indicator"),
    (1, 31):  RegisterDef("FSS_STAT",       "int8[4]",  unit="",         notes="FSS status bitfield (bit layout TBD)"),
    (1, 32):  RegisterDef("FSS0_SV",        "uint16[2]", unit="",        notes="FSS0 sun vector raw"),
    (1, 33):  RegisterDef("FSS0_PDSUM",     "uint16[2]", unit="",        notes="FSS0 photodiode sum"),
    (1, 44):  RegisterDef("IMU_STAT",       "uint8[4]", unit="",         notes="IMU status bitfield (bit layout TBD)"),
    (1, 45):  RegisterDef("IMU0_S",         "float[3]", unit="",         notes="IMU0 sensor axis indicator"),
    (1, 48):  RegisterDef("IMU1_S",         "float[3]", unit="",         notes="IMU1 sensor axis indicator"),
    # MTQ commanded dipole — confirmed at (1, 78) per mtq_get_fast wire
    # capture, official Registers.csv, and GNC team. An earlier draft
    # CSV listed (1, 82); that entry was wrong and is not aliased.
    (1, 78):  RegisterDef("MTQ",            "float[3]", unit="A.m^2",    notes="Commanded MTQ dipole"),
    # MEAS/CAL_MAG_B and MEAS/CAL_IMU_B are not explicitly documented
    # with units in the manual section we have; leaving unit blank rather
    # than guessing. Operator can see raw values; GNC can add units later.
    (1, 130): RegisterDef("MEAS_MAG_B",     "float[3]", unit="",         notes="Measured magnetic field in body frame (unit TBD)"),
    (1, 133): RegisterDef("CAL_MAG_B",      "float[3]", unit="",         notes="Calibrated magnetic field in body frame (unit TBD)"),
    # CSV row labels reg 136 "MAS_IMU_B" — appears to be a typo for
    # MEAS_IMU_B, matching the MEAS_MAG_B pattern.
    (1, 136): RegisterDef("MEAS_IMU_B",     "float[3]", unit="",         notes="Measured IMU rate in body frame (CSV typo: listed as MAS_IMU_B; unit TBD)"),
    (1, 139): RegisterDef("CAL_IMU_B",      "float[3]", unit="",         notes="Calibrated IMU rate in body frame (unit TBD)"),

    # ── Module 2 / Parameter ───────────────────────────────────────
    (2, 0):   RegisterDef("MASS",           "float",    unit="kg",       notes="Satellite mass, 10..25 kg"),
    (2, 1):   RegisterDef("INE_TEN",        "float[9]", unit="",         notes="Inertia tensor"),
    (2, 17):  RegisterDef("MAG_INFO",       "uint8[4]", unit="",         notes="Magnetometer config bitfield (bit layout TBD)"),
    (2, 18):  RegisterDef("MAG0_ORIEN_BS",  "float[4]", unit="",         notes="Magnetometer 0 orientation quaternion"),
    (2, 22):  RegisterDef("MAG1_ORIEN_BS",  "float[4]", unit="",         notes="Magnetometer 1 orientation quaternion"),
    (2, 42):  RegisterDef("FSS_INFO",       "uint8[4]", unit="",         notes="FSS config bitfield (bit layout TBD)"),
    (2, 43):  RegisterDef("FSS0_ORIEN_BS",  "float[4]", unit="",         notes="FSS0 orientation quaternion"),
    (2, 67):  RegisterDef("IMU_INFO",       "uint8[4]", unit="",         notes="IMU config bitfield (bit layout TBD)"),
    (2, 68):  RegisterDef("IMU0_ORIEN_BS",  "float[4]", unit="",         notes="IMU0 orientation quaternion"),
    (2, 72):  RegisterDef("IMU1_ORIEN_BS",  "float[4]", unit="",         notes="IMU1 orientation quaternion"),
    (2, 255): RegisterDef("NVM",            "uint8[4]", unit="",         notes="Non-volatile memory status"),
}


# ── Decoder entry points ────────────────────────────────────────────

@dataclass
class DecodedRegister:
    name: str
    module: int
    register: int
    type: str
    unit: str
    value: Any
    raw_tokens: list[str]
    decode_ok: bool
    decode_error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def decode_register(module: int, register: int, tokens: list[str]) -> DecodedRegister:
    """Decode N raw-string tokens into a typed value per the register catalog.

    Unknown (module, register) pairs return a passthrough with the raw
    tokens preserved so the operator can still inspect them.
    """
    entry = REGISTERS.get((module, register))
    if entry is None:
        return DecodedRegister(
            name=f"UNKNOWN_{module}_{register}",
            module=module,
            register=register,
            type="unknown",
            unit="",
            value=list(tokens),
            raw_tokens=list(tokens),
            decode_ok=False,
            decode_error="no catalog entry",
        )

    base, count = parse_type(entry.type)

    # char[N] — reassemble tokens as a single string (spacecraft may
    # split embedded whitespace across tokens for TLE-style fields).
    if base == "char":
        joined = " ".join(tokens).rstrip("\x00")[:count]
        return DecodedRegister(
            name=entry.name,
            module=module, register=register,
            type=entry.type, unit=entry.unit,
            value=joined,
            raw_tokens=list(tokens),
            decode_ok=True,
        )

    if len(tokens) < count:
        return DecodedRegister(
            name=entry.name,
            module=module, register=register,
            type=entry.type, unit=entry.unit,
            value=None,
            raw_tokens=list(tokens),
            decode_ok=False,
            decode_error=f"expected {count} tokens, got {len(tokens)}",
        )

    try:
        coerced = [_coerce(base, t) for t in tokens[:count]]
    except (ValueError, TypeError) as e:
        return DecodedRegister(
            name=entry.name,
            module=module, register=register,
            type=entry.type, unit=entry.unit,
            value=None,
            raw_tokens=list(tokens),
            decode_ok=False,
            decode_error=f"coerce failed: {e}",
        )

    if entry.decode_extra:
        value: Any = entry.decode_extra(coerced)
    elif count == 1:
        value = coerced[0]
    else:
        value = coerced

    return DecodedRegister(
        name=entry.name,
        module=module, register=register,
        type=entry.type, unit=entry.unit,
        value=value,
        raw_tokens=list(tokens),
        decode_ok=True,
    )
