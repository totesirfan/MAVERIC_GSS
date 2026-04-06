"""Operations-focused AX.25 path tests for MAVERIC GSS."""

from __future__ import annotations

import unittest

from ops_test_support import CMD_DEFS

from mav_gss_lib.ax25 import build_ax25_gfsk_frame
from mav_gss_lib.parsing import RxPipeline, build_rx_log_record
from mav_gss_lib.protocol import AX25Config, CSPConfig, build_cmd_raw


META_AX25 = {"transmitter": "9k6 FSK AX.25 downlink"}


class TestAX25Path(unittest.TestCase):
    def setUp(self):
        self.csp = CSPConfig()
        self.ax25 = AX25Config()
        self.pipeline = RxPipeline(CMD_DEFS, {})

    def test_ax25_rx_pipeline_recovers_ping(self):
        raw = build_cmd_raw(2, "ping", "REQ")
        payload = self.ax25.wrap(self.csp.wrap(raw))
        pkt = self.pipeline.process(META_AX25, payload)
        self.assertEqual(pkt.frame_type, "AX.25")
        self.assertEqual(pkt.cmd["cmd_id"], "ping")
        self.assertTrue(pkt.cmd["crc_valid"])
        self.assertTrue(pkt.crc_status["csp_crc32_valid"])
        self.assertTrue(pkt.cmd["schema_match"])

    def test_ax25_marks_ground_echo(self):
        raw = build_cmd_raw(2, "ping", "REQ")
        payload = self.ax25.wrap(self.csp.wrap(raw))
        pkt = self.pipeline.process(META_AX25, payload)
        self.assertTrue(pkt.is_uplink_echo)

    def test_ax25_payload_is_deterministic(self):
        raw = build_cmd_raw(2, "set_mode", "NOMINAL")
        payload = self.ax25.wrap(self.csp.wrap(raw))
        frame_a = build_ax25_gfsk_frame(payload)
        frame_b = build_ax25_gfsk_frame(payload)
        self.assertEqual(frame_a, frame_b)

    def test_ax25_log_record_matches_input_bytes(self):
        raw = build_cmd_raw(2, "set_mode", "NOMINAL")
        payload = self.ax25.wrap(self.csp.wrap(raw))
        pkt = self.pipeline.process(META_AX25, payload)
        record = build_rx_log_record(pkt, "test", META_AX25, self.pipeline.adapter)
        self.assertEqual(record["raw_hex"], payload.hex())
        self.assertEqual(record["frame_type"], "AX.25")
        self.assertEqual(record["mission"]["cmd"]["cmd_id"], "set_mode")


if __name__ == "__main__":
    unittest.main(verbosity=2)
