"""Operations-focused ASM+Golay path tests for MAVERIC GSS."""

from __future__ import annotations

import unittest

from ops_test_support import CMD_DEFS, decode_golay_via_flowgraph, decode_golay_via_gr

from mav_gss_lib.protocols.golay import MAX_PAYLOAD, build_asm_golay_frame
from mav_gss_lib.parsing import RxPipeline
from mav_gss_lib.protocols.csp import CSPConfig
from mav_gss_lib.missions.maveric.wire_format import build_cmd_raw


META_GOLAY = {"transmitter": "4k8 FSK AX100 ASM+Golay downlink"}


class TestGolayPath(unittest.TestCase):
    def setUp(self):
        self.csp = CSPConfig()
        self.pipeline = RxPipeline(CMD_DEFS, {})

    def test_frame_size_is_fixed(self):
        packet = self.csp.wrap(build_cmd_raw(6, 2, "ping", "REQ"))
        frame = build_asm_golay_frame(packet)
        self.assertEqual(len(frame), 312)
        self.assertEqual(frame[50:54].hex(), "930b51de")

    def test_golay_header_flag_bits_remain_zero(self):
        packet = self.csp.wrap(build_cmd_raw(6, 2, "ping", "REQ"))
        frame = build_asm_golay_frame(packet)
        golay_header = frame[54:57]
        length_field = int.from_bytes(golay_header, "big") & 0xFFF

        self.assertEqual((length_field >> 8) & 0x7, 0)

    def test_rejects_over_max_payload(self):
        with self.assertRaises(ValueError):
            build_asm_golay_frame(bytes(MAX_PAYLOAD + 1))

    def test_gr_satellites_roundtrip_ping(self):
        raw = build_cmd_raw(6, 2, "ping", "REQ")
        packet = self.csp.wrap(raw)
        frame = build_asm_golay_frame(packet)
        decoded = decode_golay_via_gr(frame)
        self.assertEqual(decoded, packet)

        pkt = self.pipeline.process(META_GOLAY, decoded)
        self.assertEqual(pkt.frame_type, "ASM+GOLAY")
        self.assertEqual(pkt.mission_data["cmd"]["cmd_id"], "ping")
        self.assertTrue(pkt.mission_data["cmd"]["crc_valid"])
        self.assertTrue(pkt.mission_data["crc_status"]["csp_crc32_valid"])
        self.assertTrue(pkt.mission_data["cmd"]["schema_match"])

    def test_gr_satellites_roundtrip_at_rs_limit(self):
        packet = bytes(range(256))[:MAX_PAYLOAD]
        frame = build_asm_golay_frame(packet)
        decoded = decode_golay_via_gr(frame)
        self.assertEqual(decoded, packet)

    def test_full_flowgraph_roundtrip_set_mode(self):
        raw = build_cmd_raw(6, 2, "set_mode", "NOMINAL")
        packet = self.csp.wrap(raw)
        frame = build_asm_golay_frame(packet)
        decoded, meta = decode_golay_via_flowgraph(frame)
        self.assertEqual(decoded, packet)

        pkt = self.pipeline.process(meta, decoded)
        self.assertEqual(pkt.frame_type, "ASM+GOLAY")
        self.assertEqual(pkt.mission_data["cmd"]["cmd_id"], "set_mode")
        self.assertEqual(pkt.mission_data["cmd"]["args"], ["NOMINAL"])
        self.assertTrue(pkt.mission_data["cmd"]["crc_valid"])
        self.assertTrue(pkt.mission_data["crc_status"]["csp_crc32_valid"])
        self.assertTrue(pkt.mission_data["cmd"]["schema_match"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
