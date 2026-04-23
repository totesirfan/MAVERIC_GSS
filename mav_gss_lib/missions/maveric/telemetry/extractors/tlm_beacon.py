"""Authoritative tlm_beacon decoder.

The beacon is a single unified binary struct — no beacon-type
discriminator, no variant tail. The extractor reads the 97-byte
payload from ``cmd["args_raw"]`` (``cmd["args"]`` is the stale ASCII
split the wire parser produces for text commands; it is meaningless
here), decodes it in one ``struct.unpack`` call, and emits canonical
telemetry fragments for the ``spacecraft``, ``gnc`` and ``eps`` domains.

Shape helpers delegate to the semantic decoders under
``telemetry/semantics/`` so a beacon-sourced ``ACT_ERR`` /
``GNC_MODE`` / ``GNC_COUNTERS`` / EPS scalar is value-identical to
one sourced from a RES or ``eps_hk`` packet — consumers read the
same keys from either source.

Wire layout (packed little-endian, 97 bytes; field names mirror the
flight-software struct):

    char     callsign[7]
    uint64_t time
    uint8_t  ops_stage
    uint16_t lppm_rbt_cnt
    uint8_t  lppm_rbt_cause
    uint16_t uppm_rbt_cnt
    uint8_t  uppm_rbt_cause
    uint8_t  ertc_heartbeat
    uint8_t  mtq_heartbeat
    uint8_t  nvg_heartbeat
    uint8_t  eps_heartbeat
    uint8_t  hn_state
    uint8_t  ab_state
    uint32_t mtq_stat
    uint8_t  gyro_rate_src
    uint8_t  mag_src
    float    gyro_rate[3]
    float    mag[3]
    float    mtq_dipole[3]
    float    temp_adcs
    uint16_t i_bus
    uint16_t i_batt
    uint16_t v_bus
    uint16_t v_batt
    uint16_t v_sys
    uint16_t temp_adc
    uint16_t temp_die
    uint16_t eps_mode
    uint8_t  gnc_mode
    uint16_t unexpected_safe_count
    uint16_t unexpected_detumble_count
    uint16_t sunspin_count

``eps_heartbeat`` and ``eps_mode`` are canonical ``eps`` domain keys
(catalog entries in ``TELEMETRY_MANIFEST``). ``eps_heartbeat`` is the
EPS subsystem heartbeat byte; ``eps_mode`` is the EPS operating-mode
raw enum. Neither has a structured wrapper today — promote to a
``{mode, mode_name}`` shape once the FSW enum is documented.
"""
from __future__ import annotations

import struct
from datetime import datetime, timezone

from mav_gss_lib.web_runtime.telemetry import TelemetryFragment


BEACON_STRUCT = struct.Struct(
    "<7sQBHBHBBBBBBBIBB3f3f3ffHHHHHHHHBHHH"
)
assert BEACON_STRUCT.size == 97, f"beacon struct size: {BEACON_STRUCT.size}"


