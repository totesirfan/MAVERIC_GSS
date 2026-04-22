"""EPS HK adapter tests — decoder round-trip + ptype-gated emission.

Consumes ``docs/eps-port/fixtures/packet.hex`` (synthetic 96-byte args_raw)
and ``docs/eps-port/fixtures/decoded.json`` (expected engineering values).

Covers:
  * ``decode_eps_hk`` produces the expected 48-field dict for the golden
    packet (tolerance-aware float comparison).
  * ``MavericMissionAdapter.on_packet_received`` emits exactly one
    ``eps_hk_update`` for ptype TLM responses.
  * ``on_packet_received`` does NOT emit ``eps_hk_update`` for CMD
    echoes or ACK frames (same args slot, no real telemetry).
  * ``on_client_connect`` replays the current store as a synthetic
    ``eps_hk_update`` with ``replay = True`` so consumers can skip
    link counters.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

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


def _make_packet(ptype_id: int, pkt_num: int, fields_list: list[dict]):
    from mav_gss_lib.parsing import Packet
    return Packet(
        pkt_num=pkt_num,
        mission_data={
            "ptype": ptype_id,
            "cmd": {"cmd_id": "eps_hk"},
            "telemetry": {"cmd_id": "eps_hk", "fields": fields_list},
        },
    )


class TestEpsDecoderFixture(unittest.TestCase):
    def setUp(self) -> None:
        from mav_gss_lib.missions.maveric.telemetry.semantics.eps import decode_eps_hk
        self.decode_eps_hk = decode_eps_hk
        self.args_raw = _load_hex(FIXTURES / "packet.hex")
        self.expected = json.loads((FIXTURES / "decoded.json").read_text())

    def test_packet_size_is_96_bytes(self) -> None:
        self.assertEqual(len(self.args_raw), 96)

    def test_decoder_matches_golden_fields(self) -> None:
        fields = self.decode_eps_hk({"args_raw": self.args_raw})
        self.assertEqual(len(fields), 48)
        got = {f.name: f.value for f in fields}
        want = self.expected["fields"]
        self.assertEqual(set(got.keys()), set(want.keys()))
        # Tolerance is display-precision from fields.json (+ 1 decimal for margin).
        manifest = json.loads(
            (ROOT / "docs" / "eps-port" / "eps_fields.json").read_text()
        )
        digits_by_name = {f["name"]: f["digits"] for f in manifest["fields"]}
        for name, expected_value in want.items():
            places = digits_by_name.get(name, 3)
            self.assertAlmostEqual(
                got[name], expected_value, places=places,
                msg=f"field {name}: got {got[name]}, want {expected_value}",
            )


class TestAdapterPtypeGating(unittest.TestCase):
    """The EPS branch of on_packet_received must only fire for TLM frames."""

    def setUp(self) -> None:
        from mav_gss_lib.missions.maveric.adapter import MavericMissionAdapter
        from mav_gss_lib.missions.maveric.telemetry.semantics.eps import decode_eps_hk
        from mav_gss_lib.missions.maveric.telemetry.eps_store import EpsStore

        self._tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self._tmp.close()
        self.store = EpsStore(Path(self._tmp.name))
        self.store.clear()
        self.adapter = MavericMissionAdapter(
            cmd_defs={},
            nodes=_make_nodes(),
            eps_store=self.store,
        )
        self.args_raw = _load_hex(FIXTURES / "packet.hex")
        self.expected = json.loads((FIXTURES / "decoded.json").read_text())
        self.fields_list = [f.to_dict() for f in decode_eps_hk({"args_raw": self.args_raw})]

    def tearDown(self) -> None:
        try:
            Path(self._tmp.name).unlink()
        except OSError:
            pass

    def test_tlm_emits_eps_hk_update(self) -> None:
        pkt = _make_packet(ptype_id=2, pkt_num=7, fields_list=self.fields_list)
        msgs = self.adapter.on_packet_received(pkt) or []
        eps_msgs = [m for m in msgs if m.get("type") == "eps_hk_update"]
        self.assertEqual(len(eps_msgs), 1, f"expected one eps_hk_update, got {msgs}")
        msg = eps_msgs[0]
        self.assertEqual(msg["pkt_num"], 7)
        self.assertIn("received_at_ms", msg)
        self.assertIsInstance(msg["fields"], dict)
        self.assertAlmostEqual(msg["fields"]["V_BUS"], self.expected["fields"]["V_BUS"], places=4)

    def test_cmd_does_not_emit(self) -> None:
        pkt = _make_packet(ptype_id=0, pkt_num=8, fields_list=self.fields_list)
        msgs = self.adapter.on_packet_received(pkt) or []
        eps_msgs = [m for m in msgs if m.get("type") == "eps_hk_update"]
        self.assertEqual(eps_msgs, [], "CMD echoes must not emit eps_hk_update")

    def test_ack_does_not_emit(self) -> None:
        pkt = _make_packet(ptype_id=1, pkt_num=9, fields_list=self.fields_list)
        msgs = self.adapter.on_packet_received(pkt) or []
        eps_msgs = [m for m in msgs if m.get("type") == "eps_hk_update"]
        self.assertEqual(eps_msgs, [], "ACK frames must not emit eps_hk_update")


class TestAdapterClientConnectReplay(unittest.TestCase):
    def setUp(self) -> None:
        from mav_gss_lib.missions.maveric.adapter import MavericMissionAdapter
        from mav_gss_lib.missions.maveric.telemetry.eps_store import EpsStore

        self._tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self._tmp.close()
        self.store = EpsStore(Path(self._tmp.name))
        self.store.clear()
        self.adapter = MavericMissionAdapter(
            cmd_defs={},
            nodes=_make_nodes(),
            eps_store=self.store,
        )

    def tearDown(self) -> None:
        try:
            Path(self._tmp.name).unlink()
        except OSError:
            pass

    def test_replay_empty_store_emits_nothing(self) -> None:
        msgs = self.adapter.on_client_connect()
        eps_msgs = [m for m in msgs if m.get("type") == "eps_hk_update"]
        self.assertEqual(eps_msgs, [])

    def test_replay_populated_store_emits_with_replay_flag(self) -> None:
        self.store.update({
            "received_at_ms": 123456789,
            "pkt_num": 42,
            "fields": {"V_BUS": 8.744, "I_BUS": 0.458},
        })
        msgs = self.adapter.on_client_connect()
        eps_msgs = [m for m in msgs if m.get("type") == "eps_hk_update"]
        self.assertEqual(len(eps_msgs), 1)
        msg = eps_msgs[0]
        self.assertEqual(msg["received_at_ms"], 123456789)
        self.assertEqual(msg["pkt_num"], 42)
        self.assertTrue(msg.get("replay"))
        self.assertEqual(msg["fields"]["V_BUS"], 8.744)


if __name__ == "__main__":
    unittest.main(verbosity=2)
