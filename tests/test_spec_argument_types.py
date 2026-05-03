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
        t = IntegerArgumentType(name="year_2digit_t", size_bits=8, valid_range=(0, 99))
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

    def test_valid_range_is_typed_int_tuple(self):
        # After 13f6176 the YAML parser rejects fractional bounds.
        # The dataclass annotation reinforces that contract for any
        # callers that build IntegerArgumentType directly (e.g. tests
        # or future programmatic mission construction). A static type
        # checker (mypy/pyright) will flag a tuple[float, float] here
        # — runtime stays loose because dataclasses don't enforce
        # annotations, but the YAML parse-time guard already covers
        # the YAML path and the annotation is the contract.
        import typing
        from mav_gss_lib.platform.spec.argument_types import IntegerArgumentType
        hints = typing.get_type_hints(IntegerArgumentType)
        self.assertEqual(hints["valid_range"], tuple[int, int] | None)


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


class TestYamlArgumentTypeRoundTrip(unittest.TestCase):
    """Round-trips through public parse_yaml so the test is decoupled
    from internal helper names.
    """

    def _write_minimal_mission(self, tmp_path, *, argument_types: dict) -> str:
        import yaml as _yaml
        doc = {
            "schema_version": 1,
            "id": "test_mission",
            "name": "test_mission",
            "header": {"version": "0", "date": "2026-01-01"},
            "parameter_types": {},
            "argument_types": argument_types,
            "parameters": {},
            "bitfield_types": {},
            "sequence_containers": {},
            "meta_commands": {},
        }
        path = tmp_path / "mission.yml"
        path.write_text(_yaml.safe_dump(doc))
        return str(path)

    def test_integer_argument_type_round_trips(self):
        import tempfile
        from pathlib import Path
        from mav_gss_lib.platform.spec.argument_types import IntegerArgumentType
        from mav_gss_lib.platform.spec.yaml_parse import parse_yaml
        with tempfile.TemporaryDirectory() as td:
            mp = self._write_minimal_mission(Path(td), argument_types={
                "year_2digit_t": {
                    "kind": "int", "size_bits": 8,
                    "valid_range": [0, 99],
                    "description": "2-digit year (e.g. 26 for 2026)",
                },
            })
            mission = parse_yaml(Path(mp), plugins={})
            t = mission.argument_types["year_2digit_t"]
            self.assertIsInstance(t, IntegerArgumentType)
            self.assertEqual(t.size_bits, 8)
            self.assertEqual(t.valid_range, (0.0, 99.0))
            self.assertIn("2-digit", t.description)

    def test_argument_type_with_valid_values(self):
        import tempfile
        from pathlib import Path
        from mav_gss_lib.platform.spec.yaml_parse import parse_yaml
        with tempfile.TemporaryDirectory() as td:
            mp = self._write_minimal_mission(Path(td), argument_types={
                "ops_stage_t": {
                    "kind": "int", "size_bits": 8,
                    "valid_values": [0, 1, 2],
                },
            })
            mission = parse_yaml(Path(mp), plugins={})
            t = mission.argument_types["ops_stage_t"]
            self.assertEqual(t.valid_values, (0, 1, 2))

    def test_built_in_argument_types_present_after_parse(self):
        import tempfile
        from pathlib import Path
        from mav_gss_lib.platform.spec.yaml_parse import parse_yaml
        with tempfile.TemporaryDirectory() as td:
            mp = self._write_minimal_mission(Path(td), argument_types={})
            mission = parse_yaml(Path(mp), plugins={})
            for name in ("u8", "u16", "u32", "ascii_token"):
                self.assertIn(name, mission.argument_types,
                              f"built-in {name} missing from argument_types after parse")

    def test_to_end_string_arg_must_be_last(self):
        import tempfile, yaml as _yaml
        from pathlib import Path
        from mav_gss_lib.platform.spec.errors import ParseError
        from mav_gss_lib.platform.spec.yaml_parse import parse_yaml
        with tempfile.TemporaryDirectory() as td:
            doc = {
                "schema_version": 1,
                "id": "t", "name": "t",
                "header": {"version": "0", "date": "2026-01-01"},
                "parameter_types": {},
                "argument_types": {"BlobArg": {"kind": "string", "encoding": "to_end"}},
                "parameters": {},
                "bitfield_types": {},
                "sequence_containers": {},
                "meta_commands": {"bad_cmd": {
                    "packet": {"echo": "NONE", "ptype": "CMD"},
                    "argument_list": [
                        {"name": "blob", "type": "BlobArg"},
                        {"name": "trailing", "type": "u8"},
                    ],
                }},
            }
            p = Path(td) / "mission.yml"
            p.write_text(_yaml.safe_dump(doc))
            with self.assertRaises(ParseError) as ctx:
                parse_yaml(p, plugins={})
            self.assertIn("to_end", str(ctx.exception))
            self.assertIn("LAST", str(ctx.exception))