def _spacecraft_time(unix_ms: int) -> dict:
    """Raw unix ms → canonical spacecraft-time dict.

    Shape matches gnc_schema's ``_decode_time`` (``{..., "display": "..."}``)
    so the ``is_bcd_display`` renderer handles compact/detail/log views
    without a new code path.
    """
    try:
        dt = datetime.fromtimestamp(unix_ms / 1000.0, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return {"unix_ms": unix_ms, "iso_utc": None, "display": f"raw={unix_ms}"}
    stamp = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    return {"unix_ms": unix_ms, "iso_utc": stamp, "display": stamp}


def _gnc_mode(mode: int) -> dict:
    """Raw mode byte → canonical GNC_MODE dict (matches ``_handle_gnc_get_mode``)."""
    from mav_gss_lib.missions.maveric.telemetry.semantics.gnc_handlers import (
        GNC_PLANNER_MODE_NAMES,
    )
    return {
        "mode": mode,
        "mode_name": GNC_PLANNER_MODE_NAMES.get(mode, f"UNKNOWN_{mode}"),
    }


def _gnc_counters(safe: int, detumble: int, sunspin: int) -> dict:
    """Three raw counters → canonical GNC_COUNTERS dict (matches ``_handle_gnc_get_cnts``)."""
    return {
        "reboot": safe,
        "detumble": detumble,
        "sunspin": sunspin,
        "unexpected_safe": safe,
    }


def _adcs_tmp(celsius: float) -> dict:
    """Beacon temp_adcs is already in °C; canonical shape matches RES ``_decode_adcs_tmp``."""
    return {"brdtmp": None, "celsius": float(celsius), "comm_fault": False}


def _mtq_stat(mtq_stat: int) -> dict:
    """uint32 mtq_stat → canonical MTQ_STAT bitfield dict.

    Splits the u32 into four LE bytes and feeds through the same
    ``_decode_stat`` the RES path uses for the STAT register (0, 128),
    since the beacon's ``mtq_stat`` IS the STAT register. Shape:
    ``{MODE, MODE_NAME, HERR, SERR, WDT, UV, OC, OT, GNSS_OC,
    GNSS_UP_TO_DATE, TLE, DES, SUN, TGL, TUMB, AME, CUSSV, EKF,
    byte2_raw}``.
    """
    from mav_gss_lib.missions.maveric.telemetry.semantics.gnc_schema import (
        _decode_stat,
    )
    bytes_le = list(struct.pack("<I", mtq_stat & 0xFFFFFFFF))
    return _decode_stat(bytes_le)


def _eps_scaled(name: str, raw: int) -> float:
    """Beacon carries raw int16-style EPS values (mV / mA / raw ADC LSBs);
    scale to engineering units (V / A / % / °C) via the same ``_scale_and_unit``
    table ``eps_hk`` uses, so values are identical from either source."""
    from mav_gss_lib.missions.maveric.telemetry.semantics.eps import _scale_and_unit
    scale, _unit = _scale_and_unit(name)
    return round(raw * scale, 6)


def _callsign(raw7: bytes) -> str:
    return raw7.rstrip(b"\x00").decode("ascii", errors="replace")


def extract(pkt, nodes, now_ms: int):
    md = getattr(pkt, "mission_data", None) or {}
    cmd = md.get("cmd") or {}
    if cmd.get("cmd_id") != "tlm_beacon":
        return
    if nodes.ptype_name(md.get("ptype")) != "TLM":
        return

    args_raw = cmd.get("args_raw") or b""
    if len(args_raw) < BEACON_STRUCT.size:
        return

    (callsign, time_ms, ops_stage, lppm_rbt_cnt, lppm_rbt_cause,
     uppm_rbt_cnt, uppm_rbt_cause, ertc_heartbeat, mtq_heartbeat,
     nvg_heartbeat, eps_heartbeat, hn_state, ab_state,
     mtq_stat, gyro_rate_src, mag_src,
     gyro_x, gyro_y, gyro_z,
     mag_x, mag_y, mag_z,
     mtq_x, mtq_y, mtq_z,
     temp_adcs,
     i_bus, i_bat, v_bus, v_bat, v_sys, temp_adc, temp_die, eps_mode,
     gnc_mode_raw,
     unexpected_safe, unexpected_detumble, sunspin) = BEACON_STRUCT.unpack_from(
        bytes(args_raw), 0,
    )

    # Spacecraft domain — callsign + platform shared state.
    yield TelemetryFragment("spacecraft", "callsign", _callsign(callsign), now_ms)
    yield TelemetryFragment("spacecraft", "time", _spacecraft_time(time_ms), now_ms)
    yield TelemetryFragment("spacecraft", "ops_stage", ops_stage, now_ms)
    yield TelemetryFragment("spacecraft", "lppm_rbt_cnt", lppm_rbt_cnt, now_ms)
    yield TelemetryFragment("spacecraft", "lppm_rbt_cause", lppm_rbt_cause, now_ms)
    yield TelemetryFragment("spacecraft", "uppm_rbt_cnt", uppm_rbt_cnt, now_ms)
    yield TelemetryFragment("spacecraft", "uppm_rbt_cause", uppm_rbt_cause, now_ms)
    yield TelemetryFragment("spacecraft", "ertc_heartbeat", ertc_heartbeat, now_ms)
    yield TelemetryFragment("spacecraft", "hn_state", hn_state, now_ms)
    yield TelemetryFragment("spacecraft", "ab_state", ab_state, now_ms)

    # GNC domain — ADCS state + mode + counters.
    yield TelemetryFragment("gnc", "mtq_heartbeat", mtq_heartbeat, now_ms)
    yield TelemetryFragment("gnc", "nvg_heartbeat", nvg_heartbeat, now_ms)
    yield TelemetryFragment("gnc", "MTQ_STAT", _mtq_stat(mtq_stat), now_ms)
    yield TelemetryFragment("gnc", "GYRO_RATE_SRC", gyro_rate_src, now_ms)
    yield TelemetryFragment("gnc", "MAG_SRC", mag_src, now_ms)
    yield TelemetryFragment("gnc", "RATE", [gyro_x, gyro_y, gyro_z], now_ms)
    yield TelemetryFragment("gnc", "MAG", [mag_x, mag_y, mag_z], now_ms)
    yield TelemetryFragment("gnc", "MTQ", [mtq_x, mtq_y, mtq_z], now_ms)
    yield TelemetryFragment("gnc", "ADCS_TMP", _adcs_tmp(temp_adcs), now_ms)
    yield TelemetryFragment("gnc", "GNC_MODE", _gnc_mode(gnc_mode_raw), now_ms)
    yield TelemetryFragment(
        "gnc", "GNC_COUNTERS",
        _gnc_counters(unexpected_safe, unexpected_detumble, sunspin),
        now_ms,
    )

    # EPS domain — engineering-unit scalars (same scale table as eps_hk).
    yield TelemetryFragment("eps", "I_BUS",  _eps_scaled("I_BUS",  i_bus),    now_ms)
    yield TelemetryFragment("eps", "I_BAT",  _eps_scaled("I_BAT",  i_bat),    now_ms)
    yield TelemetryFragment("eps", "V_BUS",  _eps_scaled("V_BUS",  v_bus),    now_ms)
    yield TelemetryFragment("eps", "V_BAT",  _eps_scaled("V_BAT",  v_bat),    now_ms)
    yield TelemetryFragment("eps", "V_SYS",  _eps_scaled("V_SYS",  v_sys),    now_ms)
    yield TelemetryFragment("eps", "TS_ADC", _eps_scaled("TS_ADC", temp_adc), now_ms)
    yield TelemetryFragment("eps", "T_DIE",  _eps_scaled("T_DIE",  temp_die), now_ms)
    yield TelemetryFragment("eps", "eps_heartbeat", eps_heartbeat, now_ms)
    yield TelemetryFragment("eps", "eps_mode", eps_mode, now_ms)
