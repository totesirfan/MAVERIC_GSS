import struct
import unittest
from datetime import datetime, timezone

from mav_gss_lib.platform.spec.time_codec import (
    decode_millis_u64,
    encode_millis_u64,
)


class TestMillisU64(unittest.TestCase):
    def test_roundtrip_known_value(self):
        ms = 1767225608224
        wire = encode_millis_u64(ms)
        self.assertEqual(len(wire), 8)
        self.assertEqual(struct.unpack("<Q", wire)[0], ms)
        decoded = decode_millis_u64(wire)
        self.assertEqual(decoded["unix_ms"], ms)
        self.assertEqual(decoded["iso_utc"], "2026-01-01 00:00:08 UTC")
        self.assertEqual(decoded["display"], decoded["iso_utc"])

    def test_encode_accepts_datetime(self):
        dt = datetime(2026, 1, 1, 0, 0, 8, 224000, tzinfo=timezone.utc)
        wire = encode_millis_u64(dt)
        decoded = decode_millis_u64(wire)
        self.assertEqual(decoded["unix_ms"], 1767225608224)

    def test_corrupt_value_falls_back_to_raw(self):
        # 0xFFFF_FFFF_FFFF_FFFF — well past datetime's max
        wire = struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
        decoded = decode_millis_u64(wire)
        self.assertEqual(decoded["unix_ms"], 0xFFFFFFFFFFFFFFFF)
        self.assertIsNone(decoded["iso_utc"])
        self.assertTrue(decoded["display"].startswith("raw="))


if __name__ == "__main__":
    unittest.main()
