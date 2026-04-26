"""Parameter evaluator: dispatch over rule kinds, with field selector handling
both dict keys and integer sequence indices."""
from __future__ import annotations

import unittest

from mav_gss_lib.platform.alarms import Severity
from mav_gss_lib.platform.alarms.evaluators.parameter import (
    PluginRegistry, evaluate_parameter,
)
from mav_gss_lib.platform.alarms.schema import parse_alarm_rules


def _rules(spec):
    return parse_alarm_rules({"alarm": spec})


class TestStatic(unittest.TestCase):
    def test_inside_no_alarm(self):
        rules = _rules({"static": {"warning": {"min": -20, "max": 60},
                                   "critical": {"min": -25, "max": 70}}})
        v = evaluate_parameter("param.gnc.ADCS_TMP", rules, 25)
        self.assertIsNone(v[0].severity)

    def test_warning(self):
        rules = _rules({"static": {"warning": {"min": -20, "max": 60},
                                   "critical": {"min": -25, "max": 70}}})
        v = evaluate_parameter("param.gnc.ADCS_TMP", rules, 65)
        self.assertEqual(v[0].severity, Severity.WARNING)

    def test_critical(self):
        rules = _rules({"static": {"warning": {"min": -20, "max": 60},
                                   "critical": {"min": -25, "max": 70}}})
        v = evaluate_parameter("param.gnc.ADCS_TMP", rules, 80)
        self.assertEqual(v[0].severity, Severity.CRITICAL)


class TestNorm(unittest.TestCase):
    def test_norm_warning(self):
        rules = _rules({"norm": {"warning": {"max": 5.5},
                                 "critical": {"max": 6.283}}})
        self.assertIsNone(evaluate_parameter("p", rules, [3.0, 4.0, 0.0])[0].severity)
        self.assertEqual(
            evaluate_parameter("p", rules, [4.0, 4.0, 0.0])[0].severity,
            Severity.WARNING,
        )


class TestEnum(unittest.TestCase):
    def test_enum_default(self):
        rules = _rules({"enum": {"0": None, "default": "critical"}})
        self.assertIsNone(evaluate_parameter("p", rules, 0)[0].severity)
        self.assertEqual(
            evaluate_parameter("p", rules, 5)[0].severity, Severity.CRITICAL)


class TestFieldSelectorString(unittest.TestCase):
    def test_dict_key_selector(self):
        rules = _rules({"on": "celsius",
                        "static": {"critical": {"min": -25, "max": 70}}})
        v = evaluate_parameter("p", rules, {"celsius": 80})
        self.assertEqual(v[0].severity, Severity.CRITICAL)

    def test_missing_key_no_alarm(self):
        rules = _rules({"on": "celsius",
                        "static": {"critical": {"min": -25, "max": 70}}})
        v = evaluate_parameter("p", rules, {"foo": 80})
        self.assertIsNone(v[0].severity)


class TestFieldSelectorInteger(unittest.TestCase):
    def test_sequence_index(self):
        # LLA: vec3, alarm on altitude (index 2)
        rules = _rules({"on": 2,
                        "static": {"warning": {"min": 555, "max": 645},
                                   "critical": {"min": 550, "max": 650}}})
        v = evaluate_parameter("p.gnc.LLA", rules, [45.0, -120.0, 540.0])
        self.assertEqual(v[0].severity, Severity.CRITICAL)
        v = evaluate_parameter("p.gnc.LLA", rules, [45.0, -120.0, 600.0])
        self.assertIsNone(v[0].severity)

    def test_index_out_of_range_no_alarm(self):
        rules = _rules({"on": 5,
                        "static": {"critical": {"min": 0, "max": 100}}})
        v = evaluate_parameter("p", rules, [1, 2, 3])
        self.assertIsNone(v[0].severity)

    def test_string_value_with_int_selector_no_alarm(self):
        rules = _rules({"on": 2,
                        "static": {"critical": {"max": 100}}})
        v = evaluate_parameter("p", rules, "abcdef")
        self.assertIsNone(v[0].severity)


class TestFlags(unittest.TestCase):
    def test_critical_if_any(self):
        rules = _rules({"flags": {"critical_if_any": ["CMG0", "MTQ0"]}})
        v = evaluate_parameter("p.gnc.ACT_ERR", rules,
                               {"CMG0": False, "MTQ0": True})
        self.assertEqual(v[0].severity, Severity.CRITICAL)
        self.assertIn("MTQ0", v[0].detail)

    def test_no_faults(self):
        rules = _rules({"flags": {"critical_if_any": ["CMG0"]}})
        v = evaluate_parameter("p.gnc.ACT_ERR", rules, {"CMG0": False})
        self.assertIsNone(v[0].severity)

    def test_warning_if_clear_with_explicit_false(self):
        rules = _rules({"flags": {"warning_if_clear": ["EKF"]}})
        v = evaluate_parameter("p", rules, {"EKF": False})
        self.assertEqual(v[0].severity, Severity.WARNING)

    def test_warning_if_clear_missing_key_no_alarm(self):
        # Missing key != cleared. A partial bitfield decode where some
        # flags are absent should NOT trip warning_if_clear.
        rules = _rules({"flags": {"warning_if_clear": ["EKF"]}})
        v = evaluate_parameter("p", rules, {"OTHER": True})
        self.assertIsNone(v[0].severity)


class TestPython(unittest.TestCase):
    def test_predicate(self):
        registry = PluginRegistry({"maveric.alarm.adcs_tmp": _adcs})
        rules = _rules({"python": "maveric.alarm.adcs_tmp"})
        v = evaluate_parameter("p", rules, {"celsius": 80}, plugins=registry)
        self.assertEqual(v[0].severity, Severity.CRITICAL)


def _adcs(value):
    c = value.get("celsius")
    if c is None:
        return None, ""
    if c > 70 or c < -25:
        return Severity.CRITICAL, f"{c}"
    if c > 60 or c < -20:
        return Severity.WARNING, f"{c}"
    return None, ""


class TestEventIdComposition(unittest.TestCase):
    def test_single_rule(self):
        rules = _rules({"static": {"critical": {"max": 70}}})
        v = evaluate_parameter("param.gnc.ADCS_TMP", rules, 80)
        self.assertEqual(v[0].id, "param.gnc.ADCS_TMP")

    def test_list_rules_use_field_in_id(self):
        rules = _rules([
            {"on": "celsius", "static": {"critical": {"max": 70}}},
            {"on": "comm_fault", "enum": {"true": "critical"}},
        ])
        ids = sorted(v.id for v in evaluate_parameter(
            "param.gnc.ADCS_TMP", rules, {"celsius": 80, "comm_fault": True}))
        self.assertEqual(ids, ["param.gnc.ADCS_TMP.celsius",
                               "param.gnc.ADCS_TMP.comm_fault"])


if __name__ == "__main__":
    unittest.main()
