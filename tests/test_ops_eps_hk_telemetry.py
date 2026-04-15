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
    "900600000206000206606570735f686b00b4000000e823220088266c"
    "1d2c2134023f00f50c8c00f40176132600c8000000feff00000000fe"
    "ff00000000feff00000000feff00000000000000000000feff000000"
    "00feff00000000feff00000000feff00000000000000000000feff00"
    "000040a33bd839ce"
)

GOLDEN_VALUES = {
    "I_BUS": 180, "I_BAT": 0, "V_BUS": 9192, "V_AC1": 34, "V_AC2": 9864,
    "V_BAT": 7532, "V_SYS": 8492, "TS_ADC": 564, "T_DIE": 63,
    "V3V3": 3317, "I3V3": 140, "P3V3": 500,
    "V5V0": 4982, "I5V0": 38, "P5V0": 200,
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
            self.assertEqual(by_name[name], expected, f"{name} mismatch")

    def test_v1_invariant_value_equals_raw_and_unit_is_empty(self):
        cmd = _parse_fixture_cmd()
        fields = decode_eps_hk(cmd)
        for f in fields:
            self.assertEqual(f.value, f.raw, f"{f.name}: value/raw diverged")
            self.assertEqual(f.unit, "", f"{f.name}: unit should be empty in v1")

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
        self.assertEqual(by_name["V_BAT"], 7532)


from mav_gss_lib.missions.maveric.telemetry import decode_telemetry


class TestRegistryDispatch(unittest.TestCase):

    def _eps_cmd(self):
        cmd = _parse_fixture_cmd()
        return cmd  # has cmd_id=eps_hk, pkt_type=2, args_raw=96 bytes

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
            decode_telemetry({"cmd_id": "other", "pkt_type": 2, "args_raw": b""})
        )

    def test_dispatch_returns_none_for_wrong_pkt_type(self):
        cmd = self._eps_cmd()
        cmd_cmd = {**cmd, "pkt_type": 1}
        self.assertIsNone(decode_telemetry(cmd_cmd))


if __name__ == "__main__":
    unittest.main()
