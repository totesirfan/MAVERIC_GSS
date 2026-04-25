import unittest
from dataclasses import dataclass
from pathlib import Path

from mav_gss_lib.platform.spec.errors import MissingPluginError
from mav_gss_lib.platform.spec.runtime import DeclarativeWalker
from mav_gss_lib.platform.spec.yaml_parse import (
    parse_yaml,
    parse_yaml_for_tooling,
)


@dataclass(frozen=True, slots=True)
class _Pkt:
    args_raw: bytes
    header: dict


FIXTURE = Path(__file__).parent / "fixtures" / "spec" / "minimal_mission.yml"


class TestYamlParser(unittest.TestCase):
    def test_parse_yaml_returns_mission_with_built_ins_plus_declared(self):
        m = parse_yaml(FIXTURE, plugins={})
        self.assertEqual(m.id, "testmission")
        self.assertEqual(m.name, "Test Mission")
        # Built-in u8 visible
        self.assertIn("u8", m.parameter_types)
        # Declared types visible
        self.assertIn("V_volts", m.parameter_types)
        self.assertIn("GncMode", m.parameter_types)
        # Containers + meta-commands present
        self.assertIn("eps_hk", m.sequence_containers)
        self.assertIn("gnc_get_mode", m.meta_commands)

    def test_parse_yaml_extract_path_emits_fragment(self):
        m = parse_yaml(FIXTURE, plugins={})
        walker = DeclarativeWalker(m, plugins={})
        pkt = _Pkt(args_raw=b"1", header={"cmd_id": "gnc_get_mode", "ptype": "RES"})
        fragments = list(walker.extract(pkt, now_ms=42))
        self.assertEqual(len(fragments), 1)
        self.assertEqual(fragments[0].key, "GNC_MODE")
        self.assertEqual(fragments[0].value, 1)

    def test_parse_yaml_for_tooling_skips_plugin_check(self):
        # The minimal fixture has no python: refs, but the entry-point
        # difference is the plugins kwarg; tooling form must not require it.
        m = parse_yaml_for_tooling(FIXTURE)
        self.assertEqual(m.id, "testmission")

    def test_missing_plugin_rejected(self):
        # Inject a plugin reference into a copy of the fixture
        bad = FIXTURE.parent / "_with_missing_plugin.yml"
        text = FIXTURE.read_text()
        text = text.replace(
            "calibrator: {polynomial: [0, 0.001]}",
            "calibrator: {python: 'eps.compute_pwr'}",
        )
        bad.write_text(text)
        try:
            with self.assertRaises(MissingPluginError):
                parse_yaml(bad, plugins={})
        finally:
            bad.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
