"""AsciiArgumentEncoder is the TC-side peer of TypeCodec. It must:
  - encode int/float/string ArgumentType variants to canonical ASCII tokens,
  - have NO decode method (encode-only by design),
  - reject unknown types with a clear TypeError.
"""

import unittest

from mav_gss_lib.platform.spec.argument_types import (
    BUILT_IN_ARGUMENT_TYPES,
    FloatArgumentType,
    IntegerArgumentType,
    StringArgumentType,
)
from mav_gss_lib.platform.spec.runtime import AsciiArgumentEncoder


class TestAsciiArgumentEncoder(unittest.TestCase):
    def setUp(self):
        self.types = dict(BUILT_IN_ARGUMENT_TYPES)
        self.types["custom_to_end"] = StringArgumentType(
            name="custom_to_end", encoding="to_end",
        )
        self.enc = AsciiArgumentEncoder(types=self.types)

    def test_int_canonicalizes_padded_input(self):
        self.assertEqual(self.enc.encode_ascii("u8", "026"), "26")
        self.assertEqual(self.enc.encode_ascii("i32", -7), "-7")

    def test_float_uses_repr(self):
        self.assertEqual(self.enc.encode_ascii("f32_le", 1.5), "1.5")

    def test_ascii_token_string_passthrough(self):
        self.assertEqual(self.enc.encode_ascii("ascii_token", "MAV-GSS"), "MAV-GSS")

    def test_to_end_string_passthrough_with_whitespace(self):
        self.assertEqual(
            self.enc.encode_ascii("custom_to_end", "all systems nominal"),
            "all systems nominal",
        )

    def test_no_decode_method(self):
        # By design: TC side never decodes. Catching this regression at
        # test-time is cheaper than catching it as a runtime AttributeError
        # somewhere in EntryDecoder.
        self.assertFalse(hasattr(self.enc, "decode_ascii"))


if __name__ == "__main__":
    unittest.main()
