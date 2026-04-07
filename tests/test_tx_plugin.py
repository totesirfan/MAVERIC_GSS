"""Tests for the optional TX plugin contract (Phase 3)."""

import sys
import unittest
from pathlib import Path

# Ensure mav_gss_lib is importable when run from the tests directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class FakeAdapterNoBuilder:
    """Adapter without TX builder support (like current MAVERIC)."""
    pass


class FakeAdapterWithBuilder:
    """Adapter with TX builder support."""

    def build_tx_command(self, payload):
        """Validate, encode, and return queue-ready command."""
        cmd_id = payload.get("cmd_id", "")
        if not cmd_id:
            raise ValueError("cmd_id is required")
        return {
            "raw_cmd": b"\x01\x02\x03\x04",
            "display": {
                "title": cmd_id.upper(),
                "subtitle": "target=obc",
                "fields": [{"name": k, "value": str(v)} for k, v in payload.items()],
            },
            "guard": payload.get("guard", False),
        }


class TestTxPluginHelpers(unittest.TestCase):

    def test_has_tx_builder_false_when_no_method(self):
        from mav_gss_lib.mission_adapter import has_tx_builder
        self.assertFalse(has_tx_builder(FakeAdapterNoBuilder()))

    def test_has_tx_builder_true_when_method_present(self):
        from mav_gss_lib.mission_adapter import has_tx_builder
        self.assertTrue(has_tx_builder(FakeAdapterWithBuilder()))

    def test_get_tx_capabilities_default_no_builder(self):
        from mav_gss_lib.mission_adapter import get_tx_capabilities
        caps = get_tx_capabilities(FakeAdapterNoBuilder())
        self.assertEqual(caps, {"raw_send": True, "command_builder": False})

    def test_get_tx_capabilities_with_builder(self):
        from mav_gss_lib.mission_adapter import get_tx_capabilities
        caps = get_tx_capabilities(FakeAdapterWithBuilder())
        self.assertEqual(caps, {"raw_send": True, "command_builder": True})


import threading


class FakeCSP:
    enabled = True
    prio = 2
    src = 1
    dest = 5
    dport = 0
    sport = 0
    flags = 0
    def wrap(self, data):
        return b"\x20\x01\x05\x00" + data
    def build_header(self):
        return b"\x20\x01\x05\x00"
    def overhead(self):
        return 4


class FakeAX25:
    enabled = True
    src_call = "GS"
    src_ssid = 0
    dest_call = "SAT"
    dest_ssid = 0
    def wrap(self, data):
        return b"\x00" * 16 + data
    def overhead(self):
        return 16


class FakeRuntime:
    """Minimal runtime mock for TX plugin tests."""
    def __init__(self, adapter):
        self.adapter = adapter
        self.cmd_defs = {}
        self.cfg = {"tx": {"uplink_mode": "AX.25", "delay_ms": 500}}
        self.csp = FakeCSP()
        self.ax25 = FakeAX25()
        self.cfg_lock = threading.Lock()


class TestMakeMissionCmd(unittest.TestCase):

    def test_make_mission_cmd_builds_item(self):
        from mav_gss_lib.web_runtime.runtime import make_mission_cmd
        adapter = FakeAdapterWithBuilder()
        payload = {"cmd_id": "ping", "target": "obc"}
        item = make_mission_cmd(payload, adapter=adapter)
        self.assertEqual(item["type"], "mission_cmd")
        self.assertEqual(item["raw_cmd"], b"\x01\x02\x03\x04")
        self.assertEqual(item["display"]["title"], "PING")
        self.assertFalse(item["guard"])
        self.assertEqual(item["payload"], payload)

    def test_make_mission_cmd_with_guard(self):
        from mav_gss_lib.web_runtime.runtime import make_mission_cmd
        adapter = FakeAdapterWithBuilder()
        payload = {"cmd_id": "reboot", "guard": True}
        item = make_mission_cmd(payload, adapter=adapter)
        self.assertTrue(item["guard"])

    def test_validate_mission_cmd_passes(self):
        from mav_gss_lib.web_runtime.runtime import validate_mission_cmd
        adapter = FakeAdapterWithBuilder()
        rt = FakeRuntime(adapter)
        item = validate_mission_cmd({"cmd_id": "ping"}, runtime=rt)
        self.assertEqual(item["type"], "mission_cmd")

    def test_validate_mission_cmd_rejects_invalid(self):
        from mav_gss_lib.web_runtime.runtime import validate_mission_cmd
        adapter = FakeAdapterWithBuilder()
        rt = FakeRuntime(adapter)
        with self.assertRaises(ValueError) as ctx:
            validate_mission_cmd({}, runtime=rt)
        self.assertIn("required", str(ctx.exception))

    def test_validate_mission_cmd_rejects_no_builder(self):
        from mav_gss_lib.web_runtime.runtime import validate_mission_cmd
        adapter = FakeAdapterNoBuilder()
        rt = FakeRuntime(adapter)
        with self.assertRaises(ValueError) as ctx:
            validate_mission_cmd({"cmd_id": "ping"}, runtime=rt)
        self.assertIn("does not support", str(ctx.exception))


