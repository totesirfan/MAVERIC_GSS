"""Coverage for the ArgumentType family (XTCE-lite TC-side type system).

ArgumentType is parallel to ParameterType, not a subclass. It carries
encoding-relevant fields (size_bits/signed/byte_order for int) plus TC
validation (valid_range, valid_values). It does NOT carry calibrator
or unit — **MAVERIC subset choice**. Full XTCE allows both on TC types;
we omit them because today's TC pipeline has no consumer. If that
changes, add the field AND a UI/display consumer in the same change.
"""

import unittest


class TestIntegerArgumentType(unittest.TestCase):
    def test_carries_encoding_fields(self):
        from mav_gss_lib.platform.spec.argument_types import IntegerArgumentType
        t = IntegerArgumentType(name="u8", size_bits=8)
        self.assertEqual(t.name, "u8")
        self.assertEqual(t.size_bits, 8)
        self.assertFalse(t.signed)
        self.assertEqual(t.byte_order, "little")

    def test_carries_valid_range(self):
        from mav_gss_lib.platform.spec.argument_types import IntegerArgumentType
        t = IntegerArgumentType(name="year_2digit_t", size_bits=8, valid_range=(0.0, 99.0))
        self.assertEqual(t.valid_range, (0.0, 99.0))

    def test_carries_valid_values(self):
        from mav_gss_lib.platform.spec.argument_types import IntegerArgumentType
        t = IntegerArgumentType(name="ops_stage_t", size_bits=8, valid_values=(0, 1, 2))
        self.assertEqual(t.valid_values, (0, 1, 2))

    def test_carries_description(self):
        from mav_gss_lib.platform.spec.argument_types import IntegerArgumentType
        t = IntegerArgumentType(name="year_2digit_t", size_bits=8,
                                description="2-digit year (26 for 2026)")
        self.assertEqual(t.description, "2-digit year (26 for 2026)")

    def test_does_not_have_calibrator_or_unit(self):
        from mav_gss_lib.platform.spec.argument_types import IntegerArgumentType
        t = IntegerArgumentType(name="u8", size_bits=8)
        self.assertFalse(hasattr(t, "calibrator"))
        self.assertFalse(hasattr(t, "unit"))


class TestStringArgumentType(unittest.TestCase):
    def test_basic(self):
        from mav_gss_lib.platform.spec.argument_types import StringArgumentType
        t = StringArgumentType(name="ascii_token", encoding="ascii_token")
        self.assertEqual(t.encoding, "ascii_token")


class TestBuiltInArgumentTypes(unittest.TestCase):
    def test_includes_basic_int_widths(self):
        from mav_gss_lib.platform.spec.argument_types import BUILT_IN_ARGUMENT_TYPES
        for name in ("u8", "u16", "u32", "i8", "i16", "i32"):
            self.assertIn(name, BUILT_IN_ARGUMENT_TYPES, f"missing built-in: {name}")

    def test_includes_ascii_string_built_ins(self):
        # Mirror parameter-side built-ins so existing commands declaring
        # `ascii_blob` (e.g., free-form payloads) continue to resolve.
        from mav_gss_lib.platform.spec.argument_types import BUILT_IN_ARGUMENT_TYPES
        self.assertIn("ascii_token", BUILT_IN_ARGUMENT_TYPES)
        self.assertIn("ascii_blob", BUILT_IN_ARGUMENT_TYPES)


class TestParameterArgumentBuiltInParity(unittest.TestCase):
    """Document and enforce the deliberate (in)equalities between
    BUILT_IN_PARAMETER_TYPES and BUILT_IN_ARGUMENT_TYPES. The shared
    encoding-relevant primitives (u8/u16/u32/i8/i16/i32/f32_le/f64_le/
    ascii_token/ascii_blob) appear in both. Telemetry-only entries
    (BE variants, bool) appear in PARAMETER_TYPES only — by design.
    """

    SHARED = ("u8", "u16", "u32", "u64", "i8", "i16", "i32", "i64",
              "f32_le", "f64_le", "ascii_token", "ascii_blob")
    TM_ONLY = ("u16_be", "u32_be", "u64_be", "i16_be", "i32_be", "i64_be", "bool")

    def test_shared_built_ins_present_in_both(self):
        from mav_gss_lib.platform.spec.argument_types import BUILT_IN_ARGUMENT_TYPES
        from mav_gss_lib.platform.spec.parameter_types import BUILT_IN_PARAMETER_TYPES
        for name in self.SHARED:
            self.assertIn(name, BUILT_IN_PARAMETER_TYPES, f"shared {name} missing from TM")
            self.assertIn(name, BUILT_IN_ARGUMENT_TYPES, f"shared {name} missing from TC")

    def test_tm_only_built_ins_excluded_from_argument_types(self):
        from mav_gss_lib.platform.spec.argument_types import BUILT_IN_ARGUMENT_TYPES
        from mav_gss_lib.platform.spec.parameter_types import BUILT_IN_PARAMETER_TYPES
        for name in self.TM_ONLY:
            self.assertIn(name, BUILT_IN_PARAMETER_TYPES, f"TM {name} missing from TM")
            self.assertNotIn(
                name, BUILT_IN_ARGUMENT_TYPES,
                f"TM-only {name} leaked into TC built-ins; if intentional, "
                "update TM_ONLY in this test",
            )

    def test_built_in_encoding_fields_match_for_shared_int_types(self):
        # u8 in argument_types must have the same size_bits/signed/byte_order
        # as u8 in parameter_types — wire compatibility depends on this.
        from mav_gss_lib.platform.spec.argument_types import BUILT_IN_ARGUMENT_TYPES
        from mav_gss_lib.platform.spec.parameter_types import BUILT_IN_PARAMETER_TYPES
        for name in ("u8", "u16", "u32", "i8", "i16", "i32"):
            tm = BUILT_IN_PARAMETER_TYPES[name]
            tc = BUILT_IN_ARGUMENT_TYPES[name]
            self.assertEqual(tm.size_bits, tc.size_bits, name)
            self.assertEqual(tm.signed, tc.signed, name)
            self.assertEqual(tm.byte_order, tc.byte_order, name)


if __name__ == "__main__":
    unittest.main()
