"""Operations-focused RX pipeline behavior tests for MAVERIC GSS."""

from __future__ import annotations

import unittest

from ops_test_support import CMD_DEFS

from mav_gss_lib.parsing import RxPipeline, build_rx_log_record
from mav_gss_lib.protocols.ax25 import AX25Config
from mav_gss_lib.protocols.csp import CSPConfig
from mav_gss_lib.missions.maveric.wire_format import build_cmd_raw


META_AX25 = {"transmitter": "9k6 FSK AX.25 downlink"}
META_GOLAY = {"transmitter": "4k8 FSK AX100 ASM+Golay downlink"}


class TestRxPipelineBehavior(unittest.TestCase):
    def setUp(self):
        self.pipeline = RxPipeline(CMD_DEFS, {})
        self.csp = CSPConfig()
        self.ax25 = AX25Config()

    def test_duplicate_detection_flags_second_packet(self):
        raw = build_cmd_raw(6, 2, "ping", "REQ")
        payload = self.ax25.wrap(self.csp.wrap(raw))
        first = self.pipeline.process(META_AX25, payload)
        second = self.pipeline.process(META_AX25, payload)
        self.assertFalse(first.is_dup)
        self.assertTrue(second.is_dup)

    def test_non_echo_downlink_is_not_marked_as_uplink_echo(self):
        raw = build_cmd_raw(2, 6, "tlm_beacon", "1 1767230528021 0 0")
        payload = self.ax25.wrap(self.csp.wrap(raw))
        pkt = self.pipeline.process(META_AX25, payload)
        self.assertFalse(pkt.is_uplink_echo)
        self.assertEqual(pkt.mission_data["cmd"]["cmd_id"], "tlm_beacon")

    def test_golay_meta_is_classified_as_asm_golay(self):
        raw = build_cmd_raw(6, 2, "ping", "REQ")
        payload = self.csp.wrap(raw)
        pkt = self.pipeline.process(META_GOLAY, payload)
        self.assertEqual(pkt.frame_type, "ASM+GOLAY")
        self.assertEqual(pkt.mission_data["cmd"]["cmd_id"], "ping")

    def test_log_record_contains_operationally_relevant_fields(self):
        raw = build_cmd_raw(6, 2, "set_mode", "NOMINAL")
        payload = self.ax25.wrap(self.csp.wrap(raw))
        pkt = self.pipeline.process(META_AX25, payload)
        record = build_rx_log_record(pkt, "test-version", META_AX25, self.pipeline.adapter)
        self.assertIn("gs_ts", record)
        self.assertIn("frame_type", record)
        self.assertIn("raw_hex", record)
        self.assertEqual(record["mission"]["cmd"]["cmd_id"], "set_mode")
        self.assertEqual(record["frame_type"], "AX.25")

    def test_unknown_frame_type_leaves_warning_and_raw_payload(self):
        raw = build_cmd_raw(6, 2, "ping", "REQ")
        payload = self.csp.wrap(raw)
        pkt = self.pipeline.process({"transmitter": "mystery"}, payload)
        self.assertEqual(pkt.frame_type, "UNKNOWN")
        self.assertEqual(pkt.inner_payload, payload)
        self.assertTrue(any("Unknown frame type" in warning for warning in pkt.warnings))


if __name__ == "__main__":
    unittest.main(verbosity=2)
