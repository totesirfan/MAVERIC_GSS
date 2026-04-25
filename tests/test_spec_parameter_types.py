import unittest

from mav_gss_lib.platform.spec.parameter_types import (
    BUILT_IN_PARAMETER_TYPES,
    AbsoluteTimeParameterType,
    AggregateMember,
    AggregateParameterType,
    ArrayParameterType,
    BinaryParameterType,
    EnumeratedParameterType,
    EnumValue,
    FloatParameterType,
    IntegerParameterType,
    ParameterType,
    StringParameterType,
)


class TestBuiltInPrimitives(unittest.TestCase):
    def test_builtins_cover_unsigned_le_widths(self):
        for name, width in [("u8", 8), ("u16", 16), ("u32", 32), ("u64", 64)]:
            t = BUILT_IN_PARAMETER_TYPES[name]
            self.assertIsInstance(t, IntegerParameterType)
            self.assertEqual(t.size_bits, width)
            self.assertFalse(t.signed)
            self.assertEqual(t.byte_order, "little")

    def test_builtins_cover_signed_le_widths(self):
        for name, width in [("i8", 8), ("i16", 16), ("i32", 32), ("i64", 64)]:
            t = BUILT_IN_PARAMETER_TYPES[name]
            self.assertIsInstance(t, IntegerParameterType)
            self.assertEqual(t.size_bits, width)
            self.assertTrue(t.signed)

    def test_builtins_cover_be_variants(self):
        self.assertEqual(BUILT_IN_PARAMETER_TYPES["u16_be"].byte_order, "big")
        self.assertEqual(BUILT_IN_PARAMETER_TYPES["u32_be"].byte_order, "big")
        self.assertEqual(BUILT_IN_PARAMETER_TYPES["i32_be"].byte_order, "big")

    def test_builtins_cover_float_variants(self):
        for name in ("f32_le", "f64_le", "f32_be", "f64_be"):
            t = BUILT_IN_PARAMETER_TYPES[name]
            self.assertIsInstance(t, FloatParameterType)

    def test_bool_is_alias_for_one_byte_enum(self):
        t = BUILT_IN_PARAMETER_TYPES["bool"]
        self.assertIsInstance(t, EnumeratedParameterType)
        self.assertEqual(t.size_bits, 8)
        labels = {v.raw: v.label for v in t.values}
        self.assertEqual(labels, {0: "false", 1: "true"})

    def test_ascii_token_is_string_type(self):
        t = BUILT_IN_PARAMETER_TYPES["ascii_token"]
        self.assertIsInstance(t, StringParameterType)
        self.assertEqual(t.encoding, "ascii_token")

    def test_ascii_blob_is_string_type(self):
        t = BUILT_IN_PARAMETER_TYPES["ascii_blob"]
        self.assertIsInstance(t, StringParameterType)
        self.assertEqual(t.encoding, "to_end")


class TestParameterTypeDataclasses(unittest.TestCase):
    def test_integer_dataclass_carries_calibrator_valid_range(self):
        t = IntegerParameterType(
            name="V_volts",
            size_bits=16,
            signed=True,
            byte_order="little",
            unit="V",
            valid_range=(-32.0, 32.0),
        )
        self.assertEqual(t.unit, "V")
        self.assertEqual(t.valid_range, (-32.0, 32.0))

    def test_aggregate_carries_member_list_and_unit(self):
        t = AggregateParameterType(
            name="Quaternion",
            member_list=(
                AggregateMember(name="q0", type_ref="f32_le"),
                AggregateMember(name="q1", type_ref="f32_le"),
            ),
            unit="",
        )
        self.assertEqual(len(t.member_list), 2)

    def test_array_dimension_list_is_tuple(self):
        t = ArrayParameterType(
            name="RwSpeeds",
            array_type_ref="i32_rpm",
            dimension_list=(4,),
        )
        self.assertEqual(t.dimension_list, (4,))

    def test_enum_value_carries_raw_label_description(self):
        v = EnumValue(raw=0, label="Safe", description="planner safe mode")
        self.assertEqual(v.raw, 0)

    def test_absolute_time_dataclass(self):
        t = AbsoluteTimeParameterType(
            name="BeaconTime",
            encoding="millis_u64",
            epoch="unix",
            byte_order="little",
        )
        self.assertEqual(t.encoding, "millis_u64")

    def test_binary_dynamic_ref(self):
        t = BinaryParameterType(
            name="ChunkData",
            size_kind="dynamic_ref",
            size_ref="chunk_len",
        )
        self.assertEqual(t.size_kind, "dynamic_ref")
        self.assertEqual(t.size_ref, "chunk_len")


if __name__ == "__main__":
    unittest.main()
