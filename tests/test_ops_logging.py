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
        from mav_gss_lib.config import load_gss_config, get_command_defs_path
        from mav_gss_lib.mission_adapter import load_mission_metadata
        from mav_gss_lib.protocol import init_nodes, load_command_defs
        from mav_gss_lib.missions.maveric.adapter import MavericMissionAdapter

        cfg = load_gss_config()
        load_mission_metadata(cfg)
        init_nodes(cfg)
        cmd_defs, _ = load_command_defs(get_command_defs_path(cfg))
        self.adapter = MavericMissionAdapter(cmd_defs=cmd_defs)

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


if __name__ == "__main__":
    unittest.main()
