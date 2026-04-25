import unittest

from mav_gss_lib.platform.spec.containers import (
    Comparison,
    Entry,
    PagedFrameEntry,
    ParameterRefEntry,
    RepeatEntry,
    RestrictionCriteria,
    SequenceContainer,
)


class TestRestrictionCriteria(unittest.TestCase):
    def test_comparison_default_op_is_equality(self):
        c = Comparison(parameter_ref="cmd_id", value="eps_hk")
        self.assertEqual(c.operator, "==")

    def test_restriction_criteria_default_empty_tuples(self):
        rc = RestrictionCriteria()
        self.assertEqual(rc.packet, ())
        self.assertEqual(rc.parent_args, ())


class TestEntries(unittest.TestCase):
    def test_parameter_ref_entry_default_emit_true(self):
        e = ParameterRefEntry(name="V_BUS", type_ref="V_volts")
        self.assertTrue(e.emit)
        self.assertIsNone(e.parameter_ref)

    def test_repeat_entry_count_kind_to_end(self):
        inner = ParameterRefEntry(name="slot", type_ref="ascii_token")
        re = RepeatEntry(entry=inner, count_kind="to_end")
        self.assertEqual(re.count_kind, "to_end")
        self.assertIsNone(re.count_fixed)

    def test_paged_frame_defaults(self):
        p = PagedFrameEntry(base_container_ref="mtq_get_1_res")
        self.assertEqual(p.marker_separator, ",")
        self.assertEqual(p.dispatch_keys, ("module", "register"))
        self.assertEqual(p.on_unknown_register, "skip")


class TestSequenceContainer(unittest.TestCase):
    def test_default_layout_is_ascii_tokens(self):
        c = SequenceContainer(name="x", entry_list=())
        self.assertEqual(c.layout, "ascii_tokens")

    def test_default_on_short_payload_is_skip(self):
        c = SequenceContainer(name="x", entry_list=())
        self.assertEqual(c.on_short_payload, "skip")

    def test_default_on_decode_error_is_raise(self):
        c = SequenceContainer(name="x", entry_list=())
        self.assertEqual(c.on_decode_error, "raise")


if __name__ == "__main__":
    unittest.main()
