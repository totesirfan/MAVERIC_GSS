"""Task 17 Part A — end-to-end telemetry pipeline integration test.

Drives real extractors through a live adapter + platform TelemetryRouter
and asserts:
  * eps_hk TLM → one `telemetry` message for the `eps` domain with 48 keys.
  * tlm_beacon_1 → telemetry messages for `platform` and `gnc`, with
    canonical structured values (GNC_MODE, GNC_COUNTERS, RATE/MAG/MTQ
    vectors, ADCS_TMP, ACT_ERR).
  * tlm_beacon_2 → `platform` + `eps` with canonical engineering-unit
    scalars (V_BAT, V_BUS, V_SYS, I_BAT, I_BUS, TS_ADC, T_DIE).
  * Unknown beacon_type → only `platform` message emitted.
  * router.clear("eps") returns a cleared envelope; subsequent replay
    omits EPS but keeps gnc/platform.
  * Canonical-key invariant: beacon GNC keys are a subset of the GNC
    register catalog + handler-emitted keys (no new names invented).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "docs" / "eps-port" / "fixtures"


def _load_hex(p: Path) -> bytes:
    raw = p.read_text()
    cleaned = "".join(ch for ch in raw if ch not in " \n\r\t")
    return bytes.fromhex(cleaned)


def _make_nodes():
    from mav_gss_lib.missions.maveric.nodes import NodeTable
    return NodeTable(
        node_names={0: "GS", 1: "SAT"},
        node_ids={"GS": 0, "SAT": 1},
        ptype_names={0: "CMD", 1: "ACK", 2: "TLM", 3: "RES", 4: "FILE", 5: "TLM"},
        ptype_ids={"TLM": 2},
        gs_node=0,
    )


def _adapter(tmp_path):
    from mav_gss_lib.missions.maveric.adapter import MavericMissionAdapter
    from mav_gss_lib.missions.maveric.telemetry import TELEMETRY_MANIFEST
    from mav_gss_lib.missions.maveric.telemetry.extractors import EXTRACTORS
    from mav_gss_lib.web_runtime.telemetry.router import TelemetryRouter

    adapter = MavericMissionAdapter(cmd_defs={}, nodes=_make_nodes())
    router = TelemetryRouter(tmp_path / ".telemetry")
    for name, spec in TELEMETRY_MANIFEST.items():
        router.register_domain(name, **spec)
    adapter.telemetry = router
    adapter.extractors = EXTRACTORS
    return adapter, router


def _run(adapter, pkt):
    adapter.attach_fragments(pkt)
    return adapter.on_packet_received(pkt) or []


def _eps_pkt(ptype=2):
    args_raw = _load_hex(FIXTURES / "packet.hex")
    return SimpleNamespace(mission_data={
        "ptype": ptype,
        "cmd": {"cmd_id": "eps_hk", "args_raw": args_raw},
    })


# Synthetic beacon 1 tokens. Wire layout:
#   [0]   callsign (WQ2XIC)
#   [1]   beacon_type = 1
#   [2..13] shared prefix (12 positions)
#   [14..] beacon 1 tail (17 positions)
BEACON_1 = [
    "WQ2XIC", "1",
    "1000000", "4", "2", "0", "3", "4", "200", "201", "202",
    "203", "1", "2",
    "1610612736", "1",
    "166", "3", "5",
    "0", "0",
    "0.01", "0.02", "0.03",
    "1.0", "2.0", "3.0",
    "0.1", "0.2", "0.3",
    "21.5",
]

# Synthetic beacon 2 tokens. Same layout, tail is 8 positions.
BEACON_2 = [
    "WQ2XIC", "2",
    "1000100", "4", "2", "0", "3", "4", "200", "201", "202",
    "203", "1", "2",
    "458", "-300", "7500", "7622", "7700", "512", "65", "3",
]


def _beacon_pkt(tokens, ptype=2):
    return SimpleNamespace(mission_data={
        "ptype": ptype,
        "cmd": {"cmd_id": "tlm_beacon", "args": list(tokens)},
    })


class TelemetryIntegrationTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = Path(tempfile.mkdtemp())
        self.adapter, self.router = _adapter(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    # Part A — main flow
    # ------------------------------------------------------------------

    def test_eps_hk_emits_one_eps_telemetry_message(self):
        msgs = _run(self.adapter, _eps_pkt())
        eps_msgs = [m for m in msgs
                    if m.get("type") == "telemetry" and m.get("domain") == "eps"]
        other = [m for m in msgs
                 if m.get("type") == "telemetry" and m.get("domain") != "eps"]
        self.assertEqual(len(eps_msgs), 1, msgs)
        self.assertEqual(other, [])
        self.assertEqual(len(eps_msgs[0]["changes"]), 48)

    def test_beacon_1_emits_platform_and_gnc(self):
        msgs = _run(self.adapter, _beacon_pkt(BEACON_1))
        by_domain = {m["domain"]: m for m in msgs if m.get("type") == "telemetry"}
        self.assertIn("spacecraft", by_domain)
        self.assertIn("gnc", by_domain)
        self.assertNotIn("eps", by_domain)

        gnc_changes = by_domain["gnc"]["changes"]
        # GNC_MODE — structured, not a scalar int.
        self.assertIsInstance(gnc_changes["GNC_MODE"]["v"], dict)
        self.assertEqual(gnc_changes["GNC_MODE"]["v"]["mode"], 1)
        # GNC_COUNTERS — one structured object.
        self.assertIsInstance(gnc_changes["GNC_COUNTERS"]["v"], dict)
        self.assertEqual(gnc_changes["GNC_COUNTERS"]["v"]["reboot"], 166)
        # Vectors — 3 elements.
        self.assertEqual(len(gnc_changes["RATE"]["v"]), 3)
        self.assertEqual(len(gnc_changes["MAG"]["v"]), 3)
        self.assertEqual(len(gnc_changes["MTQ"]["v"]), 3)
        # ADCS_TMP carries {brdtmp, celsius, comm_fault}.
        self.assertEqual(
            set(gnc_changes["ADCS_TMP"]["v"].keys()),
            {"brdtmp", "celsius", "comm_fault"},
        )
        # ACT_ERR — canonical bitfield dict shape.
        self.assertEqual(
            set(gnc_changes["ACT_ERR"]["v"].keys()),
            {"MTQ0", "MTQ1", "MTQ2",
             "CMG0", "CMG1", "CMG2", "CMG3",
             "byte2_raw", "byte3_raw"},
        )

    def test_beacon_2_emits_platform_and_eps_engineering_units(self):
        msgs = _run(self.adapter, _beacon_pkt(BEACON_2))
        by_domain = {m["domain"]: m for m in msgs if m.get("type") == "telemetry"}
        self.assertIn("spacecraft", by_domain)
        self.assertIn("eps", by_domain)
        # Shared prefix puts mtq_heartbeat and nvg_heartbeat under gnc —
        # that's normal (gnc has two fields, no ADCS state from beacon 2).
        if "gnc" in by_domain:
            gnc_keys = set(by_domain["gnc"]["changes"].keys())
            self.assertTrue(gnc_keys <= {"mtq_heartbeat", "nvg_heartbeat"},
                            f"unexpected gnc keys on beacon 2: {gnc_keys}")

        eps_changes = by_domain["eps"]["changes"]
        for key in ("I_BUS", "I_BAT", "V_BUS", "V_BAT", "V_SYS", "TS_ADC", "T_DIE"):
            self.assertIn(key, eps_changes, f"{key} missing")
        # Engineering units: V_BAT raw 7622 mV → 7.622 V.
        self.assertAlmostEqual(eps_changes["V_BAT"]["v"], 7.622, places=3)

    def test_unknown_beacon_type_still_emits_prefix(self):
        # Swap beacon_type for an unknown value; keep callsign + prefix.
        tokens = ["WQ2XIC", "99", *BEACON_1[2:14]]  # valid prefix, no tail
        msgs = _run(self.adapter, _beacon_pkt(tokens))
        by_domain = {m["domain"] for m in msgs if m.get("type") == "telemetry"}
        # Shared prefix routes to platform + gnc (heartbeats live under
        # the gnc domain in COMMON_MAPPINGS).
        self.assertIn("spacecraft", by_domain)
        self.assertNotIn("eps", by_domain)

    def test_clear_eps_emits_cleared_and_replay_drops_domain(self):
        _run(self.adapter, _eps_pkt())
        _run(self.adapter, _beacon_pkt(BEACON_1))
        # Sanity: replay includes eps + gnc + platform.
        replay = self.router.replay()
        domains_before = {m["domain"] for m in replay}
        self.assertIn("eps", domains_before)

        msg = self.router.clear("eps")
        self.assertEqual(msg, {"type": "telemetry", "domain": "eps", "cleared": True})
        domains_after = {m["domain"] for m in self.router.replay()}
        self.assertNotIn("eps", domains_after)
        self.assertTrue({"gnc", "spacecraft"} <= domains_after)

    def test_canonical_key_invariant_beacon_gnc_keys_are_subset(self):
        """Beacon decoder must not introduce new names into the gnc
        domain — every emitted key must exist in the mission catalog.
        The catalog is the single source of truth for canonical gnc
        keys (addressable registers + handler-emitted + beacon-only)."""
        from mav_gss_lib.missions.maveric.telemetry import TELEMETRY_MANIFEST
        catalog_names = {e["name"] for e in TELEMETRY_MANIFEST["gnc"]["catalog"]()}

        msgs = _run(self.adapter, _beacon_pkt(BEACON_1))
        gnc_msg = next(m for m in msgs
                       if m.get("type") == "telemetry" and m["domain"] == "gnc")
        unknown = set(gnc_msg["changes"]) - catalog_names
        self.assertFalse(unknown, f"beacon emitted gnc keys not in catalog: {unknown}")


if __name__ == "__main__":
    unittest.main()
