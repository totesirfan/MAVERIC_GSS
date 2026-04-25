import unittest
from pathlib import Path

import pydantic
import yaml

from mav_gss_lib.platform.spec.yaml_schema import MissionDocument


class TestYamlSchema(unittest.TestCase):
    def setUp(self):
        self.fixture = Path(__file__).parent / "fixtures" / "spec" / "minimal_mission.yml"

    def test_minimal_mission_validates(self):
        with self.fixture.open() as fh:
            data = yaml.safe_load(fh)
        doc = MissionDocument.model_validate(data)
        self.assertEqual(doc.id, "testmission")
        self.assertEqual(doc.schema_version, 1)
        self.assertIn("V_volts", doc.parameter_types)
        self.assertIn("eps_hk", doc.sequence_containers)

    def test_rejects_unknown_parameter_type_kind(self):
        bad = {
            "schema_version": 1, "id": "x", "name": "x",
            "header": {"version": "1.0.0", "date": "2026-04-25"},
            "parameter_types": {"BadType": {"kind": "wat", "size_bits": 8}},
            "parameters": {}, "sequence_containers": {}, "meta_commands": {},
        }
        with self.assertRaises(pydantic.ValidationError):
            MissionDocument.model_validate(bad)

    def test_rejects_missing_id(self):
        bad = {
            "schema_version": 1, "name": "x",
            "header": {"version": "1.0.0", "date": "2026-04-25"},
            "parameter_types": {}, "parameters": {},
            "sequence_containers": {}, "meta_commands": {},
        }
        with self.assertRaises(pydantic.ValidationError):
            MissionDocument.model_validate(bad)

    def test_rejects_polynomial_with_string_coefficient(self):
        bad = {
            "schema_version": 1, "id": "x", "name": "x",
            "header": {"version": "1.0.0", "date": "2026-04-25"},
            "parameter_types": {
                "V": {
                    "kind": "int", "size_bits": 16, "signed": True,
                    "calibrator": {"polynomial": ["zero", 1]},
                },
            },
            "parameters": {}, "sequence_containers": {}, "meta_commands": {},
        }
        with self.assertRaises(pydantic.ValidationError):
            MissionDocument.model_validate(bad)


if __name__ == "__main__":
    unittest.main()
