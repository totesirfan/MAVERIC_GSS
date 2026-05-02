import unittest


class TestPublicApi(unittest.TestCase):
    def test_top_level_imports_resolve(self):
        from mav_gss_lib.platform.spec import (
            AsciiArgumentEncoder,
            BUILT_IN_PARAMETER_TYPES,
            BUILT_IN_ARGUMENT_TYPES,
            ArgumentType,
            IntegerArgumentType,
            FloatArgumentType,
            StringArgumentType,
            CommandHeader,
            DeclarativeWalker,
            Mission,
            MissionDocument,
            PacketCodec,
            WalkerPacket,
            build_declarative_command_ops,
            parse_yaml,
            parse_yaml_for_tooling,
        )
        self.assertTrue(callable(parse_yaml))
        self.assertTrue(callable(parse_yaml_for_tooling))
        self.assertTrue(callable(build_declarative_command_ops))
        # ArgumentType should be a usable union (Python's `|` syntax in 3.10+)
        self.assertIsNotNone(ArgumentType)
        # Built-ins should be a non-empty mapping
        self.assertIn("u8", BUILT_IN_ARGUMENT_TYPES)
        self.assertIn("ascii_token", BUILT_IN_ARGUMENT_TYPES)
        self.assertTrue(hasattr(AsciiArgumentEncoder(types={}), "encode_ascii"))
        self.assertFalse(hasattr(AsciiArgumentEncoder(types={}), "decode_ascii"),
                         "AsciiArgumentEncoder must be encode-only by design")

    def test_platform_exposes_spec_namespace(self):
        from mav_gss_lib.platform import spec
        self.assertTrue(hasattr(spec, "parse_yaml"))


if __name__ == "__main__":
    unittest.main()