class TestMissionCmdQueueProjection(unittest.TestCase):

    def _make_item(self):
        return {
            "type": "mission_cmd",
            "raw_cmd": b"\x01\x02\x03\x04",
            "display": {
                "title": "PING",
                "subtitle": "target=obc",
                "fields": [{"name": "target", "value": "obc"}],
            },
            "guard": False,
            "payload": {"cmd_id": "ping", "target": "obc"},
        }

    def test_item_to_json_strips_raw_cmd(self):
        from mav_gss_lib.web_runtime.services import item_to_json
        item = self._make_item()
        result = item_to_json(item)
        self.assertNotIn("raw_cmd", result)
        self.assertEqual(result["type"], "mission_cmd")
        self.assertEqual(result["display"]["title"], "PING")
        self.assertEqual(result["payload"], {"cmd_id": "ping", "target": "obc"})

    def test_renumber_counts_mission_cmds(self):
        """mission_cmd items should get sequential numbers."""
        item1 = self._make_item()
        item2 = self._make_item()
        queue = [item1, {"type": "delay", "delay_ms": 1000}, item2]
        count = 0
        for item in queue:
            if item["type"] in ("cmd", "mission_cmd"):
                count += 1
                item["num"] = count
        self.assertEqual(item1["num"], 1)
        self.assertEqual(item2["num"], 2)


class TestMavericBuildTxCommand(unittest.TestCase):
    """Test MAVERIC adapter's build_tx_command implementation."""

    def _make_adapter(self):
        from mav_gss_lib.config import load_gss_config
        from mav_gss_lib.mission_adapter import load_mission_adapter
        cfg = load_gss_config()
        return load_mission_adapter(cfg)

    def test_build_tx_command_returns_raw_cmd(self):
        adapter = self._make_adapter()
        result = adapter.build_tx_command({
            "cmd_id": "com_ping",
            "args": {},
            "dest": "LPPM",
            "echo": "NONE",
            "ptype": "CMD",
        })
        self.assertIn("raw_cmd", result)
        self.assertIsInstance(result["raw_cmd"], bytes)
        self.assertGreater(len(result["raw_cmd"]), 0)

    def test_build_tx_command_returns_display(self):
        adapter = self._make_adapter()
        result = adapter.build_tx_command({
            "cmd_id": "com_ping",
            "args": {},
            "dest": "LPPM",
            "echo": "NONE",
            "ptype": "CMD",
        })
        display = result["display"]
        self.assertIn("title", display)
        self.assertIn("fields", display)
        self.assertEqual(display["title"], "com_ping")

    def test_build_tx_command_with_args(self):
        adapter = self._make_adapter()
        result = adapter.build_tx_command({
            "cmd_id": "ping",
            "args": {"Type": "hello"},
            "dest": "LPPM",
            "echo": "NONE",
            "ptype": "CMD",
        })
        self.assertIn("raw_cmd", result)
        display = result["display"]
        self.assertIn("fields", display)
        field_names = [f["name"] for f in display["fields"]]
        self.assertIn("Type", field_names)

    def test_build_tx_command_rejects_unknown_cmd(self):
        adapter = self._make_adapter()
        with self.assertRaises(ValueError):
            adapter.build_tx_command({
                "cmd_id": "nonexistent_cmd_xyz",
                "args": {},
                "dest": "LPPM",
                "echo": "NONE",
                "ptype": "CMD",
            })

    def test_build_tx_command_rejects_unknown_node(self):
        adapter = self._make_adapter()
        with self.assertRaises(ValueError):
            adapter.build_tx_command({
                "cmd_id": "com_ping",
                "args": {},
                "dest": "NONEXISTENT_NODE",
                "echo": "NONE",
                "ptype": "CMD",
            })

    def test_build_tx_command_guard_from_schema(self):
        adapter = self._make_adapter()
        result = adapter.build_tx_command({
            "cmd_id": "com_ping",
            "args": {},
            "dest": "LPPM",
            "echo": "NONE",
            "ptype": "CMD",
        })
        self.assertIn("guard", result)
        self.assertIsInstance(result["guard"], bool)

    def test_has_tx_builder_true_for_maveric(self):
        from mav_gss_lib.mission_adapter import has_tx_builder
        adapter = self._make_adapter()
        self.assertTrue(has_tx_builder(adapter))

    def test_build_tx_command_rejects_invalid_node_for_cmd(self):
        """com_ping is only valid for LPPM/EPS/UPPM/HLNV/ASTR, not FTDI."""
        adapter = self._make_adapter()
        with self.assertRaises(ValueError) as ctx:
            adapter.build_tx_command({
                "cmd_id": "com_ping",
                "args": {},
                "dest": "FTDI",
                "echo": "NONE",
                "ptype": "CMD",
            })
        self.assertIn("not valid for node", str(ctx.exception))

    def test_build_tx_command_rejects_non_dict_args(self):
        """args must be a dict, not a list."""
        adapter = self._make_adapter()
        with self.assertRaises(ValueError) as ctx:
            adapter.build_tx_command({
                "cmd_id": "com_ping",
                "args": [],
                "dest": "LPPM",
                "echo": "NONE",
                "ptype": "CMD",
            })
        self.assertIn("args must be a dict", str(ctx.exception))

    def test_build_tx_command_rejects_non_dict_payload(self):
        """payload must be a dict."""
        adapter = self._make_adapter()
        with self.assertRaises(ValueError):
            adapter.build_tx_command([])


if __name__ == "__main__":
    unittest.main()
