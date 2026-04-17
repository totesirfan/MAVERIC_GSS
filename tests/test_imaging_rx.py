"""Test that cam_capture_imgs and img_cnt_chunks responses feed both full
and thumb sides into the assembler and emit two imaging_progress broadcasts
per RX — one for each leaf."""
import unittest

from mav_gss_lib.config import load_gss_config
from mav_gss_lib.mission_adapter import load_mission_adapter


class FakePacket:
    """Minimal packet stand-in matching what adapter.on_packet_received reads.

    Only `mission_data` is accessed by the handler; we populate the exact
    shape that the `_md(pkt)` helper returns.
    """
    def __init__(self, cmd_id, ptype_num, typed_args):
        self.mission_data = {
            "cmd": {
                "cmd_id": cmd_id,
                "pkt_type": ptype_num,
                "schema_match": True,
                "typed_args": typed_args,
            }
        }


def _find_ptype(adapter, name):
    """Resolve a ptype name to its numeric id via the public nodes accessor."""
    for num in range(32):
        try:
            if adapter.nodes.ptype_name(num) == name:
                return num
        except Exception:
            continue
    return None


class TestPairedImagingRX(unittest.TestCase):
    def setUp(self):
        cfg = load_gss_config()
        self.adapter = load_mission_adapter(cfg)
        self.res_ptype = _find_ptype(self.adapter, "RES")
        self.cmd_ptype = _find_ptype(self.adapter, "CMD")
        self.assertIsNotNone(self.res_ptype, "RES ptype not found in nodes table")
        self.assertIsNotNone(self.cmd_ptype, "CMD ptype not found in nodes table")

    def _four_field_args(self, full_fn, full_count, thumb_fn, thumb_count):
        return [
            {"name": "Filename", "value": full_fn},
            {"name": "Num Chunks", "value": str(full_count)},
            {"name": "Thumb Filename", "value": thumb_fn},
            {"name": "Thumb Num Chunks", "value": str(thumb_count)},
        ]

    def test_cam_capture_imgs_populates_both_leaves(self):
        pkt = FakePacket(
            cmd_id="cam_capture_imgs",
            ptype_num=self.res_ptype,
            typed_args=self._four_field_args("limb_003.jpg", 84, "thumb_limb_003.jpg", 12),
        )
        messages = self.adapter.on_packet_received(pkt)
        self.assertIsNotNone(messages)
        self.assertEqual(len(messages), 2, "expected one imaging_progress per leaf")

        msg_by_fn = {m["filename"]: m for m in messages}
        self.assertIn("limb_003.jpg", msg_by_fn)
        self.assertIn("thumb_limb_003.jpg", msg_by_fn)
        self.assertEqual(msg_by_fn["limb_003.jpg"]["total"], 84)
        self.assertEqual(msg_by_fn["thumb_limb_003.jpg"]["total"], 12)

        # Both totals are stored in the assembler.
        self.assertEqual(self.adapter.image_assembler.totals.get("limb_003.jpg"), 84)
        self.assertEqual(self.adapter.image_assembler.totals.get("thumb_limb_003.jpg"), 12)

    def test_img_cnt_chunks_populates_both_leaves(self):
        """img_cnt_chunks uses the same four-field schema and same branch."""
        pkt = FakePacket(
            cmd_id="img_cnt_chunks",
            ptype_num=self.res_ptype,
            typed_args=self._four_field_args("limb_004.jpg", 60, "thumb_limb_004.jpg", 8),
        )
        messages = self.adapter.on_packet_received(pkt)
        self.assertIsNotNone(messages)
        self.assertEqual(len(messages), 2)
        self.assertEqual(self.adapter.image_assembler.totals.get("limb_004.jpg"), 60)
        self.assertEqual(self.adapter.image_assembler.totals.get("thumb_limb_004.jpg"), 8)

    def test_paired_rx_non_res_ptype_ignored(self):
        """CMD ptype (operator echo) must not poison the assembler."""
        pkt = FakePacket(
            cmd_id="cam_capture_imgs",
            ptype_num=self.cmd_ptype,
            typed_args=self._four_field_args("echo_test.jpg", 99, "thumb_echo_test.jpg", 7),
        )
        messages = self.adapter.on_packet_received(pkt)
        self.assertIsNone(messages)
        self.assertNotIn("echo_test.jpg", self.adapter.image_assembler.totals)
        self.assertNotIn("thumb_echo_test.jpg", self.adapter.image_assembler.totals)

    def test_cam_capture_imgs_thumb_missing_falls_back_to_full_only(self):
        """If a pre-firmware-update node emits the old 2-field response, the
        handler still populates the full side and skips the thumb side
        without erroring."""
        pkt = FakePacket(
            cmd_id="cam_capture_imgs",
            ptype_num=self.res_ptype,
            typed_args=[
                {"name": "Filename", "value": "legacy_001.jpg"},
                {"name": "Num Chunks", "value": "50"},
            ],
        )
        messages = self.adapter.on_packet_received(pkt)
        self.assertIsNotNone(messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["filename"], "legacy_001.jpg")
        self.assertEqual(self.adapter.image_assembler.totals.get("legacy_001.jpg"), 50)


if __name__ == "__main__":
    unittest.main()
