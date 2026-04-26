"""Container stale alarms + carrier index keyed on parameter.domain."""
from __future__ import annotations

import unittest

from mav_gss_lib.platform.alarms import AlarmSource, Severity
from mav_gss_lib.platform.alarms.evaluators.container import (
    ContainerStaleSpec, evaluate_containers, parameter_carrier_index,
    parse_specs_from_yaml, periodic_container_ids,
)


class TestContainerEvaluator(unittest.TestCase):
    def test_unmonitored_emits_nothing(self):
        spec = ContainerStaleSpec("eps_hk", "EPS HK", 30000, 0, 0)
        self.assertEqual(evaluate_containers({"eps_hk": spec}, {}, now_ms=10**6), [])

    def test_unseeded_arrival_raises_keyerror(self):
        # The caller (lifespan startup) must seed last_arrival_ms[cid]=now_ms
        # for every monitored container. Failing to seed is a programming
        # error — the evaluator surfaces it loudly rather than guessing
        # whether the container is fresh.
        spec = ContainerStaleSpec("eps_hk", "EPS HK", 30000, 1_800_000, 43_200_000)
        with self.assertRaises(KeyError):
            evaluate_containers({"eps_hk": spec}, {}, now_ms=10**6)

    def test_seeded_fresh_emits_clear(self):
        spec = ContainerStaleSpec("eps_hk", "EPS HK", 30000, 1_800_000, 43_200_000)
        v = evaluate_containers({"eps_hk": spec}, {"eps_hk": 10**6}, now_ms=10**6)[0]
        self.assertIsNone(v.severity)

    def test_warning_band(self):
        spec = ContainerStaleSpec("eps_hk", "EPS HK", 30000,
                                  warning_after_ms=1_800_000, critical_after_ms=43_200_000)
        v = evaluate_containers({"eps_hk": spec},
                                {"eps_hk": 10**9 - 2_000_000}, now_ms=10**9)[0]
        self.assertEqual(v.severity, Severity.WARNING)
        self.assertEqual(v.id, "container.eps_hk.stale")
        self.assertEqual(v.source, AlarmSource.CONTAINER)

    def test_critical_band(self):
        spec = ContainerStaleSpec("eps_hk", "EPS HK", 30000,
                                  warning_after_ms=1_800_000, critical_after_ms=43_200_000)
        v = evaluate_containers({"eps_hk": spec},
                                {"eps_hk": 10**9 - 50_000_000}, now_ms=10**9)[0]
        self.assertEqual(v.severity, Severity.CRITICAL)


class TestSpecParsing(unittest.TestCase):
    def test_only_with_stale_block_is_monitored(self):
        yaml_dict = {
            "eps_hk": {
                "domain": "eps", "expected_period_ms": 30000,
                "stale": {"warning_after_ms": 1_800_000, "critical_after_ms": 43_200_000}
            },
            "reg_M0_RATE": {"domain": "gnc"},
        }
        specs = parse_specs_from_yaml(yaml_dict)
        self.assertTrue(specs["eps_hk"].monitored)
        self.assertFalse(specs["reg_M0_RATE"].monitored)


class TestParameterCarrierIndex(unittest.TestCase):
    def test_keyed_on_parameter_domain_not_container_domain(self):
        """tlm_beacon container has domain=spacecraft; parameters inside
        carry their own domain (gnc.RATE etc). The index must use the
        parameter-resolved name, matching ParameterCache.apply keys."""
        yaml_dict = {
            "tlm_beacon": {
                "domain": "spacecraft",
                "entry_list": [{"name": "RATE"}, {"name": "MAG"}],
            },
        }
        # Resolver: parameter_name -> parameter-level domain
        resolver = {"RATE": "gnc", "MAG": "gnc"}
        idx = parameter_carrier_index(yaml_dict, periodic_only={"tlm_beacon"},
                                      parameter_domain=resolver)
        # Cache stores RATE under "gnc.RATE" — index must agree
        self.assertIn("gnc.RATE", idx)
        self.assertEqual(idx["gnc.RATE"], {"tlm_beacon"})

    def test_falls_back_to_container_domain_when_parameter_missing(self):
        yaml_dict = {
            "eps_hk": {"domain": "eps", "entry_list": [{"name": "V_BUS"}]},
        }
        resolver = {}  # no parameter-level override
        idx = parameter_carrier_index(yaml_dict, periodic_only={"eps_hk"},
                                      parameter_domain=resolver)
        self.assertEqual(idx["eps.V_BUS"], {"eps_hk"})

    def test_periodic_filter_excludes_commanded_containers(self):
        yaml_dict = {
            "eps_hk": {"domain": "eps", "entry_list": [{"name": "V_BUS"}]},
            "reg_M0_V_BUS": {"domain": "eps", "entry_list": [{"name": "V_BUS"}]},
        }
        idx = parameter_carrier_index(yaml_dict, periodic_only={"eps_hk"},
                                      parameter_domain={})
        self.assertEqual(idx["eps.V_BUS"], {"eps_hk"})

    def test_multi_periodic_aggregates(self):
        yaml_dict = {
            "tlm_beacon": {"domain": "spacecraft",
                           "entry_list": [{"name": "V_BUS"}]},
            "eps_hk":     {"domain": "eps",
                           "entry_list": [{"name": "V_BUS"}]},
        }
        idx = parameter_carrier_index(yaml_dict,
                                      periodic_only={"tlm_beacon", "eps_hk"},
                                      parameter_domain={"V_BUS": "eps"})
        self.assertEqual(idx["eps.V_BUS"], {"tlm_beacon", "eps_hk"})

    def test_periodic_container_ids_helper(self):
        specs = {
            "eps_hk": ContainerStaleSpec("eps_hk", "EPS HK", 30000,
                                         1_800_000, 43_200_000),
            "tlm_beacon": ContainerStaleSpec("tlm_beacon", "BEACON", 60000,
                                             1_800_000, 43_200_000),
            "reg_M0_RATE": ContainerStaleSpec("reg_M0_RATE", "RATE", 0, 0, 0),
        }
        self.assertEqual(periodic_container_ids(specs), {"eps_hk", "tlm_beacon"})


if __name__ == "__main__":
    unittest.main()
