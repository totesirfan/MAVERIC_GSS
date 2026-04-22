"""Authoritative tlm_beacon decoder.

Single file; no sibling beacon_map.py. Everything — `Mapping` dataclass,
small parsers, adapter helpers, `COMMON_MAPPINGS`, `BEACON_TYPE_MAPPINGS`,
extractor glue — lives here. Adapter helpers delegate to the relocated
semantic decoders under `telemetry/semantics/` so the beacon-sourced
canonical value shape matches the RES-sourced shape exactly.

The decoder reads `cmd["args"]` — the ordered `list[str]` of
whitespace-split wire tokens produced by `wire_format.CommandFrame.to_dict()`.
That list carries every token on the wire regardless of the schema's
declared rx_args, so `cmd["typed_args"]` is orthogonal to canonical
state here.

The beacon is a single telemetry family with a callsign-prefixed,
discriminator-second variant layout:

    tokens[0]      callsign               (spacecraft identifier, skipped)
    tokens[1]      beacon_type            (uint discriminator)
    tokens[2..13]  shared generic prefix  (platform + gnc/eps heartbeats)
    tokens[14..]   variant tail           (selected by beacon_type)

The callsign is a wire routing artifact, not canonical telemetry — the
extractor reads it to know where the discriminator lives and skips it
otherwise. Pre-callsign wire layout (tokens[0]=btype) is not supported;
recapture fixtures if needed.

Shared prefix and tail mappings are log-derived against a local bench
capture (10 samples, 5 x beacon_type=1 and 5 x beacon_type=2). Status
annotations mark the audit state of each row. See plan Task 9 / 9a.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any, Callable, Literal

from mav_gss_lib.web_runtime.telemetry import TelemetryFragment


MappingStatus = Literal["verified", "plausible", "deferred"]


@dataclass(frozen=True, slots=True)
class Mapping:
    """One row in the beacon decoder table.

    positions  : ordered tuple of token indices this mapping consumes,
                 indexed INSIDE the relevant block (common or tail).
                 Single-element for scalars, multi-element for
                 structured targets like GNC_COUNTERS (3 positions) or
                 RATE/MAG/MTQ (3 floats each).
    domain     : destination domain — always an existing canonical
                 domain ("gnc", "eps", "spacecraft").
    key        : canonical key in that domain. MUST already exist in
                 the domain vocabulary unless the domain is "spacecraft"
                 (a v2-new spacecraft-wide domain whose keys are
                 legitimately new).
    adapter    : callable taking the raw token strings at `positions`
                 and returning the canonical value shape, or None to skip.
    status     : "verified" | "plausible" | "deferred". The extractor
                 skips "deferred" rows entirely.
    """
    positions: tuple[int, ...]
    domain: str
    key: str
    adapter: Callable[[list[str]], Any]
    status: MappingStatus


# ── small parsers ─────────────────────────────────────────────────

def _to_int(vals):
    try:
        return int(vals[0])
    except (TypeError, ValueError, IndexError):
        return None


def _to_float(vals):
    try:
        return float(vals[0])
    except (TypeError, ValueError, IndexError):
        return None


def to_spacecraft_time(vals):
    """Raw unix ms int → canonical spacecraft-time dict.

    The beacon ships wall-clock time as a unix milliseconds integer
    (e.g. `1767229527411`). An operator reading the raw number can't
    tell if the spacecraft clock has synced or when the sample was
    taken. We preserve the raw value for analytics and add formatted
    strings for display.

    Shape matches the BCD/display pattern from gnc_schema's `_decode_time`
    (`{..., "display": "..."}`), so the existing is_bcd_display shape
    renderer handles compact/detail/log views without a new code path.
    """
    from datetime import datetime, timezone

    raw = _to_int(vals)
    if raw is None:
        return None
    try:
        dt = datetime.fromtimestamp(raw / 1000.0, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        # Out-of-range timestamp (negative, > year 9999, etc.) — preserve
        # the raw value but mark display as unknown rather than crash.
        return {
            "unix_ms": raw,
            "iso_utc": None,
            "display": f"raw={raw}",
        }
    return {
        "unix_ms": raw,
        "iso_utc": dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "display": dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


# ── adapter helpers — all delegate to semantic decoders ───────────

def to_gnc_mode(vals):
    """Map raw mode int → canonical GNC_MODE structure.

    Matches the RES shape produced by
    `semantics/gnc_handlers.py::_handle_gnc_get_mode` —
    `{"mode": mode, "mode_name": name}` — so a beacon-sourced
    GNC_MODE and a RES-sourced GNC_MODE are value-identical.
    """
    from mav_gss_lib.missions.maveric.telemetry.semantics.gnc_handlers import (
        GNC_PLANNER_MODE_NAMES,
    )
    mode = _to_int(vals)
    if mode is None:
        return None
    return {
        "mode": mode,
        "mode_name": GNC_PLANNER_MODE_NAMES.get(mode, f"UNKNOWN_{mode}"),
    }


def to_gnc_counters(vals):
    """Map (safe, detumble, sunspin) → canonical GNC_COUNTERS dict.

    Matches `_handle_gnc_get_cnts` exactly so the dashboard consumer
    sees the same keys from either source.
    """
    if len(vals) < 3:
        return None
    try:
        safe = int(vals[0])
        detumble = int(vals[1])
        sunspin = int(vals[2])
    except (TypeError, ValueError):
        return None
    return {
        "reboot": safe,
        "detumble": detumble,
        "sunspin": sunspin,
        "unexpected_safe": safe,
    }


def _vec3(vals):
    if len(vals) < 3:
        return None
    try:
        return [float(vals[0]), float(vals[1]), float(vals[2])]
    except (TypeError, ValueError):
        return None


def to_rate_vector(vals):
    """3 floats → canonical RATE value (list[float] — matches the
    register catalog's `float[3]` shape produced by `decode_register`
    when no decode_extra is present)."""
    return _vec3(vals)


def to_mag_vector(vals):
    """3 floats → canonical MAG value."""
    return _vec3(vals)


def to_mtq_vector(vals):
    """3 floats → canonical MTQ value."""
    return _vec3(vals)


def to_adcs_tmp(vals):
    """Single float → canonical ADCS_TMP dict.

    The beacon wire carries temp_adcs already in engineering units (°C).
    The RES path's canonical shape is
    `{"brdtmp": int, "celsius": float, "comm_fault": bool}` — produced
    by `_decode_adcs_tmp` from a raw int16. Beacon-sourced values
    present the same key set; `brdtmp` is None because the beacon
    tail does not carry the raw ADC reading.
    """
    celsius = _to_float(vals)
    if celsius is None:
        return None
    return {
        "brdtmp": None,
        "celsius": celsius,
        "comm_fault": False,
    }


def to_act_err(vals):
    """uint32 → canonical ACT_ERR bitfield dict.

    The wire slot carries `mtq_stat` packed as one uint32 little-endian
    word. `_decode_act_err` in semantics/gnc_schema.py interprets the
    ACT_ERR register as `uint8[4]` little-endian, so we split the u32
    into four LE bytes and feed it through the exact same decoder —
    beacon-sourced and RES-sourced ACT_ERR values share the same dict
    shape (MTQ0..MTQ2, CMG0..CMG3, byte2_raw, byte3_raw).
    """
    from mav_gss_lib.missions.maveric.telemetry.semantics.gnc_schema import (
        _decode_act_err,
    )
    raw = _to_int(vals)
    if raw is None:
        return None
    raw &= 0xFFFFFFFF
    bytes_le = list(struct.pack("<I", raw))
    return _decode_act_err(bytes_le)


def to_eps_scaled(name: str):
    """Factory: adapter that scales a raw EPS int into engineering units.

    The beacon's EPS tail carries the same raw int16-style values as
    `eps_hk` (mV for voltages, mA for currents, raw BQ25672 ADC LSBs
    for TS_ADC / T_DIE). The canonical EPS domain is engineering-unit
    (V / A / °C / %) via `decode_eps_hk` in `semantics/eps.py`. Reusing
    `_scale_and_unit` keeps one source of truth for unit conversion —
    beacon-sourced and eps_hk-sourced values for the same canonical
    key are value-identical.
    """
    from mav_gss_lib.missions.maveric.telemetry.semantics.eps import _scale_and_unit
    scale, _unit = _scale_and_unit(name)

    def adapter(vals):
        try:
            raw = int(vals[0])
        except (TypeError, ValueError, IndexError):
            return None
        return round(raw * scale, 6)

    return adapter


# ── Mapping tables (log-derived; see module docstring) ──────────────

# Position accounting rule: every wire slot MUST have a Mapping row
# even if its canonical destination is not yet settled. A row with
# status="deferred" reserves the slot (so later positions do not
# shift) and the extractor skips it. Adding a canonical key later
# is a one-row status flip plus (if needed) one helper.
#
# All shared-prefix rows verified against 10 live tlm_beacon samples
# (5 × beacon_type=1, 5 × beacon_type=2) captured in
# Downlink Apr 21 2026.jsonl. Position ordering matches the FSW CSV
# exactly; commands.yml's labels for positions 4+ are misaligned and
# should be ignored for beacon semantics.
COMMON_MAPPINGS: tuple[Mapping, ...] = (
    Mapping((0,),  "spacecraft", "time",           to_spacecraft_time, "verified"),
    Mapping((1,),  "spacecraft", "ops_stage",      _to_int, "verified"),
    Mapping((2,),  "spacecraft", "lppm_rbt_cnt",   _to_int, "verified"),
    Mapping((3,),  "spacecraft", "lppm_rbt_cause", _to_int, "verified"),
    Mapping((4,),  "spacecraft", "uppm_rbt_cnt",   _to_int, "verified"),
    Mapping((5,),  "spacecraft", "uppm_rbt_cause", _to_int, "verified"),
    Mapping((6,),  "spacecraft", "ertc_heartbeat", _to_int, "verified"),
    Mapping((7,),  "gnc",      "mtq_heartbeat",  _to_int, "verified"),
    Mapping((8,),  "gnc",      "nvg_heartbeat",  _to_int, "verified"),
    # Position 9 carries eps_heartbeat on the wire. No canonical key
    # today; row reserves the slot so hn_state / ab_state indices don't
    # shift. Extractor skips.
    Mapping((9,),  "eps",      "eps_heartbeat",  _to_int, "deferred"),
    # eps_heartbeat_time is explicitly NOT transmitted — no slot.
    Mapping((10,), "spacecraft", "hn_state",       _to_int, "verified"),
    Mapping((11,), "spacecraft", "ab_state",       _to_int, "verified"),
)


BEACON_TYPE_MAPPINGS: dict[int, tuple[Mapping, ...]] = {
    # Beacon 1 — ADCS/GNC tail. Canonical destinations verified
    # (present in gnc_schema.REGISTERS / gnc_handlers' RES output). The
    # per-row qualifier reflects whether the adapter is confirmed to
    # produce the canonical SHAPE, not merely whether the key exists.
    1: (
        # ACT_ERR: the beacon wire carries mtq_stat as one uint32. Packing it
        # into 4 LE bytes and feeding through _decode_act_err produces the
        # same `{MTQ0..2, CMG0..3, byte2_raw, byte3_raw}` dict shape the
        # RES-sourced register decoder produces — the `ActErrBitfield`
        # consumer in types.ts reads identical keys from either source.
        # Hand-check (plan Task 9a Step 2): mtq_stat = 0x60000000 in all
        # 5 beacon-1 samples → LE bytes [0x00, 0x00, 0x00, 0x60] → every
        # named bit is 0; byte3_raw = 0x60 (bits 29/30 preserved losslessly).
        # Whatever those bits encode in the FSW is a separate semantic
        # question; the shape contract holds.
        Mapping((0,),          "gnc", "ACT_ERR",       to_act_err,       "verified"),
        Mapping((1,),          "gnc", "GNC_MODE",      to_gnc_mode,      "verified"),
        Mapping((2, 3, 4),     "gnc", "GNC_COUNTERS",  to_gnc_counters,  "verified"),
        # GYRO_RATE_SRC / MAG_SRC: the spacecraft-selected active source
        # for the rate and magnetic vectors. Raw int canonical value —
        # the repo has no gyro/mag source enum today, and adding one
        # here would invent a second naming scheme (see the "do not
        # invent canonical keys" rule in the Deferred comment block
        # below). Frontend consumers that need a human label should
        # add one at render time.
        Mapping((5,),          "gnc", "GYRO_RATE_SRC", _to_int,          "verified"),
        Mapping((6,),          "gnc", "MAG_SRC",       _to_int,          "verified"),
        Mapping((7, 8, 9),     "gnc", "RATE",          to_rate_vector,   "verified"),
        Mapping((10, 11, 12),  "gnc", "MAG",           to_mag_vector,    "verified"),
        Mapping((13, 14, 15),  "gnc", "MTQ",           to_mtq_vector,    "verified"),
        Mapping((16,),         "gnc", "ADCS_TMP",      to_adcs_tmp,      "verified"),
    ),
    # Beacon 2 — EPS tail. All scalar destinations verified against
    # recent log samples; canonical keys already consumed by the EPS
    # dashboard and eps_hk decoder. Adapters are to_eps_scaled(key) —
    # NOT _to_int — because the beacon wire carries mV / mA / raw ADC
    # LSBs and the canonical EPS domain is engineering-unit (V / A /
    # °C / %).
    2: (
        Mapping((0,),  "eps", "I_BUS",    to_eps_scaled("I_BUS"),  "verified"),
        Mapping((1,),  "eps", "I_BAT",    to_eps_scaled("I_BAT"),  "verified"),
        Mapping((2,),  "eps", "V_BUS",    to_eps_scaled("V_BUS"),  "verified"),
        Mapping((3,),  "eps", "V_BAT",    to_eps_scaled("V_BAT"),  "verified"),
        Mapping((4,),  "eps", "V_SYS",    to_eps_scaled("V_SYS"),  "verified"),
        Mapping((5,),  "eps", "TS_ADC",   to_eps_scaled("TS_ADC"), "verified"),
        Mapping((6,),  "eps", "T_DIE",    to_eps_scaled("T_DIE"),  "verified"),
        # Position 7: eps_mode — deferred (slot reserved). _to_int is
        # correct for a mode byte (no unit conversion) but the row is
        # still skipped until a canonical key lands.
        Mapping((7,),  "eps", "eps_mode", _to_int,                "deferred"),
    ),
}


# -----------------------------------------------------------------------
# Deferred — layout understood (slot reserved above), but canonical
# representation unsettled. Add a proper canonical target + adapter
# when the destination key exists elsewhere in the codebase. Do NOT
# invent a new canonical key here to fill the slot — that would create
# a second naming scheme.
# -----------------------------------------------------------------------
#   eps_heartbeat   (shared prefix, position 9)
#   eps_mode        (Beacon 2 tail, position 7)


# ── Extractor glue ────────────────────────────────────────────────

def _emit(mappings: tuple[Mapping, ...], tokens: list[str],
          base_offset: int, now_ms: int):
    for m in mappings:
        if m.status == "deferred":
            continue
        try:
            values = [tokens[base_offset + p] for p in m.positions]
        except IndexError:
            continue
        value = m.adapter(values)
        if value is None:
            continue
        yield TelemetryFragment(m.domain, m.key, value, now_ms)


def extract(pkt, nodes, now_ms: int):
    md = getattr(pkt, "mission_data", None) or {}
    cmd = md.get("cmd") or {}
    if cmd.get("cmd_id") != "tlm_beacon":
        return
    if nodes.ptype_name(md.get("ptype")) != "TLM":
        return
    tokens = cmd.get("args") or []
    # Minimum legible beacon: callsign + beacon_type.
    if len(tokens) < 2:
        return
    btype = _to_int([tokens[1]])

    # Callsign — canonical spacecraft identifier. Emit as a string-valued
    # fragment so the UI can read it from useTelemetry('spacecraft')
    # alongside every other spacecraft-wide field (time, ops_stage, …).
    yield TelemetryFragment("spacecraft", "callsign", str(tokens[0]), now_ms)

    # Shared prefix — emitted on every beacon regardless of btype.
    # tokens[0] = callsign (handled above), tokens[1] = beacon_type,
    # tokens[2..] = shared prefix.
    yield from _emit(COMMON_MAPPINGS, tokens, base_offset=2, now_ms=now_ms)

    if btype is None:
        return
    tail = BEACON_TYPE_MAPPINGS.get(btype)
    if not tail:
        return
    # Tail offset: 2 (callsign + beacon_type header) + prefix-length
    # derived from the table so the layout stays a single source of
    # truth. COMMON_MAPPINGS covers positions 0..11 contiguously
    # (12 slots); eps_heartbeat_time is explicitly NOT transmitted, so
    # no gap. Deferred rows still consume a wire slot, so they must
    # remain in the max() computation.
    prefix_len = 2 + (max(p for m in COMMON_MAPPINGS for p in m.positions) + 1)
    # → with today's table: 2 + 12 = 14; tail tokens start at
    #   tokens[14], i.e. tokens[0]=callsign, tokens[1]=beacon_type,
    #   tokens[2..13]=prefix, tokens[14..]=variant tail.
    yield from _emit(tail, tokens, base_offset=prefix_len, now_ms=now_ms)
