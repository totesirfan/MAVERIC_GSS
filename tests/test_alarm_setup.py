"""build_alarm_environment + compile_parameter_rules + entry walker."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from mav_gss_lib.platform.alarms.registry import AlarmRegistry
from mav_gss_lib.platform.alarms.setup import (
    build_alarm_environment, compile_parameter_rules,
)


class TestCompileParameterRules(unittest.TestCase):
    def test_skips_invalid_rule_does_not_abort(self):
        spec_root = MagicMock()
        good = MagicMock(); good.name = "RATE"; good.domain = "gnc"
        good.alarm = {"static": {"warning": {"max": 5.0}}}
        bad = MagicMock(); bad.name = "BORK"; bad.domain = "gnc"
        bad.alarm = {"static": {"warning": {"max": 1}}, "norm": {"warning": {"max": 1}}}
        spec_root.parameters = {"RATE": good, "BORK": bad}
        rules = compile_parameter_rules(spec_root)
        self.assertIn("gnc.RATE", rules)
        self.assertNotIn("gnc.BORK", rules)


class TestBuildAlarmEnvironment(unittest.TestCase):
    def test_seeds_and_indexes(self):
        spec_root = MagicMock()
        c = MagicMock(); c.domain = "spacecraft"
        c.expected_period_ms = 60000
        c.stale = {"warning_after_ms": 1_800_000, "critical_after_ms": 43_200_000}
        rate_entry = MagicMock(); rate_entry.name = "RATE"
        c.entry_list = [rate_entry]
        spec_root.sequence_containers = {"tlm_beacon": c}
        rate_param = MagicMock(); rate_param.name = "RATE"; rate_param.domain = "gnc"
        rate_param.alarm = None
        spec_root.parameters = {"RATE": rate_param}

        registry = AlarmRegistry()
        last_arrival = {}
        env = build_alarm_environment(
            spec_root, registry, last_arrival, now_ms=10**6,
            mission_alarm_plugins={},
        )
        self.assertIn("tlm_beacon", env.container_specs)
        self.assertEqual(last_arrival["tlm_beacon"], 10**6)
        # Carrier index keys by parameter.domain ("gnc"), not container.domain
        # ("spacecraft"). RATE has no alarm declared, so it's still tracked
        # in the carrier index but produces no rules entry.
        self.assertNotIn("gnc.RATE", env.parameter_rules)


if __name__ == "__main__":
    unittest.main()
