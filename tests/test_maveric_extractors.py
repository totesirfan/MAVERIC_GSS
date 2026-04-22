"""Tests for mission extractor modules.

Each extractor reads a parsed packet's mission_data and yields
TelemetryFragment objects. Extractors must gate by cmd_id + ptype and
must tolerate malformed payloads without raising.
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
        ptype_names={0: "CMD", 1: "ACK", 2: "TLM", 3: "RES", 4: "FILE"},
        ptype_ids={"CMD": 0, "ACK": 1, "TLM": 2, "RES": 3, "FILE": 4},
        gs_node=0,
    )


def _pkt(ptype_id: int, cmd_id: str, args_raw: bytes | None = None):
    cmd: dict = {"cmd_id": cmd_id}
    if args_raw is not None:
        cmd["args_raw"] = args_raw
    return SimpleNamespace(mission_data={"ptype": ptype_id, "cmd": cmd})


class TestEpsHkExtractor(unittest.TestCase):
    def setUp(self) -> None:
        from mav_gss_lib.missions.maveric.telemetry.extractors.eps_hk import extract
        self.extract = extract
        self.nodes = _make_nodes()
        self.args_raw = _load_hex(FIXTURES / "packet.hex")

    def test_valid_tlm_packet_yields_48_fragments_with_units(self):
        pkt = _pkt(ptype_id=2, cmd_id="eps_hk", args_raw=self.args_raw)
        frags = list(self.extract(pkt, self.nodes, now_ms=12345))

        self.assertEqual(len(frags), 48)
        # Every fragment carries domain, ts_ms, and the canonical unit.
        for f in frags:
            self.assertEqual(f.domain, "eps")
            self.assertEqual(f.ts_ms, 12345)

        units = {f.key: f.unit for f in frags}
        # Unit table coverage — spot-check each scaling bucket.
        self.assertEqual(units["V_BAT"], "V")
        self.assertEqual(units["I_BAT"], "A")
        self.assertEqual(units["P3V3"], "W")
        self.assertEqual(units["TS_ADC"], "%")
        self.assertEqual(units["T_DIE"], "°C")

    def test_non_tlm_ptype_yields_nothing(self):
        for ptype in (0, 1, 3, 4):  # CMD, ACK, RES, FILE
            pkt = _pkt(ptype_id=ptype, cmd_id="eps_hk", args_raw=self.args_raw)
            self.assertEqual(list(self.extract(pkt, self.nodes, 0)), [],
                             msg=f"ptype={ptype} should not emit")

    def test_wrong_cmd_id_yields_nothing(self):
        pkt = _pkt(ptype_id=2, cmd_id="gnc_get_mode", args_raw=self.args_raw)
        self.assertEqual(list(self.extract(pkt, self.nodes, 0)), [])

    def test_missing_args_raw_yields_nothing(self):
        pkt = _pkt(ptype_id=2, cmd_id="eps_hk", args_raw=None)
        self.assertEqual(list(self.extract(pkt, self.nodes, 0)), [])

    def test_short_args_raw_yields_nothing(self):
        pkt = _pkt(ptype_id=2, cmd_id="eps_hk", args_raw=b"\x00" * 10)
        self.assertEqual(list(self.extract(pkt, self.nodes, 0)), [])

    def test_extractor_does_not_read_mission_data_telemetry(self):
        """Extractor must call decode_eps_hk directly, not consume a
        pre-populated mission_data['telemetry'] key (which Task 10a deletes).

        Scans the compiled constants + names rather than the source text so
        the docstring is ignored.
        """
        from mav_gss_lib.missions.maveric.telemetry.extractors import eps_hk
        consts = set(eps_hk.extract.__code__.co_consts)
        names = set(eps_hk.extract.__code__.co_names) | set(
            eps_hk.extract.__code__.co_varnames
        )
        self.assertNotIn("telemetry", consts,
                         "extractor must not subscript mission_data['telemetry']")
        # `fragments`/`gnc_registers` likewise must not appear as literal keys.
        self.assertNotIn("gnc_registers", consts)


def _typed_cmd(cmd_id: str, *values: str) -> dict:
    typed = [{"name": f"a{i}", "type": "str", "value": v}
             for i, v in enumerate(values)]
    return {"cmd_id": cmd_id, "typed_args": typed, "extra_args": []}


def _pkt_with_cmd(ptype_id: int, cmd: dict):
    return SimpleNamespace(mission_data={"ptype": ptype_id, "cmd": cmd})


class TestGncResExtractor(unittest.TestCase):
    def setUp(self) -> None:
        from mav_gss_lib.missions.maveric.telemetry.extractors.gnc_res import extract
        self.extract = extract
        self.nodes = _make_nodes()

    def test_gnc_get_mode_yields_one_fragment(self):
        cmd = _typed_cmd("gnc_get_mode", "1")
        pkt = _pkt_with_cmd(ptype_id=3, cmd=cmd)  # RES
        frags = list(self.extract(pkt, self.nodes, now_ms=99))

        self.assertEqual(len(frags), 1)
        f = frags[0]
        self.assertEqual(f.domain, "gnc")
        self.assertEqual(f.key, "GNC_MODE")
        self.assertEqual(f.ts_ms, 99)
        # GNC_MODE is a structured value (no scalar unit).
        self.assertEqual(f.unit, "")
        self.assertIsInstance(f.value, dict)
        self.assertEqual(f.value["mode"], 1)

    def test_gnc_get_cnts_yields_one_counters_fragment(self):
        cmd = _typed_cmd("gnc_get_cnts", "3", "2", "1")
        pkt = _pkt_with_cmd(ptype_id=3, cmd=cmd)
        frags = list(self.extract(pkt, self.nodes, now_ms=0))

        self.assertEqual(len(frags), 1)
        f = frags[0]
        self.assertEqual(f.key, "GNC_COUNTERS")
        self.assertIsInstance(f.value, dict)
        self.assertEqual(f.value["reboot"], 3)
        self.assertEqual(f.value["detumble"], 2)
        self.assertEqual(f.value["sunspin"], 1)

    def test_non_res_ptype_yields_nothing(self):
        cmd = _typed_cmd("gnc_get_mode", "1")
        for ptype in (0, 1, 2, 4):  # CMD, ACK, TLM, FILE
            pkt = _pkt_with_cmd(ptype_id=ptype, cmd=cmd)
            self.assertEqual(list(self.extract(pkt, self.nodes, 0)), [],
                             msg=f"ptype={ptype} should not emit")

    def test_unregistered_cmd_yields_nothing(self):
        pkt = _pkt_with_cmd(ptype_id=3, cmd=_typed_cmd("no_such_cmd"))
        self.assertEqual(list(self.extract(pkt, self.nodes, 0)), [])

    def test_decode_failed_entries_are_dropped(self):
        # gnc_get_mode with a non-integer arg → handler returns None →
        # extractor emits nothing. Exercises the decode_ok gate indirectly
        # (the full handler returns None on bad input, which is treated
        # the same as decode_ok=False by the extractor).
        cmd = _typed_cmd("gnc_get_mode", "not-a-number")
        pkt = _pkt_with_cmd(ptype_id=3, cmd=cmd)
        self.assertEqual(list(self.extract(pkt, self.nodes, 0)), [])

    def test_extractor_does_not_read_mission_data_gnc_registers(self):
        from mav_gss_lib.missions.maveric.telemetry.extractors import gnc_res
        consts = set(gnc_res.extract.__code__.co_consts)
        self.assertNotIn("gnc_registers", consts,
                         "extractor must not subscript mission_data['gnc_registers']")
        self.assertNotIn("telemetry", consts)


if __name__ == "__main__":
    unittest.main()
