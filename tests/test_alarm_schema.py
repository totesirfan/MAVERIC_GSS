"""Parse inline `alarm:` blocks from mission.yml `parameters:` entries."""
from __future__ import annotations

import unittest

from mav_gss_lib.platform.alarms import Severity
from mav_gss_lib.platform.alarms.schema import (
    EnumRule, FlagsRule, NormRule, PythonRule, StaticRule, parse_alarm_rules,
)


class TestStaticRule(unittest.TestCase):
    def test_static(self):
        rules = parse_alarm_rules({"alarm": {"static": {
            "warning":  {"min": -20, "max": 60},
            "critical": {"min": -25, "max": 70},
        }}})
        self.assertEqual(len(rules), 1)
        self.assertIsInstance(rules[0], StaticRule)
        self.assertEqual(rules[0].bands[Severity.WARNING], (-20.0, 60.0))
        self.assertEqual(rules[0].bands[Severity.CRITICAL], (-25.0, 70.0))
        self.assertIsNone(rules[0].on)

    def test_static_field_string_selector(self):
        rules = parse_alarm_rules({"alarm": {
            "on": "celsius",
            "static": {"warning": {"min": -20, "max": 60}},
        }})
        self.assertEqual(rules[0].on, "celsius")

    def test_static_integer_selector(self):
        rules = parse_alarm_rules({"alarm": {
            "on": 2,
            "static": {"warning": {"min": 555, "max": 645}},
        }})
        self.assertEqual(rules[0].on, 2)

    def test_list_form(self):
        rules = parse_alarm_rules({"alarm": [
            {"on": "celsius", "static": {"critical": {"min": -25, "max": 70}}},
            {"on": "comm_fault", "enum": {"true": "critical"}},
        ]})
        self.assertEqual(len(rules), 2)
        self.assertIsInstance(rules[0], StaticRule)
        self.assertIsInstance(rules[1], EnumRule)


class TestNormRule(unittest.TestCase):
    def test_norm_max_only(self):
        rules = parse_alarm_rules({"alarm": {"norm": {
            "warning":  {"max": 5.5},
            "critical": {"max": 6.283},
        }}})
        self.assertIsInstance(rules[0], NormRule)
        self.assertEqual(rules[0].bands[Severity.CRITICAL], (None, 6.283))

    def test_norm_min_max(self):
        rules = parse_alarm_rules({"alarm": {"norm": {
            "warning":  {"min": 52000, "max": 73000},
            "critical": {"min": 50000, "max": 75000},
        }}})
        self.assertEqual(rules[0].bands[Severity.CRITICAL], (50000.0, 75000.0))


class TestEnumRule(unittest.TestCase):
    def test_enum(self):
        rules = parse_alarm_rules({"alarm": {"enum": {
            "0": None, "default": "critical",
        }}})
        self.assertEqual(rules[0].map["0"], None)
        self.assertEqual(rules[0].default, Severity.CRITICAL)


class TestFlagsRule(unittest.TestCase):
    def test_flags_critical_if_any(self):
        rules = parse_alarm_rules({"alarm": {"flags": {
            "critical_if_any": ["CMG0", "CMG1", "MTQ0"],
        }}})
        self.assertEqual(rules[0].critical_if_any, ("CMG0", "CMG1", "MTQ0"))

    def test_flags_warning_if_clear(self):
        rules = parse_alarm_rules({"alarm": {"flags": {
            "critical_if_any": ["HERR"],
            "warning_if_clear": ["EKF"],
        }}})
        self.assertEqual(rules[0].warning_if_clear, ("EKF",))


class TestPythonRule(unittest.TestCase):
    def test_python(self):
        rules = parse_alarm_rules({"alarm": {"python": "maveric.alarm.adcs_tmp"}})
        self.assertEqual(rules[0].callable_ref, "maveric.alarm.adcs_tmp")


class TestPersistenceLatching(unittest.TestCase):
    def test_carries(self):
        rules = parse_alarm_rules({"alarm": {
            "static": {"warning": {"max": 60}},
            "persistence": 3, "latched": True,
        }})
        self.assertEqual(rules[0].persistence, 3)
        self.assertTrue(rules[0].latched)

    def test_defaults(self):
        rules = parse_alarm_rules({"alarm": {"static": {"warning": {"max": 60}}}})
        self.assertEqual(rules[0].persistence, 1)
        self.assertFalse(rules[0].latched)


class TestNoAlarm(unittest.TestCase):
    def test_no_alarm_block(self):
        self.assertEqual(parse_alarm_rules({}), ())
        self.assertEqual(parse_alarm_rules({"alarm": None}), ())


class TestRejectsAmbiguous(unittest.TestCase):
    def test_static_and_norm_in_same_item_raises(self):
        with self.assertRaises(ValueError):
            parse_alarm_rules({"alarm": {
                "static": {"warning": {"max": 60}},
                "norm":   {"warning": {"max": 5}},
            }})


if __name__ == "__main__":
    unittest.main()
