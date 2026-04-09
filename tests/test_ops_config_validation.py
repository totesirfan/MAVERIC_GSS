"""Tests for mission config validation and startup diagnostics.

Verifies:
  1. mission metadata is read and merged correctly
  2. Missing mission metadata produces a warning but doesn't crash
  3. Config validation catches invalid mission configs
  4. Startup diagnostics include mission metadata
"""

import unittest
import sys
import os
import logging
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.config import load_gss_config
from mav_gss_lib.mission_adapter import (
    load_mission_adapter,
    _merge_mission_metadata,
    MissionAdapter,
)
from mav_gss_lib.missions.maveric.nodes import init_nodes
from mav_gss_lib.missions.maveric.schema import load_command_defs


class TestMissionMetadata(unittest.TestCase):
    """Verify mission metadata reading and merging."""

    def test_maveric_example_metadata_exists(self):
        """MAVERIC mission metadata baseline is present in the package directory."""
        from mav_gss_lib.missions import maveric
        pkg_dir = os.path.dirname(os.path.abspath(maveric.__file__))
        yml_path = os.path.join(pkg_dir, "mission.example.yml")
        self.assertTrue(os.path.isfile(yml_path), f"Expected {yml_path} to exist")

    def test_maveric_example_metadata_has_required_fields(self):
        """Tracked MAVERIC mission metadata contains required fields."""
        import yaml
        from mav_gss_lib.missions import maveric
        pkg_dir = os.path.dirname(os.path.abspath(maveric.__file__))
        with open(os.path.join(pkg_dir, "mission.example.yml")) as f:
            data = yaml.safe_load(f)
        self.assertIn("mission_name", data)
        self.assertIn("nodes", data)
        self.assertIn("ptypes", data)
        self.assertIn("command_defs", data)
        self.assertEqual(data["mission_name"], "MAVERIC")

    def test_merge_fills_missing_keys(self):
        """_merge_mission_metadata fills keys absent from cfg."""
        cfg = {"general": {}}
        meta = {
            "mission_name": "TEST",
            "nodes": {0: "NONE", 1: "CPU"},
            "gs_node": "CPU",
        }
        _merge_mission_metadata(cfg, meta)
        self.assertEqual(cfg["nodes"], {0: "NONE", 1: "CPU"})
        self.assertEqual(cfg["general"]["mission_name"], "TEST")
        self.assertEqual(cfg["general"]["gs_node"], "CPU")

    def test_merge_does_not_override_operator_config(self):
        """Operator config values take precedence over mission metadata."""
        cfg = {
            "general": {"mission_name": "OPERATOR_NAME"},
            "nodes": {0: "ZERO", 99: "CUSTOM"},
        }
        meta = {
            "mission_name": "MISSION_NAME",
            "nodes": {0: "NONE", 1: "CPU"},
        }
        _merge_mission_metadata(cfg, meta)
        # Operator values win
        self.assertEqual(cfg["general"]["mission_name"], "OPERATOR_NAME")
        self.assertEqual(cfg["nodes"][0], "ZERO")
        self.assertEqual(cfg["nodes"][99], "CUSTOM")
        # Mission fills gaps
        self.assertEqual(cfg["nodes"][1], "CPU")


class TestStartupDiagnostics(unittest.TestCase):
    """Verify startup logging includes mission metadata."""

    def test_startup_log_includes_mission_info(self):
        """load_mission_adapter() logs mission name, id, API version."""
        cfg = load_gss_config()

        with self.assertLogs(level=logging.INFO) as cm:
            load_mission_adapter(cfg)

        log_output = "\n".join(cm.output)
        self.assertIn("Mission loaded", log_output)
        self.assertIn("MAVERIC", log_output)
        self.assertIn("adapter API v1", log_output)

    def test_missing_mission_metadata_does_not_crash(self):
        """load_mission_metadata returns {} gracefully for unknown mission ID."""
        from mav_gss_lib.mission_adapter import load_mission_metadata
        cfg = {"general": {"mission": "nonexistent_mission_xyz"}}
        result = load_mission_metadata(cfg)
        self.assertEqual(result, {})


class TestConfigDefaults(unittest.TestCase):
    def test_platform_defaults_have_no_mission_keys(self):
        """Platform _DEFAULTS should not contain mission-owned placeholders."""
        from mav_gss_lib.config import _DEFAULTS
        for key in ("nodes", "ptypes", "node_descriptions"):
            self.assertNotIn(key, _DEFAULTS,
                f"'{key}' should not be in platform _DEFAULTS")

    def test_platform_defaults_have_no_protocol_defaults(self):
        """AX.25/CSP defaults come from mission, not platform."""
        from mav_gss_lib.config import _DEFAULTS
        self.assertNotIn("ax25", _DEFAULTS)
        self.assertNotIn("csp", _DEFAULTS)

    def test_load_config_works_without_mission_keys(self):
        """load_gss_config() should work before mission metadata is loaded."""
        from mav_gss_lib.config import load_gss_config
        cfg = load_gss_config()
        self.assertIn("tx", cfg)
        self.assertIn("rx", cfg)
        self.assertIn("general", cfg)

    def test_mission_metadata_populates_mission_keys(self):
        """After load_mission_metadata, config has mission-owned keys."""
        from mav_gss_lib.config import load_gss_config
        from mav_gss_lib.mission_adapter import load_mission_metadata
        cfg = load_gss_config()
        load_mission_metadata(cfg)
        self.assertIn("nodes", cfg)
        self.assertIn("ptypes", cfg)
        self.assertIsInstance(cfg["nodes"], dict)
        self.assertTrue(len(cfg["nodes"]) > 0)

    def test_ax25_csp_populated_by_mission(self):
        """AX.25 and CSP config populated by mission metadata."""
        from mav_gss_lib.config import load_gss_config
        from mav_gss_lib.mission_adapter import load_mission_metadata
        cfg = load_gss_config()
        load_mission_metadata(cfg)
        self.assertIn("ax25", cfg)
        self.assertIn("csp", cfg)
        self.assertTrue(len(cfg["ax25"]) > 0)
        self.assertTrue(len(cfg["csp"]) > 0)


if __name__ == "__main__":
    unittest.main()
