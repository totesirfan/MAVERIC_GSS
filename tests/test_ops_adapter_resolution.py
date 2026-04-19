"""Tests for mission init hook, adapter resolution methods, and single-entry loader.

Verifies:
  1. init_mission() exists on mission packages and returns expected shape
  2. load_mission_adapter(cfg) works without cmd_defs param
  3. adapter.cmd_defs is populated by the loader
  4. Echo mission init_mission returns empty cmd_defs
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.mission_adapter import MissionAdapter, validate_adapter


class TestInitMission(unittest.TestCase):
    """Verify init_mission hook on mission packages."""

    def test_maveric_init_mission_returns_cmd_defs(self):
        """MAVERIC init_mission() returns cmd_defs and cmd_warn."""
        from mav_gss_lib.config import load_gss_config
        from mav_gss_lib.mission_adapter import load_mission_metadata
        from mav_gss_lib.missions.maveric import init_mission

        cfg = load_gss_config()
        load_mission_metadata(cfg)
        resources = init_mission(cfg)
        self.assertIn("cmd_defs", resources)
        self.assertIn("cmd_warn", resources)
        self.assertIsInstance(resources["cmd_defs"], dict)
        self.assertGreater(len(resources["cmd_defs"]), 0)

    def test_echo_init_mission_returns_empty(self):
        """Echo init_mission() returns empty cmd_defs."""
        from tests.echo_mission import init_mission
        resources = init_mission({})
        self.assertEqual(resources["cmd_defs"], {})
        self.assertIsNone(resources["cmd_warn"])

    def test_load_mission_adapter_single_arg(self):
        """load_mission_adapter(cfg) works with only cfg (no cmd_defs)."""
        from mav_gss_lib.config import load_gss_config
        from mav_gss_lib.mission_adapter import load_mission_adapter

        cfg = load_gss_config()
        adapter = load_mission_adapter(cfg)
        self.assertIsInstance(adapter, MissionAdapter)
        self.assertIsInstance(adapter.cmd_defs, dict)
        self.assertGreater(len(adapter.cmd_defs), 0)

    def test_unknown_mission_raises_import_error(self):
        """Unknown mission raises ImportError via convention-based discovery."""
        from mav_gss_lib.mission_adapter import load_mission_adapter

        cfg = {"general": {"mission": "nonexistent_mission_xyz"}}
        with self.assertRaises(ImportError):
            load_mission_adapter(cfg)

    def test_convention_discovery_finds_maveric(self):
        """Mission discovery finds maveric without hardcoded registry."""
        from mav_gss_lib.mission_adapter import _resolve_mission_module
        module_path = _resolve_mission_module("maveric")
        self.assertEqual(module_path, "mav_gss_lib.missions.maveric")

    def test_convention_discovery_raises_for_unknown(self):
        from mav_gss_lib.mission_adapter import _resolve_mission_module
        with self.assertRaises(ImportError) as ctx:
            _resolve_mission_module("nonexistent_mission_xyz")
        self.assertIn("No mission package found", str(ctx.exception))


class TestEchoResolution(unittest.TestCase):
    """Verify echo adapter resolution stubs."""

    def setUp(self):
        from tests.echo_mission import EchoMissionAdapter
        self.adapter = EchoMissionAdapter(cmd_defs={})

    def test_echo_satisfies_protocol(self):
        self.assertIsInstance(self.adapter, MissionAdapter)
        validate_adapter(self.adapter, 1, "echo")

    def test_node_name(self):
        self.assertEqual(self.adapter.node_name(0), "0")

    def test_ptype_name(self):
        self.assertEqual(self.adapter.ptype_name(1), "1")

    def test_resolve_node_numeric(self):
        self.assertEqual(self.adapter.resolve_node("5"), 5)

    def test_resolve_node_non_numeric(self):
        self.assertIsNone(self.adapter.resolve_node("GS"))

    def test_resolve_ptype_numeric(self):
        self.assertEqual(self.adapter.resolve_ptype("2"), 2)

    def test_gs_node(self):
        self.assertEqual(self.adapter.gs_node, 0)

    def test_echo_build_tx_command(self):
        result = self.adapter.build_tx_command({"line": "test a b"})
        self.assertIn("raw_cmd", result)
        self.assertIsInstance(result["raw_cmd"], bytes)
        self.assertIn("display", result)


class TestMavericResolution(unittest.TestCase):
    """Verify MAVERIC adapter resolves correctly."""

    def setUp(self):
        from mav_gss_lib.config import load_gss_config
        from mav_gss_lib.mission_adapter import load_mission_adapter
        cfg = load_gss_config()
        self.adapter = load_mission_adapter(cfg)

    def test_node_name_known(self):
        self.assertEqual(self.adapter.node_name(6), "GS")

    def test_ptype_name_known(self):
        self.assertEqual(self.adapter.ptype_name(1), "CMD")

    def test_resolve_node_by_name(self):
        self.assertEqual(self.adapter.resolve_node("GS"), 6)

    def test_resolve_node_by_id(self):
        self.assertEqual(self.adapter.resolve_node("6"), 6)

    def test_resolve_ptype_by_name(self):
        self.assertEqual(self.adapter.resolve_ptype("CMD"), 1)

    def test_gs_node_is_6(self):
        self.assertEqual(self.adapter.gs_node, 6)

    def test_parse_cmd_line_full(self):
        src, dest, echo, ptype, cmd_id, args = self.adapter.parse_cmd_line("6 1 0 1 com_ping")
        self.assertEqual(cmd_id, "com_ping")


if __name__ == "__main__":
    unittest.main()