def _write_mission_with_arg_type(td: str, arg_type_def: dict):
    """Helper for ParseError tests — minimal mission with one custom arg type."""
    import yaml as _yaml
    from pathlib import Path
    doc = {
        "schema_version": 1,
        "id": "t", "name": "t",
        "header": {"version": "0", "date": "2026-01-01"},
        "parameter_types": {},
        "argument_types": {"BadArg": arg_type_def},
        "parameters": {},
        "bitfield_types": {},
        "sequence_containers": {},
        "meta_commands": {},
    }
    p = Path(td) / "mission.yml"
    p.write_text(_yaml.safe_dump(doc))
    return p


class TestValidRangeBoundedBySizeBits(unittest.TestCase):
    """Parse-time guard: valid_range must be a SUBSET of the representable
    range derived from size_bits/signed. Otherwise the type would silently
    accept values that overflow at encode.
    """

    def test_valid_range_outside_unsigned_size_bits_rejected(self):
        import tempfile
        from mav_gss_lib.platform.spec.errors import ParseError
        from mav_gss_lib.platform.spec.yaml_parse import parse_yaml
        with tempfile.TemporaryDirectory() as td:
            p = _write_mission_with_arg_type(
                td, {"kind": "int", "size_bits": 8, "valid_range": [0, 1000]},
            )
            with self.assertRaises(ParseError) as ctx:
                parse_yaml(p, plugins={})
            msg = str(ctx.exception)
            self.assertIn("BadArg", msg)
            self.assertIn("valid_range", msg)
            self.assertIn("[0, 255]", msg)

    def test_valid_range_outside_signed_size_bits_rejected(self):
        import tempfile
        from mav_gss_lib.platform.spec.errors import ParseError
        from mav_gss_lib.platform.spec.yaml_parse import parse_yaml
        with tempfile.TemporaryDirectory() as td:
            p = _write_mission_with_arg_type(
                td, {"kind": "int", "size_bits": 8, "signed": True,
                     "valid_range": [-200, 50]},
            )
            with self.assertRaises(ParseError) as ctx:
                parse_yaml(p, plugins={})
            self.assertIn("[-128, 127]", str(ctx.exception))

    def test_valid_range_within_size_bits_accepted(self):
        import tempfile
        from mav_gss_lib.platform.spec.yaml_parse import parse_yaml
        with tempfile.TemporaryDirectory() as td:
            p = _write_mission_with_arg_type(
                td, {"kind": "int", "size_bits": 8, "valid_range": [0, 99]},
            )
            mission = parse_yaml(p, plugins={})
            self.assertIn("BadArg", mission.argument_types)

    def test_inverted_valid_range_rejected(self):
        import tempfile
        from mav_gss_lib.platform.spec.errors import ParseError
        from mav_gss_lib.platform.spec.yaml_parse import parse_yaml
        with tempfile.TemporaryDirectory() as td:
            p = _write_mission_with_arg_type(
                td, {"kind": "int", "size_bits": 8, "valid_range": [50, 10]},
            )
            with self.assertRaises(ParseError) as ctx:
                parse_yaml(p, plugins={})
            self.assertIn("inverted", str(ctx.exception).lower())

    def test_valid_values_outside_size_bits_rejected(self):
        import tempfile
        from mav_gss_lib.platform.spec.errors import ParseError
        from mav_gss_lib.platform.spec.yaml_parse import parse_yaml
        with tempfile.TemporaryDirectory() as td:
            p = _write_mission_with_arg_type(
                td, {"kind": "int", "size_bits": 8, "valid_values": [0, 1, 999]},
            )
            with self.assertRaises(ParseError) as ctx:
                parse_yaml(p, plugins={})
            msg = str(ctx.exception)
            self.assertIn("999", msg)
            self.assertIn("[0, 255]", msg)

    def test_inverted_float_valid_range_rejected(self):
        import tempfile
        from mav_gss_lib.platform.spec.errors import ParseError
        from mav_gss_lib.platform.spec.yaml_parse import parse_yaml
        with tempfile.TemporaryDirectory() as td:
            p = _write_mission_with_arg_type(
                td, {"kind": "float", "size_bits": 32, "valid_range": [1.5, -1.5]},
            )
            with self.assertRaises(ParseError) as ctx:
                parse_yaml(p, plugins={})
            self.assertIn("inverted", str(ctx.exception).lower())

    def test_well_formed_float_valid_range_accepted(self):
        import tempfile
        from mav_gss_lib.platform.spec.yaml_parse import parse_yaml
        with tempfile.TemporaryDirectory() as td:
            p = _write_mission_with_arg_type(
                td, {"kind": "float", "size_bits": 32, "valid_range": [-1.0, 1.0]},
            )
            mission = parse_yaml(p, plugins={})
            self.assertIn("BadArg", mission.argument_types)

    def test_fractional_int_valid_range_rejected(self):
        # Integer wires canonicalize via str(int(value)). A type with
        # valid_range=[0.5, 2.5] would round at validate-time and silently
        # accept values outside the author's intent (e.g. 0 with truncated
        # bounds [0, 2]). Reject at parse time.
        import tempfile
        from mav_gss_lib.platform.spec.errors import ParseError
        from mav_gss_lib.platform.spec.yaml_parse import parse_yaml
        with tempfile.TemporaryDirectory() as td:
            p = _write_mission_with_arg_type(
                td, {"kind": "int", "size_bits": 8, "valid_range": [0.5, 2.5]},
            )
            with self.assertRaises(ParseError) as ctx:
                parse_yaml(p, plugins={})
            self.assertIn("fractional", str(ctx.exception).lower())


