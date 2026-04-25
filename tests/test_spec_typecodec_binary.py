import struct
import unittest

from mav_gss_lib.platform.spec.cursor import BitCursor
from mav_gss_lib.platform.spec.parameter_types import (
    BUILT_IN_PARAMETER_TYPES,
    AbsoluteTimeParameterType,
)
from mav_gss_lib.platform.spec.runtime import TypeCodec


class TestTypeCodecBinaryDecode(unittest.TestCase):
    def setUp(self):
        self.types = dict(BUILT_IN_PARAMETER_TYPES)

    def test_u16_le(self):
        codec = TypeCodec(types=self.types)
        cursor = BitCursor(b"\x34\x12")
        self.assertEqual(codec.decode_binary("u16", cursor), 0x1234)

    def test_i16_signed_le(self):
        codec = TypeCodec(types=self.types)
        cursor = BitCursor(b"\xff\xff")
        self.assertEqual(codec.decode_binary("i16", cursor), -1)

    def test_u32_be(self):
        codec = TypeCodec(types=self.types)
        cursor = BitCursor(b"\x00\x00\x12\x34")
        self.assertEqual(codec.decode_binary("u32_be", cursor), 0x1234)

    def test_f32_le(self):
        codec = TypeCodec(types=self.types)
        cursor = BitCursor(struct.pack("<f", 3.14))
        self.assertAlmostEqual(codec.decode_binary("f32_le", cursor), 3.14, places=4)

    def test_absolute_time_millis_u64(self):
        types = dict(self.types)
        types["BeaconTime"] = AbsoluteTimeParameterType(
            name="BeaconTime", encoding="millis_u64", epoch="unix", byte_order="little",
        )
        codec = TypeCodec(types=types)
        cursor = BitCursor(struct.pack("<Q", 1767225608224))
        decoded = codec.decode_binary("BeaconTime", cursor)
        self.assertEqual(decoded["unix_ms"], 1767225608224)


class TestTypeCodecBinaryEncode(unittest.TestCase):
    def setUp(self):
        self.types = dict(BUILT_IN_PARAMETER_TYPES)

    def test_u16_le_encode(self):
        codec = TypeCodec(types=self.types)
        self.assertEqual(codec.encode_binary("u16", 0x1234), b"\x34\x12")

    def test_i16_signed_le_encode(self):
        codec = TypeCodec(types=self.types)
        self.assertEqual(codec.encode_binary("i16", -1), b"\xff\xff")

    def test_f32_le_encode_roundtrip(self):
        codec = TypeCodec(types=self.types)
        wire = codec.encode_binary("f32_le", 3.14)
        self.assertAlmostEqual(struct.unpack("<f", wire)[0], 3.14, places=4)


if __name__ == "__main__":
    unittest.main()
