"""Synthetic unit tests for the tlm_beacon extractor.

Build wire-token lists by hand so every Mapping row's behavior is
exercised without depending on a local fixture. Task 9a adds a
fixture-gated regression test against a real bench capture; this file
focuses on the semantics of the mapping tables.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.missions.maveric.telemetry.extractors import tlm_beacon
from mav_gss_lib.missions.maveric.telemetry.extractors.tlm_beacon import (
    BEACON_TYPE_MAPPINGS,
    COMMON_MAPPINGS,
    Mapping,
    extract,
)
from mav_gss_lib.missions.maveric.nodes import NodeTable


def _nodes():
    return NodeTable(
        node_names={0: "GS", 1: "SAT"},
        node_ids={"GS": 0, "SAT": 1},
        ptype_names={0: "CMD", 1: "ACK", 2: "TLM", 3: "RES", 4: "FILE"},
        ptype_ids={"CMD": 0, "ACK": 1, "TLM": 2, "RES": 3, "FILE": 4},
        gs_node=0,
    )


# 12 prefix positions verified in COMMON_MAPPINGS — build a plausible
# sample. Token[0] = beacon_type, tokens[1..12] = shared prefix.
PREFIX_SAMPLE = [
    "1000000",  # time
    "4",        # ops_stage
    "2",        # lppm_rbt_cnt
    "0",        # lppm_rbt_cause
    "3",        # uppm_rbt_cnt
    "4",        # uppm_rbt_cause
    "200",      # ertc_heartbeat
    "201",      # mtq_heartbeat
    "202",      # nvg_heartbeat
    "203",      # eps_heartbeat (deferred)
    "1",        # hn_state
    "2",        # ab_state
]


_CALLSIGN = "WQ2XIC"


def _beacon_pkt(beacon_type: int, tail: list[str], cmd_id: str = "tlm_beacon",
                ptype_id: int = 2):
    # Wire layout: callsign, beacon_type, 12 prefix positions, variant tail.
    tokens = [_CALLSIGN, str(beacon_type), *PREFIX_SAMPLE, *tail]
    return SimpleNamespace(mission_data={
        "ptype": ptype_id,
        "cmd": {"cmd_id": cmd_id, "args": tokens},
    })


BEACON_1_TAIL = [
    "1610612736",  # mtq_stat = 0x60000000
    "1",           # gnc_mode
    "166",         # unexpected_safe_count
    "3",           # unexpected_detumble_count
    "5",           # sunspin_count
    "2",           # GYRO_RATE_SRC (raw int; no enum in repo)
    "3",           # MAG_SRC (raw int; no enum in repo)
    "0.01", "0.02", "0.03",   # rate[3]
    "1.0", "2.0", "3.0",      # mag[3]
    "0.1", "0.2", "0.3",      # mtq_dipole[3]
    "21.5",                   # temp_adcs
]

BEACON_2_TAIL = [
    "458",      # i_bus (mA → 0.458 A)
    "-300",     # i_bat (mA → -0.300 A)
    "7500",     # v_bus (mV → 7.500 V)
    "7622",     # v_bat (mV → 7.622 V)
    "7700",     # v_sys (mV → 7.700 V)
    "512",      # ts_adc raw
    "65",       # t_die raw
    "3",        # eps_mode (deferred)
]


class TestBeaconExtractorGating(unittest.TestCase):
    def test_wrong_cmd_id_yields_nothing(self):
        pkt = _beacon_pkt(1, BEACON_1_TAIL, cmd_id="eps_hk")
        self.assertEqual(list(extract(pkt, _nodes(), 0)), [])

    def test_non_tlm_ptype_yields_nothing(self):
        for ptype in (0, 1, 3, 4):
            pkt = _beacon_pkt(1, BEACON_1_TAIL, ptype_id=ptype)
            self.assertEqual(list(extract(pkt, _nodes(), 0)), [],
                             msg=f"ptype={ptype} should not emit")

    def test_empty_args_yields_nothing(self):
        pkt = SimpleNamespace(mission_data={
            "ptype": 2, "cmd": {"cmd_id": "tlm_beacon", "args": []},
        })
        self.assertEqual(list(extract(pkt, _nodes(), 0)), [])


class TestSharedPrefix(unittest.TestCase):
    def test_prefix_emits_verified_rows(self):
        pkt = _beacon_pkt(1, BEACON_1_TAIL)
        frags = list(extract(pkt, _nodes(), now_ms=500))
        by_key = {(f.domain, f.key): f for f in frags}

        # Every verified shared-prefix row emitted.
        self.assertEqual(by_key[("spacecraft", "time")].value, 1000000)
        self.assertEqual(by_key[("spacecraft", "ops_stage")].value, 4)
        self.assertEqual(by_key[("spacecraft", "uppm_rbt_cnt")].value, 3)
        self.assertEqual(by_key[("spacecraft", "hn_state")].value, 1)
        self.assertEqual(by_key[("gnc", "mtq_heartbeat")].value, 201)
        self.assertEqual(by_key[("gnc", "nvg_heartbeat")].value, 202)

        # Deferred rows skipped.
        self.assertNotIn(("eps", "eps_heartbeat"), by_key)

    def test_ts_ms_propagated(self):
        pkt = _beacon_pkt(1, BEACON_1_TAIL)
        frags = list(extract(pkt, _nodes(), now_ms=12345))
        for f in frags:
            self.assertEqual(f.ts_ms, 12345)

    def test_single_packet_routes_across_multiple_domains(self):
        pkt = _beacon_pkt(1, BEACON_1_TAIL)
        frags = list(extract(pkt, _nodes(), 0))
        domains = {f.domain for f in frags}
        self.assertIn("spacecraft", domains)
        self.assertIn("gnc", domains)


class TestBeacon1Tail(unittest.TestCase):
    def test_gnc_mode_has_canonical_shape(self):
        pkt = _beacon_pkt(1, BEACON_1_TAIL)
        frags = [f for f in extract(pkt, _nodes(), 0) if f.key == "GNC_MODE"]
        self.assertEqual(len(frags), 1)
        self.assertIsInstance(frags[0].value, dict)
        self.assertEqual(frags[0].value["mode"], 1)
        self.assertIn("mode_name", frags[0].value)

    def test_gnc_counters_is_one_structured_fragment(self):
        pkt = _beacon_pkt(1, BEACON_1_TAIL)
        frags = [f for f in extract(pkt, _nodes(), 0) if f.key == "GNC_COUNTERS"]
        self.assertEqual(len(frags), 1)
        v = frags[0].value
        self.assertEqual(v["reboot"], 166)
        self.assertEqual(v["detumble"], 3)
        self.assertEqual(v["sunspin"], 5)

    def test_rate_mag_mtq_are_three_element_vectors(self):
        pkt = _beacon_pkt(1, BEACON_1_TAIL)
        frags = {f.key: f.value for f in extract(pkt, _nodes(), 0)
                 if f.key in ("RATE", "MAG", "MTQ")}
        self.assertEqual(frags["RATE"], [0.01, 0.02, 0.03])
        self.assertEqual(frags["MAG"], [1.0, 2.0, 3.0])
        self.assertEqual(frags["MTQ"], [0.1, 0.2, 0.3])

    def test_adcs_tmp_canonical_shape(self):
        pkt = _beacon_pkt(1, BEACON_1_TAIL)
        adcs = next(f for f in extract(pkt, _nodes(), 0) if f.key == "ADCS_TMP")
        self.assertIsInstance(adcs.value, dict)
        self.assertEqual(set(adcs.value), {"brdtmp", "celsius", "comm_fault"})
        self.assertEqual(adcs.value["celsius"], 21.5)

    def test_act_err_canonical_bitfield_shape(self):
        pkt = _beacon_pkt(1, BEACON_1_TAIL)
        act = next(f for f in extract(pkt, _nodes(), 0) if f.key == "ACT_ERR")
        # Shape must match _decode_act_err's output regardless of verified
        # vs plausible status.
        expected_keys = {"MTQ0", "MTQ1", "MTQ2",
                         "CMG0", "CMG1", "CMG2", "CMG3",
                         "byte2_raw", "byte3_raw"}
        self.assertEqual(set(act.value.keys()), expected_keys)
        # mtq_stat = 0x60000000 → byte3_raw = 0x60.
        self.assertEqual(act.value["byte3_raw"], 0x60)

    def test_callsign_emits_as_spacecraft_fragment(self):
        """tokens[0] is the spacecraft callsign — emitted as a string-valued
        fragment in the spacecraft domain so the UI can read it from
        useTelemetry('spacecraft') alongside time/ops_stage/reboots."""
        pkt = _beacon_pkt(1, BEACON_1_TAIL)
        frags = {(f.domain, f.key): f for f in extract(pkt, _nodes(), 0)}

        self.assertIn(("spacecraft", "callsign"), frags)
        self.assertEqual(frags[("spacecraft", "callsign")].value, _CALLSIGN)
        self.assertEqual(frags[("spacecraft", "callsign")].unit, "")

    def test_source_selectors_emit_as_canonical_gnc_keys(self):
        pkt = _beacon_pkt(1, BEACON_1_TAIL)
        frags = {f.key: f for f in extract(pkt, _nodes(), 0)
                 if f.domain == "gnc"}

        self.assertIn("GYRO_RATE_SRC", frags)
        self.assertIn("MAG_SRC", frags)
        # Raw int canonical values (no enum mapping in repo).
        self.assertEqual(frags["GYRO_RATE_SRC"].value, 2)
        self.assertEqual(frags["MAG_SRC"].value, 3)
        self.assertEqual(frags["GYRO_RATE_SRC"].unit, "")
        self.assertEqual(frags["MAG_SRC"].unit, "")
        # Old lowercase names are NOT emitted — we're using canonical uppercase.
        self.assertNotIn("gyro_rate_src", frags)
        self.assertNotIn("mag_src", frags)


class TestBeacon2Tail(unittest.TestCase):
    def test_eps_scalars_are_engineering_unit(self):
        pkt = _beacon_pkt(2, BEACON_2_TAIL)
        frags = {f.key: f.value for f in extract(pkt, _nodes(), 0)
                 if f.domain == "eps"}

        # Every verified EPS scalar present and scaled.
        self.assertAlmostEqual(frags["V_BAT"], 7.622, places=3)
        self.assertAlmostEqual(frags["V_BUS"], 7.500, places=3)
        self.assertAlmostEqual(frags["V_SYS"], 7.700, places=3)
        self.assertAlmostEqual(frags["I_BUS"], 0.458, places=3)
        self.assertAlmostEqual(frags["I_BAT"], -0.300, places=3)
        # T_DIE raw=65 → 65 * 0.5 = 32.5 °C
        self.assertAlmostEqual(frags["T_DIE"], 32.5, places=3)

        # eps_mode is deferred — skipped.
        self.assertNotIn("eps_mode", frags)

    def test_beacon_2_emits_platform_prefix_too(self):
        pkt = _beacon_pkt(2, BEACON_2_TAIL)
        domains = {f.domain for f in extract(pkt, _nodes(), 0)}
        self.assertIn("spacecraft", domains)
        self.assertIn("eps", domains)


class TestUnknownBeaconType(unittest.TestCase):
    def test_unknown_btype_still_emits_prefix(self):
        pkt = _beacon_pkt(99, BEACON_1_TAIL)
        frags = list(extract(pkt, _nodes(), 0))
        domains = {f.domain for f in frags}
        self.assertIn("spacecraft", domains)
        # No tail — no gnc keys beyond the heartbeats in the prefix.
        gnc_keys = {f.key for f in frags if f.domain == "gnc"}
        self.assertNotIn("GNC_MODE", gnc_keys)
        self.assertNotIn("RATE", gnc_keys)


class TestTruncatedPacket(unittest.TestCase):
    def test_truncated_tail_still_emits_what_it_can(self):
        # Truncate to just 3 tail tokens — GNC_COUNTERS needs positions
        # 2/3/4 and RATE needs 7/8/9; both become IndexError and are
        # skipped, but ACT_ERR (pos 0) and GNC_MODE (pos 1) still fire.
        short_tail = BEACON_1_TAIL[:2]  # mtq_stat + gnc_mode only
        pkt = _beacon_pkt(1, short_tail)
        frags = list(extract(pkt, _nodes(), 0))
        gnc_keys = {f.key for f in frags if f.domain == "gnc"}
        self.assertIn("ACT_ERR", gnc_keys)
        self.assertIn("GNC_MODE", gnc_keys)
        self.assertNotIn("RATE", gnc_keys)
        self.assertNotIn("GNC_COUNTERS", gnc_keys)


class TestEmptyMappingTables(unittest.TestCase):
    def test_empty_common_mappings(self):
        # Monkeypatch empty tables to prove emission is table-driven.
        original_common = tlm_beacon.COMMON_MAPPINGS
        original_tails = tlm_beacon.BEACON_TYPE_MAPPINGS
        tlm_beacon.COMMON_MAPPINGS = ()
        tlm_beacon.BEACON_TYPE_MAPPINGS = {}
        try:
            pkt = _beacon_pkt(1, BEACON_1_TAIL)
            # ValueError inside extract when computing prefix_len over
            # empty COMMON_MAPPINGS — extract short-circuits before the
            # tail step via `tail = BEACON_TYPE_MAPPINGS.get(btype)`, but
            # the prefix_len computation would only run when a tail is
            # present. With empty tails, extract yields only whatever
            # the (empty) prefix emits — nothing.
            frags = list(extract(pkt, _nodes(), 0))
            # Callsign is emitted unconditionally (it's the spacecraft
            # identifier, not a mapping-table row). With empty mapping
            # tables nothing else should emit.
            keys = [(f.domain, f.key) for f in frags]
            self.assertEqual(keys, [("spacecraft", "callsign")])
        finally:
            tlm_beacon.COMMON_MAPPINGS = original_common
            tlm_beacon.BEACON_TYPE_MAPPINGS = original_tails


class TestNoSiblingBeaconMap(unittest.TestCase):
    def test_beacon_map_module_does_not_exist(self):
        """Single-file ownership — no sibling beacon_map.py."""
        import importlib
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module(
                "mav_gss_lib.missions.maveric.telemetry.extractors.beacon_map"
            )


class TestMappingTableCoverage(unittest.TestCase):
    """Every canonical name targeted by the beacon tables must already
    exist somewhere authoritative — either in the GNC register catalog,
    in the EPS name list, or in the platform domain (v2-new)."""

    def test_gnc_keys_exist_in_catalog(self):
        """Every beacon-emitted gnc key must appear in the mission's
        telemetry catalog. The catalog is the single source of truth for
        canonical gnc keys + metadata, covering both addressable
        registers and non-register canonical keys (handler-emitted,
        beacon-only). An unknown key here = a silent scope expansion
        that needs a catalog entry first."""
        from mav_gss_lib.missions.maveric.telemetry import TELEMETRY_MANIFEST
        catalog_names = {e["name"] for e in TELEMETRY_MANIFEST["gnc"]["catalog"]()}
        gnc_keys = {m.key for m in BEACON_TYPE_MAPPINGS[1]
                    if m.status != "deferred" and m.domain == "gnc"}
        missing = gnc_keys - catalog_names
        self.assertFalse(missing, f"beacon gnc keys missing from catalog: {missing}")

    def test_eps_keys_exist_in_eps_hk_names(self):
        from mav_gss_lib.missions.maveric.telemetry.semantics.eps import _EPS_HK_NAMES
        eps_keys = {m.key for m in BEACON_TYPE_MAPPINGS[2]
                    if m.status != "deferred" and m.domain == "eps"}
        missing = eps_keys - set(_EPS_HK_NAMES)
        self.assertFalse(missing, f"unknown eps keys in beacon map: {missing}")


if __name__ == "__main__":
    unittest.main()
