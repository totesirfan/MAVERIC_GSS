import unittest

from mav_gss_lib.platform.spec.commands import Argument, MetaCommand


class TestArgument(unittest.TestCase):
    def test_argument_default_optional_fields(self):
        a = Argument(name="axis", type_ref="i8")
        self.assertEqual(a.description, "")
        self.assertIsNone(a.valid_range)
        self.assertIsNone(a.valid_values)
        self.assertIsNone(a.invalid_values)
        self.assertFalse(a.important)

    def test_argument_carries_valid_range(self):
        a = Argument(name="axis", type_ref="i8", valid_range=(0, 5))
        self.assertEqual(a.valid_range, (0, 5))


class TestMetaCommand(unittest.TestCase):
    def test_meta_command_id_and_packet_defaults(self):
        m = MetaCommand(id="gnc_get_mode")
        self.assertEqual(m.id, "gnc_get_mode")
        self.assertEqual(dict(m.packet), {})
        self.assertEqual(dict(m.allowed_packet), {})
        self.assertFalse(m.guard)
        self.assertFalse(m.no_response)
        self.assertEqual(m.argument_list, ())
        self.assertEqual(m.rx_args, ())

    def test_meta_command_with_argument_list(self):
        m = MetaCommand(
            id="cam_capture",
            packet={"echo": "NONE", "ptype": "CMD"},
            allowed_packet={"dest": ("HLNV", "ASTR")},
            argument_list=(
                Argument(name="count", type_ref="u8"),
                Argument(name="interval_s", type_ref="u16"),
            ),
            rx_count_from="count",
        )
        self.assertEqual(len(m.argument_list), 2)
        self.assertEqual(m.rx_count_from, "count")


if __name__ == "__main__":
    unittest.main()
