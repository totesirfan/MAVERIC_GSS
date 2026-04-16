"""Tests for MAVERIC EPS HK telemetry decoder + framework integration."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.missions.maveric.telemetry.types import TelemetryField


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


from mav_gss_lib.missions.maveric.telemetry.eps import decode_eps_hk
from mav_gss_lib.missions.maveric.wire_format import try_parse_command


PAYLOAD_HEX = (
    "900600000206000406606570735f686b00b4000000e823220088266c"
    "1d2c2134023f00f50c8c00f40176132600c8000000feff00000000fe"
    "ff00000000feff00000000feff00000000000000000000feff000000"
    "00feff00000000feff00000000feff00000000000000000000feff00"
    "0000c95d1cfcc76f"
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


from mav_gss_lib.missions.maveric.telemetry import decode_telemetry


class TestRegistryDispatch(unittest.TestCase):

    def _eps_cmd(self):
        cmd = _parse_fixture_cmd()
        return cmd  # has cmd_id=eps_hk, pkt_type=4 (TLM), args_raw=96 bytes

    def test_dispatch_returns_dict_shape(self):
        result = decode_telemetry(self._eps_cmd())
        self.assertIsInstance(result, dict)
        self.assertEqual(result["cmd_id"], "eps_hk")
        self.assertEqual(len(result["fields"]), 48)
        self.assertTrue(result["hide_schema_args"])

    def test_dispatch_fields_are_plain_dicts(self):
        result = decode_telemetry(self._eps_cmd())
        first = result["fields"][0]
        self.assertIsInstance(first, dict)
        self.assertEqual(set(first.keys()), {"name", "value", "unit"})

    def test_dispatch_returns_none_for_unknown_cmd(self):
        self.assertIsNone(
            decode_telemetry({"cmd_id": "other", "pkt_type": 4, "args_raw": b""})
        )

    def test_dispatch_returns_none_for_wrong_pkt_type(self):
        cmd = self._eps_cmd()
        cmd_cmd = {**cmd, "pkt_type": 2}
        self.assertIsNone(decode_telemetry(cmd_cmd))


from ops_test_support import CMD_DEFS  # noqa: E402
from mav_gss_lib.missions.maveric import rx_ops  # noqa: E402


class TestParsePacketAttachesTelemetry(unittest.TestCase):

    def test_eps_hk_payload_attaches_telemetry(self):
        raw = bytes.fromhex(PAYLOAD_HEX)
        parsed = rx_ops.parse_packet(raw, CMD_DEFS)
        tel = parsed.mission_data.get("telemetry")
        self.assertIsNotNone(tel, "telemetry block missing from mission_data")
        self.assertEqual(tel["cmd_id"], "eps_hk")
        self.assertEqual(len(tel["fields"]), 48)
        self.assertTrue(tel["hide_schema_args"])
        by_name = {f["name"]: f["value"] for f in tel["fields"]}
        self.assertAlmostEqual(by_name["V_BAT"], 7.532, places=6)
        self.assertAlmostEqual(by_name["V_BUS"], 9.192, places=6)

    def test_non_telemetry_packet_sets_none(self):
        from mav_gss_lib.missions.maveric.wire_format import build_cmd_raw
        cmd_bytes = bytes(build_cmd_raw(6, 2, "com_ping", "", echo=0, ptype=1))
        csp_hdr = b"\x90\x06\x00\x00"
        parsed = rx_ops.parse_packet(csp_hdr + cmd_bytes, CMD_DEFS)
        self.assertIsNone(parsed.mission_data.get("telemetry"))


from ops_test_support import NODES  # noqa: E402
from mav_gss_lib.missions.maveric.adapter import MavericMissionAdapter  # noqa: E402
from mav_gss_lib.parsing import Packet  # noqa: E402


def _make_pkt_from_payload(payload_hex: str) -> Packet:
    """Build a minimal Packet whose mission_data comes from rx_ops."""
    raw = bytes.fromhex(payload_hex)
    parsed = rx_ops.parse_packet(raw, CMD_DEFS)
    return Packet(
        pkt_num=1,
        gs_ts="2026-04-14 18:21:09 PDT",
        gs_ts_short="18:21:09",
        frame_type="ASM+GOLAY",
        raw=raw,
        inner_payload=raw,
        mission_data=parsed.mission_data,
    )


class TestDetailBlocksReplayContract(unittest.TestCase):

    def setUp(self):
        self.adapter = MavericMissionAdapter(cmd_defs=CMD_DEFS, nodes=NODES)
        self.pkt = _make_pkt_from_payload(PAYLOAD_HEX)

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
        self.pkt = _make_pkt_from_payload(PAYLOAD_HEX)

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
