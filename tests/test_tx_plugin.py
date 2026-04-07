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
        """args must be a str or dict, not a list."""
        adapter = self._make_adapter()
        with self.assertRaises(ValueError) as ctx:
            adapter.build_tx_command({
                "cmd_id": "com_ping",
                "args": [],
                "dest": "LPPM",
                "echo": "NONE",
                "ptype": "CMD",
            })
        self.assertIn("args must be a str or dict", str(ctx.exception))

    def test_build_tx_command_rejects_non_dict_payload(self):
        """payload must be a dict."""
        adapter = self._make_adapter()
        with self.assertRaises(ValueError):
            adapter.build_tx_command([])


def _make_maveric_adapter():
    """Load a fully initialized MAVERIC adapter for testing."""
    from mav_gss_lib.config import load_gss_config
    from mav_gss_lib.mission_adapter import load_mission_metadata
    from mav_gss_lib.missions.maveric import init_mission
    from mav_gss_lib.missions.maveric.adapter import MavericMissionAdapter

    cfg = load_gss_config()
    load_mission_metadata(cfg)
    resources = init_mission(cfg)
    return MavericMissionAdapter(cmd_defs=resources["cmd_defs"])


class TestBuildTxCommandStringArgs(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.adapter = _make_maveric_adapter()
        # Pick a command with tx_args and one without for use in tests
        cmd_defs = cls.adapter.cmd_defs
        cls.cmd_with_args = None
        cls.cmd_no_args = None
        for cmd_id, defn in cmd_defs.items():
            if defn.get("rx_only"):
                continue
            if defn.get("tx_args") and not cls.cmd_with_args:
                cls.cmd_with_args = (cmd_id, defn)
            if not defn.get("tx_args") and not cls.cmd_no_args:
                cls.cmd_no_args = (cmd_id, defn)
            if cls.cmd_with_args and cls.cmd_no_args:
                break

    def _routing_for(self, defn):
        """Return dest/echo/ptype routing from command definition defaults.

        Converts numeric node/ptype IDs to names using the adapter's resolution tables.
        Falls back to the first allowed node, or to a known valid node name.
        """
        from mav_gss_lib.missions.maveric.wire_format import node_name, ptype_name, NODE_NAMES

        # Resolve dest: prefer defn.dest, else first allowed node, else first known node
        raw_dest = defn.get("dest")
        if isinstance(raw_dest, int):
            dest = node_name(raw_dest)
        elif raw_dest:
            dest = raw_dest
        elif defn.get("nodes"):
            dest = defn["nodes"][0]
        else:
            # Fall back to first non-NONE, non-GS node available
            dest = next((v for k, v in sorted(NODE_NAMES.items()) if k not in (0, 6)), "GS")

        raw_echo = defn.get("echo", 0)
        echo = node_name(raw_echo) if isinstance(raw_echo, int) else raw_echo

        raw_ptype = defn.get("ptype", 1)
        ptype = ptype_name(raw_ptype) if isinstance(raw_ptype, int) else raw_ptype

        return {"dest": dest, "echo": echo, "ptype": ptype}

    def test_string_args_accepted(self):
        """build_tx_command with args as a flat string should return bytes raw_cmd."""
        cmd_id, defn = self.cmd_with_args
        tx_args = defn.get("tx_args", [])
        args_str = " ".join("test" for _ in tx_args)
        payload = {"cmd_id": cmd_id, "args": args_str, **self._routing_for(defn)}
        result = self.adapter.build_tx_command(payload)
        self.assertIsInstance(result["raw_cmd"], bytes)
        self.assertIn("display", result)

    def test_string_args_display_has_named_fields(self):
        """Display fields should include Src, Dest, and each tx_arg name."""
        cmd_id, defn = self.cmd_with_args
        tx_args = defn.get("tx_args", [])
        args_str = " ".join("test" for _ in tx_args)
        payload = {"cmd_id": cmd_id, "args": args_str, **self._routing_for(defn)}
        result = self.adapter.build_tx_command(payload)
        field_names = [f["name"] for f in result["display"]["fields"]]
        self.assertIn("Src", field_names)
        self.assertIn("Dest", field_names)
        for arg_def in tx_args:
            self.assertIn(arg_def["name"], field_names)

    def test_dict_args_still_works(self):
        """Existing dict args path must still produce valid raw_cmd bytes."""
        cmd_id, defn = self.cmd_with_args
        tx_args = defn.get("tx_args", [])
        args_dict = {arg["name"]: "test" for arg in tx_args}
        payload = {"cmd_id": cmd_id, "args": args_dict, **self._routing_for(defn)}
        result = self.adapter.build_tx_command(payload)
        self.assertIsInstance(result["raw_cmd"], bytes)

    def test_empty_string_args_accepted(self):
        """Empty string args for a command with no tx_args should succeed."""
        if self.cmd_no_args is None:
            self.skipTest("No zero-arg command found in schema")
        cmd_id, defn = self.cmd_no_args
        payload = {"cmd_id": cmd_id, "args": "", **self._routing_for(defn)}
        result = self.adapter.build_tx_command(payload)
        self.assertIsInstance(result["raw_cmd"], bytes)

    def test_explicit_src_honored(self):
        """Explicit src in payload should be reflected in the Src display field."""
        cmd_id, defn = self.cmd_with_args
        tx_args = defn.get("tx_args", [])
        args_str = " ".join("test" for _ in tx_args)
        routing = self._routing_for(defn)
        src_override = routing["dest"]  # use dest as an explicit src override
        payload = {
            "cmd_id": cmd_id,
            "args": args_str,
            "src": src_override,
            **routing,
        }
        result = self.adapter.build_tx_command(payload)
        field_map = {f["name"]: f["value"] for f in result["display"]["fields"]}
        self.assertEqual(field_map["Src"], src_override)

    def test_default_src_is_gs_node(self):
        """Omitting src should default to GS_NODE in the Src display field."""
        from mav_gss_lib.missions.maveric.wire_format import GS_NODE, node_name
        cmd_id, defn = self.cmd_with_args
        tx_args = defn.get("tx_args", [])
        args_str = " ".join("test" for _ in tx_args)
        payload = {"cmd_id": cmd_id, "args": args_str, **self._routing_for(defn)}
        result = self.adapter.build_tx_command(payload)
        field_map = {f["name"]: f["value"] for f in result["display"]["fields"]}
        self.assertEqual(field_map["Src"], node_name(GS_NODE))


if __name__ == "__main__":
    unittest.main()
