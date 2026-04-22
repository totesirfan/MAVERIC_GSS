"""Fixture-gated regression test for tlm_beacon decoder against real bench logs.

Loads a current-layout downlink capture (machine-local, gitignored),
re-parses every tlm_beacon wire frame through try_parse_command, feeds
the resulting cmd through the extractor, and asserts every "verified"
mapping row produces the expected canonical output.

Gated on fixture presence so CI / other hosts skip gracefully.

Fixture layout must match the current wire (callsign, beacon_type,
prefix, tail). The pre-callsign Apr 21 2026 capture is incompatible
with today's extractor — drop a new capture under
`tests/fixtures/beacon_samples/downlink_current.jsonl` to re-enable.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURE = Path(__file__).parent / "fixtures" / "beacon_samples" / "downlink_current.jsonl"

pytestmark = pytest.mark.skipif(
    not FIXTURE.exists(),
    reason="current-layout beacon fixture not present (machine-local; drop a "
           "recent downlink JSONL at tests/fixtures/beacon_samples/downlink_current.jsonl)",
)


from mav_gss_lib.missions.maveric.wire_format import try_parse_command
from mav_gss_lib.missions.maveric.telemetry.extractors.tlm_beacon import (
    BEACON_TYPE_MAPPINGS,
    COMMON_MAPPINGS,
    extract,
)
from mav_gss_lib.missions.maveric.nodes import NodeTable


def _nodes():
    # Platform wire uses ptype=5 for TLM on maveric; align the minimal
    # NodeTable stub here with that.
    return NodeTable(
        node_names={0: "GS"},
        node_ids={"GS": 0},
        ptype_names={0: "CMD", 1: "ACK", 2: "TLM", 3: "RES", 4: "FILE", 5: "TLM"},
        ptype_ids={"TLM": 5},
        gs_node=0,
    )


def _load_beacon_packets():
    """Parse every tlm_beacon record in the fixture into (btype, cmd_dict)."""
    out: list[tuple[int, dict]] = []
    for line in FIXTURE.read_text().splitlines():
        obj = json.loads(line)
        cmd_str = ((obj.get("_rendering") or {}).get("row") or {}).get("values", {}).get("cmd", "")
        if not cmd_str.startswith("tlm_beacon"):
            continue
        payload = bytes.fromhex(obj["payload_hex"])
        cmd, _tail = try_parse_command(payload[4:])
        if cmd is None:
            continue
        args = cmd.get("args") or []
        if not args:
            continue
        try:
            btype = int(args[0])
        except (TypeError, ValueError):
            continue
        out.append((btype, cmd))
    return out


def _run_extractor(cmd):
    pkt = SimpleNamespace(mission_data={"cmd": cmd, "ptype": cmd.get("pkt_type")})
    return list(extract(pkt, _nodes(), now_ms=1_700_000_000_000))


class TestFixtureContents:
    """The fixture should carry exactly 10 beacons — 5 of each type."""

    def test_fixture_counts(self):
        beacons = _load_beacon_packets()
        by_type = {t: 0 for t in (1, 2)}
        for bt, _ in beacons:
            by_type[bt] = by_type.get(bt, 0) + 1
        assert by_type == {1: 5, 2: 5}, \
            f"expected 5+5 beacons in Apr 21 fixture; got {by_type}"


class TestVerifiedRowsFire:
    """Every verified mapping row must emit a fragment for every sample."""

    def test_every_beacon_emits_full_shared_prefix(self):
        expected_prefix = {
            (m.domain, m.key) for m in COMMON_MAPPINGS if m.status == "verified"
        }
        for bt, cmd in _load_beacon_packets():
            frags = _run_extractor(cmd)
            keys = {(f.domain, f.key) for f in frags}
            missing = expected_prefix - keys
            assert not missing, f"beacon_type={bt}: missing prefix {missing}"

    def test_every_beacon1_emits_full_gnc_tail(self):
        expected = {m.key for m in BEACON_TYPE_MAPPINGS[1] if m.status == "verified"}
        for bt, cmd in _load_beacon_packets():
            if bt != 1:
                continue
            keys = {f.key for f in _run_extractor(cmd) if f.domain == "gnc"
                    and f.key in expected}
            assert keys == expected, \
                f"beacon_type=1 tail: missing {expected - keys}"

    def test_every_beacon2_emits_full_eps_tail(self):
        expected = {m.key for m in BEACON_TYPE_MAPPINGS[2] if m.status == "verified"}
        for bt, cmd in _load_beacon_packets():
            if bt != 2:
                continue
            keys = {f.key for f in _run_extractor(cmd) if f.domain == "eps"
                    and f.key in expected}
            assert keys == expected, \
                f"beacon_type=2 tail: missing {expected - keys}"


class TestDomainRouting:
    def test_beacon_1_routes_to_platform_and_gnc(self):
        for bt, cmd in _load_beacon_packets():
            if bt != 1:
                continue
            domains = {f.domain for f in _run_extractor(cmd)}
            assert "platform" in domains
            assert "gnc" in domains

    def test_beacon_2_routes_to_platform_and_eps(self):
        for bt, cmd in _load_beacon_packets():
            if bt != 2:
                continue
            domains = {f.domain for f in _run_extractor(cmd)}
            assert "platform" in domains
            assert "eps" in domains


class TestDeferredRowsSkip:
    def test_deferred_keys_never_emit(self):
        deferred = {m.key for m in COMMON_MAPPINGS if m.status == "deferred"}
        for bt in (1, 2):
            deferred |= {m.key for m in BEACON_TYPE_MAPPINGS[bt] if m.status == "deferred"}
        for bt, cmd in _load_beacon_packets():
            emitted = {f.key for f in _run_extractor(cmd)}
            stale = deferred & emitted
            assert not stale, f"beacon_type={bt}: deferred rows leaked {stale}"


class TestValueSpotChecks:
    """Pin specific canonical values from the live fixture so silent drift
    in the mapping tables breaks this test."""

    def test_uppm_rbt_cnt_monotonic_across_beacon_1(self):
        vals = []
        for bt, cmd in _load_beacon_packets():
            if bt != 1:
                continue
            frags = _run_extractor(cmd)
            for f in frags:
                if f.key == "uppm_rbt_cnt":
                    vals.append(f.value)
        # Values in the fixture are [216, 216, 218, 220, 222] — monotonic non-decreasing.
        assert vals == sorted(vals), f"uppm_rbt_cnt not monotonic: {vals}"
        assert vals[0] >= 200, f"first sample value {vals[0]} not in plausible range"

    def test_v_bat_in_engineering_unit_range_across_beacon_2(self):
        for bt, cmd in _load_beacon_packets():
            if bt != 2:
                continue
            frags = _run_extractor(cmd)
            v_bat = next((f.value for f in frags if f.key == "V_BAT"), None)
            assert v_bat is not None
            # Engineering-unit assertion — raw wire is mV (~7000–8500) but
            # the canonical domain-state value is volts.
            assert 7.0 <= v_bat <= 8.5, (
                f"V_BAT {v_bat} out of plausible 7.0–8.5 V engineering range "
                f"(would be raw mV if scaling is off)"
            )

    def test_gnc_counters_first_component_non_decreasing(self):
        vals = []
        for bt, cmd in _load_beacon_packets():
            if bt != 1:
                continue
            frags = _run_extractor(cmd)
            cnts = next((f.value for f in frags if f.key == "GNC_COUNTERS"), None)
            assert cnts is not None
            vals.append(cnts["reboot"])
        # Fixture has unexpected_safe counter [166, 184, 212, 218, 232] — strictly increasing.
        assert vals == sorted(vals), f"GNC_COUNTERS.reboot not monotonic: {vals}"

    def test_act_err_shape_matches_res_canonical(self):
        """ACT_ERR dict from the beacon must carry the same keys the RES
        path's _decode_act_err produces — that's the shape contract the
        dashboard's ActErrBitfield consumer relies on."""
        required = {"MTQ0", "MTQ1", "MTQ2",
                    "CMG0", "CMG1", "CMG2", "CMG3",
                    "byte2_raw", "byte3_raw"}
        for bt, cmd in _load_beacon_packets():
            if bt != 1:
                continue
            frags = _run_extractor(cmd)
            act_err = next((f.value for f in frags if f.key == "ACT_ERR"), None)
            assert act_err is not None
            assert set(act_err.keys()) == required
            # All 5 fixture samples have mtq_stat = 0x60000000 →
            # byte3_raw = 0x60 = 96.
            assert act_err["byte3_raw"] == 0x60

    def test_gnc_mode_shape_matches_res_canonical(self):
        for bt, cmd in _load_beacon_packets():
            if bt != 1:
                continue
            frags = _run_extractor(cmd)
            mode = next((f.value for f in frags if f.key == "GNC_MODE"), None)
            assert mode is not None
            assert set(mode.keys()) == {"mode", "mode_name"}
