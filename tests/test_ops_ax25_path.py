"""Operations-focused AX.25 path tests for MAVERIC GSS."""

from __future__ import annotations

import unittest

from ops_test_support import CMD_DEFS

from mav_gss_lib.protocols.ax25 import AX25Config, ax25_decode_header, build_ax25_gfsk_frame
from mav_gss_lib.parsing import RxPipeline, build_rx_log_record
from mav_gss_lib.protocols.csp import CSPConfig
from mav_gss_lib.missions.maveric.wire_format import build_cmd_raw


META_AX25 = {"transmitter": "9k6 FSK AX.25 downlink"}


class TestAX25Path(unittest.TestCase):
    def setUp(self):
        self.csp = CSPConfig()
        self.ax25 = AX25Config()
        self.pipeline = RxPipeline(CMD_DEFS, {})

    def test_ax25_rx_pipeline_recovers_ping(self):
        raw = build_cmd_raw(6, 2, "ping", "REQ")
        payload = self.ax25.wrap(self.csp.wrap(raw))
        pkt = self.pipeline.process(META_AX25, payload)
        self.assertEqual(pkt.frame_type, "AX.25")
        self.assertEqual(pkt.mission_data["cmd"]["cmd_id"], "ping")
        self.assertTrue(pkt.mission_data["cmd"]["crc_valid"])
        self.assertTrue(pkt.mission_data["crc_status"]["csp_crc32_valid"])
        self.assertTrue(pkt.mission_data["cmd"]["schema_match"])

    def test_ax25_marks_ground_echo(self):
        raw = build_cmd_raw(6, 2, "ping", "REQ")
        payload = self.ax25.wrap(self.csp.wrap(raw))
        pkt = self.pipeline.process(META_AX25, payload)
        self.assertTrue(pkt.is_uplink_echo)

    def test_ax25_payload_is_deterministic(self):
        raw = build_cmd_raw(6, 2, "set_mode", "NOMINAL")
        payload = self.ax25.wrap(self.csp.wrap(raw))
        frame_a = build_ax25_gfsk_frame(payload)
        frame_b = build_ax25_gfsk_frame(payload)
        self.assertEqual(frame_a, frame_b)

    def test_ax25_log_record_matches_input_bytes(self):
        raw = build_cmd_raw(6, 2, "set_mode", "NOMINAL")
        payload = self.ax25.wrap(self.csp.wrap(raw))
        pkt = self.pipeline.process(META_AX25, payload)
        record = build_rx_log_record(pkt, "test", META_AX25, self.pipeline.adapter)
        self.assertEqual(record["raw_hex"], payload.hex())
        self.assertEqual(record["frame_type"], "AX.25")
        self.assertEqual(record["mission"]["cmd"]["cmd_id"], "set_mode")

    def test_ax25_header_decode_round_trip(self):
        self.ax25.dest_call = "CQ"
        self.ax25.dest_ssid = 0
        self.ax25.src_call = "N0CALL"
        self.ax25.src_ssid = 1
        header = self.ax25.wrap(b"")[: self.ax25.HEADER_LEN]
        decoded = ax25_decode_header(header)
        self.assertEqual(decoded["dest"]["callsign"], "CQ")
        self.assertEqual(decoded["dest"]["ssid"], 0)
        self.assertEqual(decoded["src"]["callsign"], "N0CALL")
        self.assertEqual(decoded["src"]["ssid"], 1)
        self.assertEqual(decoded["control"], 0x03)
        self.assertEqual(decoded["pid"], 0xF0)

    def test_ax25_protocol_block_decodes_callsigns(self):
        self.ax25.dest_call = "CQ"
        self.ax25.dest_ssid = 0
        self.ax25.src_call = "N0CALL"
        self.ax25.src_ssid = 1
        raw = build_cmd_raw(6, 2, "ping", "REQ")
        payload = self.ax25.wrap(self.csp.wrap(raw))
        pkt = self.pipeline.process(META_AX25, payload)
        blocks = self.pipeline.adapter.protocol_blocks(pkt)
        ax25_block = next(b for b in blocks if b.kind == "ax25")
        fields = {field["name"]: field["value"] for field in ax25_block.fields}
        self.assertEqual(fields["Dest"], "CQ-0")
        self.assertEqual(fields["Src"], "N0CALL-1")
        self.assertEqual(fields["Control"], "0x03")
        self.assertEqual(fields["PID"], "0xF0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
