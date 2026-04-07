"""Tests for platform log envelope and adapter-driven mission logging.

Verifies:
  1. New adapter methods exist on MissionAdapter Protocol
  2. EchoMissionAdapter satisfies updated Protocol
  3. Platform envelope contains stable fields
  4. Adapter mission data is opaque to platform
  5. Adapter text log lines are pre-formatted strings
  6. is_unknown_packet classification is adapter-driven
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.mission_adapter import MissionAdapter, validate_adapter
from tests.echo_mission import EchoMissionAdapter, ADAPTER_API_VERSION


class TestAdapterLoggingMethods(unittest.TestCase):
    """Verify new logging methods on adapters."""

    def setUp(self):
        self.adapter = EchoMissionAdapter(cmd_defs={})

    def test_echo_adapter_still_satisfies_protocol(self):
        """EchoMissionAdapter passes isinstance check with new methods."""
        self.assertIsInstance(self.adapter, MissionAdapter)
        validate_adapter(self.adapter, ADAPTER_API_VERSION, "echo")

    def test_build_log_mission_data_returns_dict(self):
        """build_log_mission_data() returns a dict."""

        class MockPkt:
            pkt_num = 1
            gs_ts = "2026-04-06T10:30:00"
            gs_ts_short = "10:30:00"
            raw = b"\xDE\xAD"
            inner_payload = b"\xDE\xAD"
            frame_type = "RAW"
            is_dup = False
            is_uplink_echo = False
            is_unknown = True
            warnings = []
            csp = None
            cmd = None
            cmd_tail = None
            ts_result = None
            crc_status = {}
            stripped_hdr = None
            csp_plausible = False

        result = self.adapter.build_log_mission_data(MockPkt())
        self.assertIsInstance(result, dict)

    def test_format_log_lines_returns_list_of_strings(self):
        """format_log_lines() returns a list of strings."""

        class MockPkt:
            pkt_num = 1
            gs_ts = "2026-04-06T10:30:00"
            gs_ts_short = "10:30:00"
            raw = b"\xDE\xAD"
            inner_payload = b"\xDE\xAD"
            frame_type = "RAW"
            is_dup = False
            is_uplink_echo = False
            is_unknown = True
            warnings = []
            csp = None
            cmd = None
            cmd_tail = None
            ts_result = None
            crc_status = {}
            stripped_hdr = None
            csp_plausible = False

        result = self.adapter.format_log_lines(MockPkt())
        self.assertIsInstance(result, list)
        for item in result:
            self.assertIsInstance(item, str)

    def test_is_unknown_packet_returns_bool(self):
        """is_unknown_packet() returns a bool."""
        from mav_gss_lib.mission_adapter import ParsedPacket
        parsed = ParsedPacket()
        result = self.adapter.is_unknown_packet(parsed)
        self.assertIsInstance(result, bool)

    def test_echo_adapter_unknown_is_always_true(self):
        """Echo mission has no command parsing — all packets are unknown."""
        from mav_gss_lib.mission_adapter import ParsedPacket
        parsed = ParsedPacket()
        self.assertTrue(self.adapter.is_unknown_packet(parsed))

    def test_echo_adapter_mission_data_is_empty(self):
        """Echo mission produces empty mission log data."""

        class MockPkt:
            pkt_num = 1
            gs_ts = "2026-04-06T10:30:00"
            gs_ts_short = "10:30:00"
            raw = b"\xDE\xAD"
            inner_payload = b"\xDE\xAD"
            frame_type = "RAW"
            is_dup = False
            is_uplink_echo = False
            is_unknown = True
            warnings = []
            csp = None
            cmd = None
            cmd_tail = None
            ts_result = None
            crc_status = {}
            stripped_hdr = None
            csp_plausible = False

        self.assertEqual(self.adapter.build_log_mission_data(MockPkt()), {})
        self.assertEqual(self.adapter.format_log_lines(MockPkt()), [])


class TestMavericLoggingMethods(unittest.TestCase):
    """Verify MAVERIC adapter produces correct log data."""

    def setUp(self):
        from mav_gss_lib.config import load_gss_config
        from mav_gss_lib.mission_adapter import load_mission_adapter

        cfg = load_gss_config()
        self.adapter = load_mission_adapter(cfg)

    def _make_pkt(self, cmd=None, csp=None, ts_result=None, crc_status=None):
        class MockPkt:
            pass
        pkt = MockPkt()
        pkt.pkt_num = 1
        pkt.gs_ts = "2026-04-06 10:30:00 PDT"
        pkt.gs_ts_short = "10:30:00"
        pkt.frame_type = "AX.25"
        pkt.raw = b"\xDE\xAD\xBE\xEF"
        pkt.inner_payload = b"\xBE\xEF"
        pkt.delta_t = 1.5
        pkt.stripped_hdr = "WM2XBB>WS9XSW"
        pkt.csp = csp
        pkt.csp_plausible = csp is not None
        pkt.cmd = cmd
        pkt.cmd_tail = None
        pkt.ts_result = ts_result
        pkt.crc_status = crc_status or {"csp_crc32_valid": None, "csp_crc32_rx": None, "csp_crc32_comp": None}
        pkt.text = ""
        pkt.warnings = []
        pkt.is_dup = False
        pkt.is_uplink_echo = False
        pkt.is_unknown = cmd is None
        pkt.unknown_num = 1 if cmd is None else None
        return pkt

    def test_mission_data_with_command(self):
        """MAVERIC mission data includes cmd block when command is present."""
        cmd = {
            "src": 6, "dest": 1, "echo": 0, "pkt_type": 2,
            "cmd_id": "com_ping", "crc": 0x1234, "crc_valid": True,
            "args": [], "schema_match": False,
        }
        pkt = self._make_pkt(cmd=cmd)
        data = self.adapter.build_log_mission_data(pkt)
        self.assertIn("cmd", data)
        self.assertEqual(data["cmd"]["cmd_id"], "com_ping")

    def test_mission_data_with_csp(self):
        """MAVERIC mission data includes csp_candidate when CSP is present."""
        csp = {"prio": 2, "src": 0, "dest": 8, "dport": 24, "sport": 0, "flags": 0}
        pkt = self._make_pkt(csp=csp)
        data = self.adapter.build_log_mission_data(pkt)
        self.assertIn("csp_candidate", data)
        self.assertTrue(data["csp_plausible"])

    def test_mission_data_without_command_is_minimal(self):
        """MAVERIC mission data is minimal when no command is parsed."""
        pkt = self._make_pkt()
        data = self.adapter.build_log_mission_data(pkt)
        self.assertNotIn("cmd", data)

    def test_format_log_lines_with_command(self):
        """MAVERIC text log includes command routing and ID lines."""
        cmd = {
            "src": 6, "dest": 1, "echo": 0, "pkt_type": 2,
            "cmd_id": "com_ping", "crc": 0x1234, "crc_valid": True,
            "args": [], "schema_match": False,
        }
        pkt = self._make_pkt(cmd=cmd)
        lines = self.adapter.format_log_lines(pkt)
        self.assertIsInstance(lines, list)
        text = "\n".join(lines)
        self.assertIn("com_ping", text)

    def test_format_log_lines_without_command(self):
        """MAVERIC text log is empty when no command is parsed."""
        pkt = self._make_pkt()
        lines = self.adapter.format_log_lines(pkt)
        # Should still have AX.25 header line (stripped_hdr is set)
        self.assertTrue(any("AX.25 HDR" in line for line in lines))

    def test_is_unknown_packet_with_command(self):
        """MAVERIC: packet with a parsed command is not unknown."""
        from mav_gss_lib.mission_adapter import ParsedPacket
        parsed = ParsedPacket(cmd={"cmd_id": "com_ping"})
        self.assertFalse(self.adapter.is_unknown_packet(parsed))

    def test_is_unknown_packet_without_command(self):
        """MAVERIC: packet without a parsed command is unknown."""
        from mav_gss_lib.mission_adapter import ParsedPacket
        parsed = ParsedPacket()
        self.assertTrue(self.adapter.is_unknown_packet(parsed))


class TestPlatformLogEnvelope(unittest.TestCase):
    """Verify the platform log envelope structure."""

    def setUp(self):
        from mav_gss_lib.config import load_gss_config
        from mav_gss_lib.mission_adapter import load_mission_adapter

        cfg = load_gss_config()
        self.adapter = load_mission_adapter(cfg)

    def _make_pkt(self):
        class MockPkt:
            pass
        pkt = MockPkt()
        pkt.pkt_num = 42
        pkt.gs_ts = "2026-04-06 10:30:00 PDT"
        pkt.gs_ts_short = "10:30:00"
        pkt.frame_type = "AX.25"
        pkt.raw = b"\xDE\xAD\xBE\xEF"
        pkt.inner_payload = b"\xBE\xEF"
        pkt.delta_t = 1.5
        pkt.stripped_hdr = None
        pkt.csp = None
        pkt.csp_plausible = False
        pkt.cmd = None
        pkt.cmd_tail = None
        pkt.ts_result = None
        pkt.crc_status = {"csp_crc32_valid": None, "csp_crc32_rx": None, "csp_crc32_comp": None}
        pkt.text = ""
        pkt.warnings = []
        pkt.is_dup = False
        pkt.is_uplink_echo = False
        pkt.is_unknown = True
        pkt.unknown_num = 1
        return pkt

    def test_envelope_has_stable_platform_fields(self):
        """Platform envelope contains all stable fields."""
        from mav_gss_lib.parsing import build_rx_log_record
        pkt = self._make_pkt()
        record = build_rx_log_record(pkt, "4.3.1", {"transmitter": "UHF"}, self.adapter)
        self.assertEqual(record["v"], "4.3.1")
        self.assertEqual(record["pkt"], 42)
        self.assertEqual(record["gs_ts"], "2026-04-06 10:30:00 PDT")
        self.assertEqual(record["frame_type"], "AX.25")
        self.assertEqual(record["raw_hex"], "deadbeef")
        self.assertEqual(record["payload_hex"], "beef")
        self.assertEqual(record["raw_len"], 4)
        self.assertEqual(record["payload_len"], 2)
        self.assertAlmostEqual(record["delta_t"], 1.5)
        self.assertFalse(record["duplicate"])
        self.assertFalse(record["uplink_echo"])
        self.assertTrue(record["unknown"])

    def test_envelope_has_protocol_and_integrity_blocks(self):
        """Platform envelope includes serialized protocol/integrity blocks."""
        from mav_gss_lib.parsing import build_rx_log_record
        pkt = self._make_pkt()
        pkt.csp = {"prio": 2, "src": 0, "dest": 8, "dport": 24, "sport": 0, "flags": 0}
        pkt.csp_plausible = True
        pkt.is_unknown = False
        pkt.cmd = {
            "src": 6, "dest": 1, "echo": 0, "pkt_type": 2,
            "cmd_id": "com_ping", "crc": 0x1234, "crc_valid": True,
            "args": [], "schema_match": False,
        }
        record = build_rx_log_record(pkt, "4.3.1", {"transmitter": "UHF"}, self.adapter)
        self.assertIn("protocol_blocks", record)
        self.assertIn("integrity_blocks", record)
        self.assertIsInstance(record["protocol_blocks"], list)
        self.assertIsInstance(record["integrity_blocks"], list)

    def test_envelope_has_mission_block(self):
        """Platform envelope contains adapter-provided mission block."""
        from mav_gss_lib.parsing import build_rx_log_record
        pkt = self._make_pkt()
        pkt.cmd = {
            "src": 6, "dest": 1, "echo": 0, "pkt_type": 2,
            "cmd_id": "com_ping", "crc": 0x1234, "crc_valid": True,
            "args": [], "schema_match": False,
        }
        pkt.is_unknown = False
        record = build_rx_log_record(pkt, "4.3.1", {"transmitter": "UHF"}, self.adapter)
        self.assertIn("mission", record)
        self.assertIn("cmd", record["mission"])
        self.assertEqual(record["mission"]["cmd"]["cmd_id"], "com_ping")

    def test_envelope_no_flat_maveric_fields(self):
        """Platform envelope does not contain flat MAVERIC-specific fields at top level."""
        from mav_gss_lib.parsing import build_rx_log_record
        pkt = self._make_pkt()
        pkt.csp = {"prio": 2, "src": 0, "dest": 8, "dport": 24, "sport": 0, "flags": 0}
        pkt.cmd = {
            "src": 6, "dest": 1, "echo": 0, "pkt_type": 2,
            "cmd_id": "com_ping", "crc": 0x1234, "crc_valid": True,
            "args": [], "schema_match": False,
        }
        record = build_rx_log_record(pkt, "4.3.1", {"transmitter": "UHF"}, self.adapter)
        # These were previously at top level — now inside mission block
        self.assertNotIn("csp_candidate", record)
        self.assertNotIn("csp_plausible", record)
        self.assertNotIn("cmd", record)
        self.assertNotIn("sat_ts_ms", record)
        self.assertNotIn("tail_hex", record)


class TestUnknownClassification(unittest.TestCase):
    """Verify adapter-driven unknown packet classification."""

    def test_rx_pipeline_uses_adapter_for_unknown(self):
        """RxPipeline delegates is_unknown to the adapter."""
        from mav_gss_lib.parsing import RxPipeline
        from tests.echo_mission import EchoMissionAdapter

        adapter = EchoMissionAdapter(cmd_defs={})
        pipeline = RxPipeline(adapter, tx_freq_map={})
        pkt = pipeline.process({"transmitter": "test"}, b"\x01\x02\x03\x04")
        # Echo adapter: is_unknown_packet always returns True
        self.assertTrue(pkt.is_unknown)
        self.assertEqual(pkt.unknown_num, 1)

    def test_maveric_pipeline_known_command_not_unknown(self):
        """MAVERIC adapter classifies parsed commands as known."""
        from mav_gss_lib.parsing import RxPipeline
        from mav_gss_lib.config import load_gss_config
        from mav_gss_lib.mission_adapter import load_mission_adapter

        cfg = load_gss_config()
        adapter = load_mission_adapter(cfg)

        pipeline = RxPipeline(adapter, tx_freq_map={})
        # Process a minimal raw packet with no valid command
        pkt = pipeline.process({"transmitter": "test"}, b"\x00\x01\x02\x03")
        # Short payload with no valid command → unknown
        self.assertTrue(pkt.is_unknown)


class TestReplayCompat(unittest.TestCase):
    """Verify replay reads both new envelope and legacy flat formats."""

    def setUp(self):
        from mav_gss_lib.config import load_gss_config
        from mav_gss_lib.mission_adapter import load_mission_adapter

        cfg = load_gss_config()
        adapter = load_mission_adapter(cfg)
        self.cmd_defs = adapter.cmd_defs

    def test_new_envelope_replay_passes_through_rendering(self):
        """Replay passes through _rendering from new-format RX log entries."""
        from mav_gss_lib.web_runtime.api import parse_replay_entry

        rendering = {
            "row": {"values": {"cmd": "com_ping", "src": "GS"}, "_meta": {"opacity": 1.0}},
            "detail_blocks": [{"kind": "routing", "label": "Routing", "fields": []}],
            "protocol_blocks": [{"kind": "csp", "label": "CSP V1", "fields": []}],
            "integrity_blocks": [{"kind": "crc16", "label": "CRC-16", "scope": "command", "ok": True}],
        }
        entry = {
            "v": "4.3.1", "pkt": 1,
            "gs_ts": "2026-04-06 10:30:00 PDT",
            "frame_type": "AX.25", "raw_hex": "deadbeef", "raw_len": 4,
            "duplicate": False, "uplink_echo": False, "unknown": False,
            "_rendering": rendering,
        }
        result = parse_replay_entry(entry, self.cmd_defs)
        self.assertIsNotNone(result)
        self.assertEqual(result["num"], 1)
        self.assertFalse(result["is_dup"])
        # RX entries no longer emit flat cmd/src/dest fields
        self.assertNotIn("cmd", result)
        self.assertNotIn("src", result)
        # _rendering is passed through verbatim
        self.assertEqual(result["_rendering"], rendering)
        self.assertEqual(result["_rendering"]["row"]["values"]["cmd"], "com_ping")

    def test_rx_entry_without_rendering_gets_empty_rendering(self):
        """RX entry without _rendering gets empty dict — no flat field reconstruction."""
        from mav_gss_lib.web_runtime.api import parse_replay_entry

        entry = {
            "v": "4.3.0", "pkt": 1,
            "gs_ts": "2026-04-06 10:30:00 PDT",
            "frame_type": "AX.25", "raw_hex": "deadbeef", "raw_len": 4,
            "duplicate": False, "uplink_echo": False, "unknown": False,
        }
        result = parse_replay_entry(entry, self.cmd_defs)
        self.assertIsNotNone(result)
        self.assertEqual(result["num"], 1)
        # No flat mission fields
        self.assertNotIn("cmd", result)
        self.assertNotIn("csp_header", result)
        # Empty _rendering passthrough
        self.assertEqual(result["_rendering"], {})

    def test_tx_log_entry_detected_by_missing_pkt_field(self):
        """TX log entries (no 'pkt' field) are correctly identified."""
        from mav_gss_lib.web_runtime.api import parse_replay_entry

        entry = {
            "n": 1, "ts": "2026-04-06T10:30:00",
            "cmd": "com_ping", "args": "",
            "src": 6, "dest": 1, "echo": 0, "ptype": 1,
            "raw_hex": "deadbeef", "len": 4,
        }
        result = parse_replay_entry(entry, self.cmd_defs)
        self.assertIsNotNone(result)
        self.assertEqual(result["cmd"], "com_ping")
        self.assertFalse(result["is_dup"])
        self.assertFalse(result["is_echo"])


if __name__ == "__main__":
    unittest.main()