class TestCommandArgTypeRefValidation(unittest.TestCase):
    def _write_mission(self, tmp_path, *, parameter_types, argument_types, meta_commands):
        import yaml as _yaml
        doc = {
            "schema_version": 1,
            "id": "t", "name": "t",
            "header": {"version": "0", "date": "2026-01-01"},
            "parameter_types": parameter_types,
            "argument_types": argument_types,
            "parameters": {},
            "bitfield_types": {},
            "sequence_containers": {},
            "meta_commands": meta_commands,
        }
        path = tmp_path / "mission.yml"
        path.write_text(_yaml.safe_dump(doc))
        return str(path)

    def test_command_arg_referencing_parameter_only_type_is_rejected(self):
        import tempfile
        from pathlib import Path
        from mav_gss_lib.platform.spec.errors import UnknownTypeRef
        from mav_gss_lib.platform.spec.yaml_parse import parse_yaml
        with tempfile.TemporaryDirectory() as td:
            mp = self._write_mission(Path(td),
                parameter_types={"only_tm_t": {"kind": "int", "size_bits": 8}},
                argument_types={},
                meta_commands={"bad_cmd": {
                    "packet": {"echo": "NONE", "ptype": "CMD"},
                    "argument_list": [{"name": "x", "type": "only_tm_t"}],
                }},
            )
            with self.assertRaises(UnknownTypeRef):
                parse_yaml(Path(mp), plugins={})

    def test_command_arg_referencing_built_in_argument_type_passes(self):
        import tempfile
        from pathlib import Path
        from mav_gss_lib.platform.spec.yaml_parse import parse_yaml
        with tempfile.TemporaryDirectory() as td:
            mp = self._write_mission(Path(td),
                parameter_types={},
                argument_types={},
                meta_commands={"good_cmd": {
                    "packet": {"echo": "NONE", "ptype": "CMD"},
                    "argument_list": [
                        {"name": "x", "type": "u8"},
                        {"name": "tag", "type": "ascii_token"},
                    ],
                }},
            )
            mission = parse_yaml(Path(mp), plugins={})
            self.assertIn("good_cmd", mission.meta_commands)

    def test_argument_type_redeclaring_built_in_is_rejected(self):
        import tempfile
        from pathlib import Path
        from mav_gss_lib.platform.spec.errors import ParseError
        from mav_gss_lib.platform.spec.yaml_parse import parse_yaml
        with tempfile.TemporaryDirectory() as td:
            mp = self._write_mission(Path(td),
                parameter_types={},
                argument_types={"u8": {"kind": "int", "size_bits": 8, "valid_range": [0, 5]}},
                meta_commands={},
            )
            with self.assertRaises(ParseError) as ctx:
                parse_yaml(Path(mp), plugins={})
            self.assertIn("u8", str(ctx.exception))

    def test_command_arg_typed_as_bitfield_is_rejected(self):
        import tempfile
        from pathlib import Path
        from mav_gss_lib.platform.spec.errors import UnknownTypeRef
        from mav_gss_lib.platform.spec.yaml_parse import parse_yaml
        import yaml as _yaml
        with tempfile.TemporaryDirectory() as td:
            doc = {
                "schema_version": 1,
                "id": "t", "name": "t",
                "header": {"version": "0", "date": "2026-01-01"},
                "parameter_types": {},
                "argument_types": {},
                "parameters": {},
                "bitfield_types": {
                    "MyReg": {
                        "size_bits": 32, "byte_order": "little",
                        "entry_list": [{"name": "MODE", "bits": [0, 6], "kind": "uint"}],
                    },
                },
                "sequence_containers": {},
                "meta_commands": {"bad_cmd": {
                    "packet": {"echo": "NONE", "ptype": "CMD"},
                    "argument_list": [{"name": "reg", "type": "MyReg"}],
                }},
            }
            path = Path(td) / "mission.yml"
            path.write_text(_yaml.safe_dump(doc))
            with self.assertRaises(UnknownTypeRef):
                parse_yaml(path, plugins={})


if __name__ == "__main__":
    unittest.main()
