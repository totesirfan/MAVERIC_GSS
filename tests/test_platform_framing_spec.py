"""FramingSpec parser tests."""
import unittest
from pathlib import Path
from textwrap import dedent

from mav_gss_lib.platform.spec import parse_framing_section, parse_yaml_for_tooling


class FramingSpecParserTests(unittest.TestCase):
    def test_parses_minimal_chain(self):
        spec = parse_framing_section({
            "uplink": {
                "chain": [
                    {"framer": "csp_v1", "config_ref": "csp"},
                    {"framer": "asm_golay"},
                ],
            },
        })
        self.assertIsNotNone(spec)
        self.assertEqual(len(spec.uplink_chain), 2)
        self.assertEqual(spec.uplink_chain[0].framer, "csp_v1")
        self.assertEqual(spec.uplink_chain[0].config_ref, "csp")
        self.assertEqual(spec.uplink_chain[1].framer, "asm_golay")
        self.assertIsNone(spec.uplink_label)
        self.assertEqual(spec.accept_frame_types, ())
        self.assertEqual(spec.on_unexpected, "warn")

    def test_label_and_downlink(self):
        spec = parse_framing_section({
            "uplink": {"label": "ASM+Golay", "chain": [{"framer": "asm_golay"}]},
            "downlink": {"accept_frame_types": ["ASM+GOLAY"], "on_unexpected": "drop"},
        })
        self.assertEqual(spec.uplink_label, "ASM+Golay")
        self.assertEqual(spec.accept_frame_types, ("ASM+GOLAY",))
        self.assertEqual(spec.on_unexpected, "drop")

    def test_returns_none_when_absent(self):
        self.assertIsNone(parse_framing_section(None))

    def test_rejects_empty_chain(self):
        with self.assertRaises(ValueError):
            parse_framing_section({"uplink": {"chain": []}})

    def test_rejects_unknown_on_unexpected(self):
        with self.assertRaises(ValueError):
            parse_framing_section({
                "uplink": {"chain": [{"framer": "asm_golay"}]},
                "downlink": {"on_unexpected": "explode"},
            })

    def test_rejects_missing_framer_key(self):
        with self.assertRaises(ValueError):
            parse_framing_section({"uplink": {"chain": [{}]}})


class MissionDocumentFramingTests(unittest.TestCase):
    def test_mission_yaml_round_trip(self):
        p = Path("/tmp/test_mission_framing.yml")
        p.write_text(dedent("""
            schema_version: 1
            id: testmission
            name: "Test"
            header: {version: "0", date: "2026-04-26"}
            framing:
              uplink:
                label: "ASM+Golay"
                chain:
                  - framer: csp_v1
                    config_ref: csp
                  - framer: asm_golay
              downlink:
                accept_frame_types: [ASM+GOLAY]
        """).strip())
        try:
            mission = parse_yaml_for_tooling(p)
            self.assertIsNotNone(mission.framing)
            self.assertEqual(mission.framing.uplink_label, "ASM+Golay")
            self.assertEqual(mission.framing.accept_frame_types, ("ASM+GOLAY",))
            self.assertEqual(len(mission.framing.uplink_chain), 2)
        finally:
            p.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
