"""Tests that the platform boundary works with a non-MAVERIC mission.

These tests prove:
  1. EchoMissionAdapter satisfies MissionAdapter Protocol
  2. validate_adapter() accepts it
  3. RxPipeline processes packets through the echo adapter
  4. Rendering-slot methods produce valid output
  5. The transitional JSON methods produce valid output
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.mission_adapter import (
    MissionAdapter,
    ParsedPacket,
    validate_adapter,
)
from mav_gss_lib.parsing import RxPipeline
from tests.echo_mission import EchoMissionAdapter, ADAPTER_API_VERSION


class TestMissionBoundary(unittest.TestCase):
    """Verify the platform works with a non-MAVERIC mission adapter."""

    def setUp(self):
        self.adapter = EchoMissionAdapter(cmd_defs={})

    def test_echo_adapter_satisfies_protocol(self):
        """EchoMissionAdapter passes isinstance check against MissionAdapter."""
        self.assertIsInstance(self.adapter, MissionAdapter)

    def test_validate_adapter_accepts_echo(self):
        """validate_adapter() does not raise for a conforming echo adapter."""
        validate_adapter(self.adapter, ADAPTER_API_VERSION, "echo")

    def test_validate_adapter_rejects_bad_version(self):
        """validate_adapter() raises ValueError for unsupported API version."""
        with self.assertRaises(ValueError) as ctx:
            validate_adapter(self.adapter, 99, "echo")
        self.assertIn("ADAPTER_API_VERSION=99", str(ctx.exception))

    def test_validate_adapter_rejects_non_adapter(self):
        """validate_adapter() raises ValueError for an object missing methods."""
        with self.assertRaises(ValueError) as ctx:
            validate_adapter(object(), 1, "fake")
        self.assertIn("does not satisfy", str(ctx.exception))

    def test_echo_adapter_renders_columns(self):
        """packet_list_columns() returns a non-empty list of column defs."""
        cols = self.adapter.packet_list_columns()
        self.assertGreater(len(cols), 0)
        ids = [c["id"] for c in cols]
        self.assertIn("num", ids)
        self.assertIn("size", ids)

    def test_echo_adapter_renders_row(self):
        """packet_list_row() returns values keyed by column IDs."""

        class MockPkt:
            pkt_num = 1
            gs_ts_short = "10:30:00"
            gs_ts = "2026-04-06T10:30:00"
            raw = b"\xDE\xAD\xBE\xEF"
            is_dup = False
            is_unknown = True
            is_uplink_echo = False
            warnings = []

        row = self.adapter.packet_list_row(MockPkt())
        self.assertIn("values", row)
        self.assertEqual(row["values"]["num"], 1)
        self.assertEqual(row["values"]["size"], 4)
        self.assertEqual(row["values"]["hex"], "deadbeef")

    def test_echo_adapter_renders_detail_blocks(self):
        """packet_detail_blocks() returns at least one block with fields."""

        class MockPkt:
            pkt_num = 1
            gs_ts_short = "10:30:00"
            gs_ts = "2026-04-06T10:30:00"
            raw = b"\xCA\xFE"
            is_dup = False
            is_unknown = True
            is_uplink_echo = False
            warnings = []

        blocks = self.adapter.packet_detail_blocks(MockPkt())
        self.assertGreater(len(blocks), 0)
        self.assertEqual(blocks[0]["kind"], "raw")
        self.assertIn("fields", blocks[0])

    def test_echo_adapter_no_protocol_or_integrity_blocks(self):
        """Echo mission has no protocol/integrity -- returns empty lists."""

        class MockPkt:
            pkt_num = 1
            gs_ts_short = "10:30:00"
            raw = b"\x00"
            is_dup = False
            is_unknown = True
            is_uplink_echo = False
            warnings = []
            csp = None
            stripped_hdr = None
            crc_status = {}
            cmd = None

        self.assertEqual(self.adapter.protocol_blocks(MockPkt()), [])
        self.assertEqual(self.adapter.integrity_blocks(MockPkt()), [])

    def test_rx_pipeline_with_echo_adapter(self):
        """RxPipeline processes a raw PDU through the echo adapter."""
        pipeline = RxPipeline(self.adapter, tx_freq_map={})
        meta = {"transmitter": "raw test"}
        raw = b"\x01\x02\x03\x04"
        pkt = pipeline.process(meta, raw)
        self.assertEqual(pkt.pkt_num, 1)
        self.assertEqual(pkt.raw, raw)
        self.assertEqual(pkt.frame_type, "RAW")

    def test_echo_packet_to_json(self):
        """Transitional packet_to_json() produces valid JSON shape."""

        class MockPkt:
            pkt_num = 1
            gs_ts_short = "10:30:00"
            gs_ts = "2026-04-06T10:30:00"
            frame_type = "RAW"
            raw = b"\xAB\xCD"
            is_dup = False
            is_unknown = True
            is_uplink_echo = False
            warnings = []
            csp = None
            stripped_hdr = None
            crc_status = {}
            cmd = None
            ts_result = None

        result = self.adapter.packet_to_json(MockPkt())
        self.assertEqual(result["num"], 1)
        self.assertEqual(result["frame"], "RAW")
        self.assertEqual(result["raw_hex"], "abcd")
        self.assertIn("_rendering", result)
        self.assertIn("row", result["_rendering"])


if __name__ == "__main__":
    unittest.main()
