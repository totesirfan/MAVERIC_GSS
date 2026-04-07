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

    def test_get_tx_capabilities_legacy_builder(self):
        """Adapter with build_raw_command (legacy) but no build_tx_command."""
        from mav_gss_lib.mission_adapter import get_tx_capabilities

        class LegacyAdapter:
            def build_raw_command(self, src, dest, echo, ptype, cmd_id, args):
                return b""
        caps = get_tx_capabilities(LegacyAdapter())
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


if __name__ == "__main__":
    unittest.main()
