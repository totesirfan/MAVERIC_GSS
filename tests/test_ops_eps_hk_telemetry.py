"""Tests for MAVERIC EPS HK telemetry decoder + framework integration."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.missions.maveric.telemetry.semantics.types import TelemetryField


class TestTelemetryField(unittest.TestCase):

    def test_field_construction(self):
        f = TelemetryField(name="V_BUS", value=9192, unit="", raw=9192)
        self.assertEqual(f.name, "V_BUS")
        self.assertEqual(f.value, 9192)
        self.assertEqual(f.unit, "")
        self.assertEqual(f.raw, 9192)

    def test_to_dict_omits_raw(self):
        f = TelemetryField(name="V_BUS", value=9192, unit="", raw=9192)
        d = f.to_dict()
        self.assertEqual(d, {"name": "V_BUS", "value": 9192, "unit": ""})
        self.assertNotIn("raw", d)

    def test_field_is_frozen(self):
        f = TelemetryField(name="X", value=1, unit="", raw=1)
        with self.assertRaises(Exception):  # FrozenInstanceError
            f.value = 2  # type: ignore


from mav_gss_lib.missions.maveric.telemetry.semantics.eps import decode_eps_hk
from mav_gss_lib.missions.maveric.wire_format import try_parse_command


PAYLOAD_HEX = (
    "900600000206000506606570735f686b00b4000000e823220088266c"
    "1d2c2134023f00f50c8c00f40176132600c8000000feff00000000fe"
    "ff00000000feff00000000feff00000000000000000000feff000000"
    "00feff00000000feff00000000feff00000000000000000000feff00"
    "0000050f079ba7a4"
)

GOLDEN_VALUES = {
    "I_BUS": 0.18, "I_BAT": 0.0, "V_BUS": 9.192, "V_AC1": 0.034, "V_AC2": 9.864,
    "V_BAT": 7.532, "V_SYS": 8.492, "TS_ADC": 55.078153, "T_DIE": 31.5,
    "V3V3": 3.317, "I3V3": 0.14, "P3V3": 0.5,
    "V5V0": 4.982, "I5V0": 0.038, "P5V0": 0.2,
}

GOLDEN_UNITS = {
    "I_BUS": "A", "I_BAT": "A", "V_BUS": "V", "V_AC1": "V", "V_AC2": "V",
    "V_BAT": "V", "V_SYS": "V", "TS_ADC": "%", "T_DIE": "°C",
    "V3V3": "V", "I3V3": "A", "P3V3": "W",
    "V5V0": "V", "I5V0": "A", "P5V0": "W",
}


def _parse_fixture_cmd():
    """Parse PAYLOAD_HEX into the cmd dict the decoder expects.

    try_parse_command expects the command frame with CSP header already
    stripped, so slice [4:] to skip the 4-byte CSP v1 header.
    """
    raw = bytes.fromhex(PAYLOAD_HEX)
    cmd, _tail = try_parse_command(raw[4:])
    return cmd


class TestDecodeEpsHk(unittest.TestCase):

    def test_from_log_payload(self):
        cmd = _parse_fixture_cmd()
        self.assertEqual(cmd["cmd_id"], "eps_hk")
        fields = decode_eps_hk(cmd)
        self.assertEqual(len(fields), 48)
        by_name = {f.name: f.value for f in fields}
        for name, expected in GOLDEN_VALUES.items():
            self.assertAlmostEqual(by_name[name], expected, places=6,
                                   msg=f"{name} mismatch")

    def test_units_populated_per_field_kind(self):
        cmd = _parse_fixture_cmd()
        fields = decode_eps_hk(cmd)
        by_name = {f.name: f.unit for f in fields}
        for name, expected_unit in GOLDEN_UNITS.items():
            self.assertEqual(by_name[name], expected_unit,
                             f"{name}: unit mismatch")

    def test_raw_preserved_alongside_scaled_value(self):
        cmd = _parse_fixture_cmd()
        fields = decode_eps_hk(cmd)
        by_name = {f.name: f for f in fields}
        self.assertEqual(by_name["V_BAT"].raw, 7532)
        self.assertAlmostEqual(by_name["V_BAT"].value, 7.532, places=6)
        self.assertEqual(by_name["T_DIE"].raw, 63)
        self.assertAlmostEqual(by_name["T_DIE"].value, 31.5, places=6)

    def test_short_payload_raises(self):
        with self.assertRaises(ValueError):
            decode_eps_hk({"args_raw": b""})
        with self.assertRaises(ValueError):
            decode_eps_hk({"args_raw": b"\x00" * 95})

    def test_trailing_bytes_ignored(self):
        cmd = _parse_fixture_cmd()
        padded = {**cmd, "args_raw": cmd["args_raw"] + b"\x00\x00\x00\x00"}
        fields = decode_eps_hk(padded)
        self.assertEqual(len(fields), 48)
        by_name = {f.name: f.value for f in fields}
        self.assertAlmostEqual(by_name["V_BAT"], 7.532, places=6)


from ops_test_support import CMD_DEFS  # noqa: E402
from mav_gss_lib.missions.maveric import rx_ops  # noqa: E402


class TestParsePacketDoesNotInjectLegacyKeys(unittest.TestCase):
    """Post-v2: rx_ops.parse_packet stops attaching mission_data['telemetry']
    and ['gnc_registers']. The fragment list is the single per-packet
    decoded payload, and it's populated by the mission adapter's
    attach_fragments hook (rx_service calls it between pipeline.process
    and build_rx_log_record).
    """

    def test_eps_hk_payload_carries_no_legacy_telemetry_key(self):
        raw = bytes.fromhex(PAYLOAD_HEX)
        parsed = rx_ops.parse_packet(raw, CMD_DEFS)
        self.assertNotIn("telemetry", parsed.mission_data)
        self.assertNotIn("gnc_registers", parsed.mission_data)
        # cmd is still there — extractors read args_raw from it.
        self.assertEqual(parsed.mission_data["cmd"]["cmd_id"], "eps_hk")


from ops_test_support import NODES  # noqa: E402
from mav_gss_lib.missions.maveric.adapter import MavericMissionAdapter  # noqa: E402
from mav_gss_lib.missions.maveric.telemetry.extractors import EXTRACTORS  # noqa: E402
from mav_gss_lib.parsing import Packet  # noqa: E402
from mav_gss_lib.web_runtime.telemetry.router import TelemetryRouter  # noqa: E402


def _make_pkt_from_payload(payload_hex: str, adapter=None) -> Packet:
    """Build a Packet from a raw wire payload and run the adapter's
    attach_fragments hook, replicating production rx_service behavior."""
    raw = bytes.fromhex(payload_hex)
    parsed = rx_ops.parse_packet(raw, CMD_DEFS)
    pkt = Packet(
        pkt_num=1,
        gs_ts="2026-04-14 18:21:09 PDT",
        gs_ts_short="18:21:09",
        frame_type="ASM+GOLAY",
        raw=raw,
        inner_payload=raw,
        mission_data=parsed.mission_data,
    )
    if adapter is not None:
        adapter.attach_fragments(pkt)
    return pkt


def _adapter_with_router(tmp_path):
    """Fresh MavericMissionAdapter with a TelemetryRouter wired up.

    Replicates WebRuntime.__init__'s adapter-attachment steps so tests
    can exercise the full attach_fragments → on_packet_received flow.
    """
    adapter = MavericMissionAdapter(cmd_defs=CMD_DEFS, nodes=NODES)
    router = TelemetryRouter(tmp_path / ".telemetry")
    router.register_domain("eps")
    router.register_domain("gnc")
    adapter.telemetry = router
    adapter.extractors = EXTRACTORS
    return adapter


class TestDetailBlocksReplayContract(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = Path(tempfile.mkdtemp())
        self.adapter = _adapter_with_router(self._tmp)
        self.pkt = _make_pkt_from_payload(PAYLOAD_HEX, adapter=self.adapter)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_eps_hk_detail_has_telemetry_block(self):
        blocks = self.adapter.packet_detail_blocks(self.pkt)
        labels = [b.get("label") for b in blocks]
        self.assertIn("EPS_HK", labels, f"blocks were: {labels}")

        hk = next(b for b in blocks if b.get("label") == "EPS_HK")
        self.assertEqual(hk["kind"], "args")
        self.assertEqual(len(hk["fields"]), 48)

        by_name = {f["name"]: f["value"] for f in hk["fields"]}
        self.assertEqual(by_name["V_BAT"], "7.532 V")
        self.assertEqual(by_name["V_BUS"], "9.192 V")

    def test_eps_hk_detail_hides_schema_arguments_block(self):
        blocks = self.adapter.packet_detail_blocks(self.pkt)
        labels = [b.get("label") for b in blocks]
        self.assertNotIn("Arguments", labels,
                         "hide_schema_args=True should suppress the schema Arguments block")

    def test_eps_hk_row_cmd_is_just_cmd_id(self):
        row = self.adapter.packet_list_row(self.pkt)
        self.assertEqual(row["values"]["cmd"], "eps_hk",
                         "hide_schema_args=True should suppress row args string")

    def test_build_rx_log_record_freezes_telemetry_into_rendering(self):
        # Exercises the ACTUAL freeze point in parsing.build_rx_log_record,
        # not just the adapter methods in isolation. If adapter/parsing
        # integration ever regresses at the _rendering write step (e.g. a
        # wrapper changes the dict shape or drops a key), this test fires.
        # Covers the replay boundary end-to-end — what lands in the JSONL
        # is exactly what the log viewer replays.
        from mav_gss_lib.parsing import build_rx_log_record
        record = build_rx_log_record(
            self.pkt,
            version="test",
            meta={"transmitter": "test-fixture"},
            adapter=self.adapter,
        )
        self.assertIn("_rendering", record)
        rendering = record["_rendering"]

        detail_labels = [b.get("label") for b in rendering["detail_blocks"]]
        self.assertIn("EPS_HK", detail_labels,
                      f"frozen detail_blocks were: {detail_labels}")
        self.assertNotIn("Arguments", detail_labels,
                         "frozen detail_blocks must not contain schema Arguments for eps_hk")

        row_cmd = rendering["row"]["values"]["cmd"]
        self.assertEqual(row_cmd, "eps_hk",
                         f"frozen row cmd cell was: {row_cmd!r}")

        hk = next(b for b in rendering["detail_blocks"] if b.get("label") == "EPS_HK")
        by_name = {f["name"]: f["value"] for f in hk["fields"]}
        self.assertEqual(by_name["V_BAT"], "7.532 V")


from mav_gss_lib.missions.maveric import log_format  # noqa: E402


class TestLogFormatTelemetry(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = Path(tempfile.mkdtemp())
        adapter = _adapter_with_router(self._tmp)
        self.pkt = _make_pkt_from_payload(PAYLOAD_HEX, adapter=adapter)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_eps_hk_log_lines_include_hk_fields(self):
        lines = log_format.format_log_lines(self.pkt, NODES)
        text = "\n".join(lines)
        self.assertIn("I_BUS", text)
        self.assertIn("V_BAT", text)
        self.assertIn("V_BUS", text)
        self.assertIn("7.532 V", text)

    def test_eps_hk_log_lines_have_no_arg_plus_rows(self):
        lines = log_format.format_log_lines(self.pkt, NODES)
        for line in lines:
            self.assertNotIn("ARG +", line,
                             f"hide_schema_args=True should drop ARG + lines, got: {line!r}")


if __name__ == "__main__":
    unittest.main()
