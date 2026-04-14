"""Tests for the optional TX plugin contract (Phase 3)."""

import sys
import unittest
from pathlib import Path

# Ensure mav_gss_lib is importable when run from the tests directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class FakeAdapter:
    """Minimal adapter stub for TX capability tests."""
    pass


class FakeBuildAdapter:
    """Adapter stub with build_tx_command for make_mission_cmd tests."""

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

    def test_get_tx_capabilities_default(self):
        from mav_gss_lib.mission_adapter import get_tx_capabilities
        caps = get_tx_capabilities(FakeAdapter())
        self.assertEqual(caps, {"raw_send": True})

    def test_get_tx_capabilities_custom_override(self):
        """Adapters can override tx_capabilities() to declare support."""
        from mav_gss_lib.mission_adapter import get_tx_capabilities

        class CustomAdapter:
            def tx_capabilities(self):
                return {"raw_send": True, "extra_feature": True}

        caps = get_tx_capabilities(CustomAdapter())
        self.assertEqual(caps, {"raw_send": True, "extra_feature": True})


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
        adapter = FakeBuildAdapter()
        payload = {"cmd_id": "ping", "target": "obc"}
        item = make_mission_cmd(payload, adapter=adapter)
        self.assertEqual(item["type"], "mission_cmd")
        self.assertEqual(item["raw_cmd"], b"\x01\x02\x03\x04")
        self.assertEqual(item["display"]["title"], "PING")
        self.assertFalse(item["guard"])
        self.assertEqual(item["payload"], payload)

    def test_make_mission_cmd_with_guard(self):
        from mav_gss_lib.web_runtime.runtime import make_mission_cmd
        adapter = FakeBuildAdapter()
        payload = {"cmd_id": "reboot", "guard": True}
        item = make_mission_cmd(payload, adapter=adapter)
        self.assertTrue(item["guard"])

    def test_validate_mission_cmd_passes(self):
        from mav_gss_lib.web_runtime.runtime import validate_mission_cmd
        adapter = FakeBuildAdapter()
        rt = FakeRuntime(adapter)
        item = validate_mission_cmd({"cmd_id": "ping"}, runtime=rt)
        self.assertEqual(item["type"], "mission_cmd")

    def test_validate_mission_cmd_rejects_invalid(self):
        from mav_gss_lib.web_runtime.runtime import validate_mission_cmd
        adapter = FakeBuildAdapter()
        rt = FakeRuntime(adapter)
        with self.assertRaises(ValueError) as ctx:
            validate_mission_cmd({}, runtime=rt)
        self.assertIn("required", str(ctx.exception))

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
        adapter = load_mission_adapter(cfg)
        # Ensure com_ping has node restrictions for whitelist tests — the
        # local commands.yml may include FTDI, which would defeat the test.
        # Use setdefault so we only inject if the field is absent; if present
        # we overwrite to the canonical set the test assumes.
        if "com_ping" in adapter.cmd_defs:
            adapter.cmd_defs["com_ping"]["nodes"] = ["LPPM", "EPS", "UPPM", "HLNV", "ASTR"]
        return adapter

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
        self.assertIn("row", display)
        self.assertIn("detail_blocks", display)
        self.assertNotIn("fields", display)
        self.assertEqual(display["title"], "com_ping")

    def test_build_tx_command_with_args(self):
        adapter = self._make_adapter()
        result = adapter.build_tx_command({
            "cmd_id": "gnc_set_mode",
            "args": {"Mode": "NOMINAL"},
            "dest": "LPPM",
            "echo": "NONE",
            "ptype": "CMD",
        })
        self.assertIn("raw_cmd", result)
        display = result["display"]
        self.assertIn("detail_blocks", display)
        self.assertNotIn("fields", display)
        all_field_names = [f["name"] for b in display["detail_blocks"] for f in b["fields"]]
        self.assertIn("Mode", all_field_names)

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
    return MavericMissionAdapter(cmd_defs=resources["cmd_defs"], nodes=resources["nodes"])


class TestTxQueueColumns(unittest.TestCase):
    def test_maveric_returns_column_defs(self):
        adapter = _make_maveric_adapter()
        cols = adapter.tx_queue_columns()
        self.assertIsInstance(cols, list)
        self.assertTrue(len(cols) > 0)
        for col in cols:
            self.assertIn("id", col)
            self.assertIn("label", col)

    def test_columns_include_dest_ptype_cmd(self):
        adapter = _make_maveric_adapter()
        col_ids = [c["id"] for c in adapter.tx_queue_columns()]
        self.assertIn("dest", col_ids)
        self.assertIn("ptype", col_ids)
        self.assertIn("cmd", col_ids)

    def test_src_column_is_dropped(self):
        adapter = _make_maveric_adapter()
        col_ids = [c["id"] for c in adapter.tx_queue_columns()]
        self.assertNotIn("src", col_ids)

    def test_echo_column_has_hide_if_all(self):
        adapter = _make_maveric_adapter()
        cols = {c["id"]: c for c in adapter.tx_queue_columns()}
        self.assertIn("NONE", cols["echo"].get("hide_if_all", []))


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
        adapter = self.adapter
        node_names = adapter.nodes.node_names

        # Resolve dest: prefer defn.dest, else first allowed node, else first known node
        raw_dest = defn.get("dest")
        if isinstance(raw_dest, int):
            dest = adapter.node_name(raw_dest)
        elif raw_dest:
            dest = raw_dest
        elif defn.get("nodes"):
            dest = defn["nodes"][0]
        else:
            # Fall back to first non-NONE, non-GS node available
            dest = next((v for k, v in sorted(node_names.items()) if k not in (0, adapter.gs_node)), "GS")

        raw_echo = defn.get("echo", 0)
        echo = adapter.node_name(raw_echo) if isinstance(raw_echo, int) else raw_echo

        raw_ptype = defn.get("ptype", 1)
        ptype = adapter.ptype_name(raw_ptype) if isinstance(raw_ptype, int) else raw_ptype

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
        """Display detail_blocks should include routing (Src, Dest) and each tx_arg name."""
        cmd_id, defn = self.cmd_with_args
        tx_args = defn.get("tx_args", [])
        args_str = " ".join("test" for _ in tx_args)
        payload = {"cmd_id": cmd_id, "args": args_str, **self._routing_for(defn)}
        result = self.adapter.build_tx_command(payload)
        all_field_names = [f["name"] for b in result["display"]["detail_blocks"] for f in b["fields"]]
        self.assertIn("Src", all_field_names)
        self.assertIn("Dest", all_field_names)
        for arg_def in tx_args:
            self.assertIn(arg_def["name"], all_field_names)

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
        """Explicit src in payload should be reflected in the Src routing field."""
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
        routing_block = next(b for b in result["display"]["detail_blocks"] if b["kind"] == "routing")
        field_map = {f["name"]: f["value"] for f in routing_block["fields"]}
        self.assertEqual(field_map["Src"], src_override)

    def test_default_src_is_gs_node(self):
        """Omitting src should default to GS_NODE in the Src routing field."""
        cmd_id, defn = self.cmd_with_args
        tx_args = defn.get("tx_args", [])
        args_str = " ".join("test" for _ in tx_args)
        payload = {"cmd_id": cmd_id, "args": args_str, **self._routing_for(defn)}
        result = self.adapter.build_tx_command(payload)
        routing_block = next(b for b in result["display"]["detail_blocks"] if b["kind"] == "routing")
        field_map = {f["name"]: f["value"] for f in routing_block["fields"]}
        self.assertEqual(field_map["Src"], self.adapter.node_name(self.adapter.gs_node))


def _find_cmd_with_defaults(adapter):
    for cid, defn in adapter.cmd_defs.items():
        if not defn.get("rx_only") and defn.get("dest") is not None:
            return cid, defn
    return None, None


class TestTxRendering(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.adapter = _make_maveric_adapter()
        # Prefer a zero-args command with dest defaults; fall back to first with defaults
        cmd_id, defn = None, None
        for cid, d in cls.adapter.cmd_defs.items():
            if not d.get("rx_only") and d.get("dest") is not None:
                if not d.get("tx_args"):
                    cmd_id, defn = cid, d
                    break
        if cmd_id is None:
            cmd_id, defn = _find_cmd_with_defaults(cls.adapter)
        dest_raw = defn["dest"]
        dest_str = cls.adapter.node_name(dest_raw) if isinstance(dest_raw, int) else dest_raw
        cls.payload = {"cmd_id": cmd_id, "args": "", "dest": dest_str}
        cls.cmd_id = cmd_id

    def test_display_has_row(self):
        result = self.adapter.build_tx_command(self.payload)
        self.assertIn("row", result["display"])
        self.assertIsInstance(result["display"]["row"], dict)

    def test_row_has_column_values(self):
        result = self.adapter.build_tx_command(self.payload)
        row = result["display"]["row"]
        col_ids = [c["id"] for c in self.adapter.tx_queue_columns()]
        for cid in col_ids:
            self.assertIn(cid, row)

    def test_display_has_detail_blocks(self):
        result = self.adapter.build_tx_command(self.payload)
        blocks = result["display"]["detail_blocks"]
        self.assertIsInstance(blocks, list)
        self.assertTrue(len(blocks) > 0)
        for block in blocks:
            self.assertIn("kind", block)
            self.assertIn("label", block)
            self.assertIn("fields", block)

    def test_display_no_fields(self):
        """display.fields should not exist — clean cut."""
        result = self.adapter.build_tx_command(self.payload)
        self.assertNotIn("fields", result["display"])

    def test_title_and_subtitle_preserved(self):
        result = self.adapter.build_tx_command(self.payload)
        self.assertEqual(result["display"]["title"], self.cmd_id)
        self.assertIn("\u2192", result["display"]["subtitle"])


class TestCmdLineToPayload(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.adapter = _make_maveric_adapter()
        # Find a non-rx-only command with schema routing defaults (dest set)
        cmd_defs = cls.adapter.cmd_defs
        cls.cmd_with_defaults = None      # any command with dest set
        cls.cmd_with_args = None          # command with tx_args and dest set
        cls.cmd_no_args_defaults = None   # zero-arg command with dest set (for roundtrip)
        for cmd_id, defn in cmd_defs.items():
            if defn.get("rx_only"):
                continue
            if defn.get("dest") is not None:
                if defn.get("tx_args") and not cls.cmd_with_args:
                    cls.cmd_with_args = (cmd_id, defn)
                if not defn.get("tx_args") and not cls.cmd_no_args_defaults:
                    cls.cmd_no_args_defaults = (cmd_id, defn)
                if not cls.cmd_with_defaults:
                    cls.cmd_with_defaults = (cmd_id, defn)
            if cls.cmd_with_defaults and cls.cmd_with_args and cls.cmd_no_args_defaults:
                break

    def test_shortcut_format(self):
        """Shortcut format (just cmd_id) returns payload with routing defaults."""
        cmd_id, defn = self.cmd_with_defaults
        payload = self.adapter.cmd_line_to_payload(cmd_id)
        self.assertEqual(payload["cmd_id"], cmd_id)
        self.assertIn("dest", payload)
        self.assertIn("echo", payload)
        self.assertIn("ptype", payload)

    def test_shortcut_with_args(self):
        """Shortcut format with args preserves args string."""
        if self.cmd_with_args is None:
            self.skipTest("No command with tx_args found in schema")
        cmd_id, defn = self.cmd_with_args
        tx_args = defn.get("tx_args", [])
        args_str = " ".join("test" for _ in tx_args)
        line = f"{cmd_id} {args_str}"
        payload = self.adapter.cmd_line_to_payload(line)
        self.assertEqual(payload["cmd_id"], cmd_id)
        self.assertEqual(payload["args"], args_str)

    def test_full_format_without_src(self):
        """Full format (DEST ECHO TYPE CMD) sets cmd_id and dest, no src key."""
        cmd_id, defn = self.cmd_with_defaults
        dest_name = defn.get("dest") if isinstance(defn.get("dest"), str) else self.adapter.node_name(defn["dest"])
        echo_name = self.adapter.node_name(defn.get("echo", 0)) if isinstance(defn.get("echo"), int) else defn.get("echo", "NONE")
        ptype_n = self.adapter.ptype_name(defn.get("ptype", 1)) if isinstance(defn.get("ptype"), int) else defn.get("ptype", "CMD")
        line = f"{dest_name} {echo_name} {ptype_n} {cmd_id}"
        payload = self.adapter.cmd_line_to_payload(line)
        self.assertEqual(payload["cmd_id"], cmd_id)
        self.assertEqual(payload["dest"], dest_name)
        self.assertNotIn("src", payload)

    def test_full_format_with_explicit_src(self):
        """Full format (SRC DEST ECHO TYPE CMD) sets src key when non-default."""
        cmd_id, defn = self.cmd_with_defaults
        dest_name = defn.get("dest") if isinstance(defn.get("dest"), str) else self.adapter.node_name(defn["dest"])
        echo_name = self.adapter.node_name(defn.get("echo", 0)) if isinstance(defn.get("echo"), int) else defn.get("echo", "NONE")
        ptype_n = self.adapter.ptype_name(defn.get("ptype", 1)) if isinstance(defn.get("ptype"), int) else defn.get("ptype", "CMD")
        # Pick a src that differs from GS_NODE
        node_names = self.adapter.nodes.node_names
        gs_node = self.adapter.gs_node
        alt_src = next((v for k, v in sorted(node_names.items()) if k != gs_node), None)
        if alt_src is None:
            self.skipTest("No alternate src node available")
        line = f"{alt_src} {dest_name} {echo_name} {ptype_n} {cmd_id}"
        payload = self.adapter.cmd_line_to_payload(line)
        self.assertIn("src", payload)
        self.assertEqual(payload["src"], alt_src)

    def test_roundtrip_through_build(self):
        """cmd_line_to_payload output feeds into build_tx_command successfully."""
        if self.cmd_no_args_defaults is None:
            self.skipTest("No zero-arg command with defaults found in schema")
        cmd_id, defn = self.cmd_no_args_defaults
        payload = self.adapter.cmd_line_to_payload(cmd_id)
        result = self.adapter.build_tx_command(payload)
        self.assertIsInstance(result["raw_cmd"], bytes)
        self.assertIn("display", result)

    def test_unknown_command_raises(self):
        """ValueError raised for an unknown command ID."""
        with self.assertRaises(ValueError):
            self.adapter.cmd_line_to_payload("__totally_unknown_cmd__")

    def test_empty_input_raises(self):
        """ValueError raised for empty input."""
        with self.assertRaises(ValueError):
            self.adapter.cmd_line_to_payload("")


class TestQueuePersistence(unittest.TestCase):

    def test_item_to_json_strips_raw_cmd(self):
        from mav_gss_lib.web_runtime.services import item_to_json
        item = {
            "type": "mission_cmd",
            "raw_cmd": b"\x01\x02",
            "display": {"title": "ping", "subtitle": "GS -> OBC", "fields": []},
            "guard": False,
            "payload": {"cmd_id": "ping", "dest": "OBC"},
        }
        result = item_to_json(item)
        self.assertNotIn("raw_cmd", result)
        self.assertEqual(result["type"], "mission_cmd")
        self.assertEqual(result["display"]["title"], "ping")

    def test_item_to_json_delay(self):
        from mav_gss_lib.web_runtime.services import item_to_json
        item = {"type": "delay", "delay_ms": 2000}
        result = item_to_json(item)
        self.assertEqual(result, {"type": "delay", "delay_ms": 2000})


class TestImagingCommandsRoundtrip(unittest.TestCase):
    """Round-trip every imaging/camera command through build_tx_command.

    Mirrors the shape of TestMavericBuildTxCommand — ensures the schema
    accepts the args we'll stage from the new imaging UI.
    """

    def _make_adapter(self):
        from mav_gss_lib.config import load_gss_config
        from mav_gss_lib.mission_adapter import load_mission_adapter
        return load_mission_adapter(load_gss_config())

    def _assert_raw(self, result):
        self.assertIn("raw_cmd", result)
        self.assertIsInstance(result["raw_cmd"], bytes)
        self.assertGreater(len(result["raw_cmd"]), 0)

    def test_cam_capture_img_roundtrip(self):
        adapter = self._make_adapter()
        result = adapter.build_tx_command({
            "cmd_id": "cam_capture_img",
            "args": {"Filename": "limb_004.jpg"},
            "dest": "HLNV",
            "echo": "NONE",
            "ptype": "CMD",
        })
        self._assert_raw(result)
        self.assertEqual(result["display"]["title"], "cam_capture_img")

    def test_cam_on_roundtrip(self):
        adapter = self._make_adapter()
        result = adapter.build_tx_command({
            "cmd_id": "cam_on", "args": {}, "dest": "HLNV",
            "echo": "NONE", "ptype": "CMD",
        })
        self._assert_raw(result)

    def test_cam_off_roundtrip(self):
        adapter = self._make_adapter()
        result = adapter.build_tx_command({
            "cmd_id": "cam_off", "args": {}, "dest": "HLNV",
            "echo": "NONE", "ptype": "CMD",
        })
        self._assert_raw(result)

    def test_cam_cleanup_roundtrip(self):
        adapter = self._make_adapter()
        result = adapter.build_tx_command({
            "cmd_id": "cam_cleanup", "args": {}, "dest": "HLNV",
            "echo": "NONE", "ptype": "CMD",
        })
        self._assert_raw(result)

    def test_img_compress_roundtrip(self):
        adapter = self._make_adapter()
        result = adapter.build_tx_command({
            "cmd_id": "img_compress",
            "args": {"Filename": "limb_003.jpg", "Quality": "80"},
            "dest": "HLNV", "echo": "NONE", "ptype": "CMD",
        })
        self._assert_raw(result)

    def test_img_resize_roundtrip(self):
        adapter = self._make_adapter()
        result = adapter.build_tx_command({
            "cmd_id": "img_resize",
            "args": {"Filename": "limb_003.jpg", "Width": "640", "Height": "480"},
            "dest": "HLNV", "echo": "NONE", "ptype": "CMD",
        })
        self._assert_raw(result)

    def test_img_dfl_thumb_roundtrip(self):
        adapter = self._make_adapter()
        result = adapter.build_tx_command({
            "cmd_id": "img_dfl_thumb",
            "args": {"Filename": "limb_003.jpg"},
            "dest": "HLNV", "echo": "NONE", "ptype": "CMD",
        })
        self._assert_raw(result)

    def test_img_delete_roundtrip(self):
        adapter = self._make_adapter()
        result = adapter.build_tx_command({
            "cmd_id": "img_delete",
            "args": {"Filepath": "/home/pi/full/limb_003.jpg"},
            "dest": "HLNV", "echo": "NONE", "ptype": "CMD",
        })
        self._assert_raw(result)

    def test_img_cnt_chunks_with_destination_target_roundtrip(self):
        """The new UI sends Destination as '1' or '2' (target arg)."""
        adapter = self._make_adapter()
        result = adapter.build_tx_command({
            "cmd_id": "img_cnt_chunks",
            "args": {"Filename": "limb_003.jpg", "Destination": "2", "Chunk Size": "150"},
            "dest": "HLNV", "echo": "NONE", "ptype": "CMD",
        })
        self._assert_raw(result)

    def test_img_get_chunk_with_destination_target_roundtrip(self):
        adapter = self._make_adapter()
        result = adapter.build_tx_command({
            "cmd_id": "img_get_chunk",
            "args": {
                "Filename": "limb_003.jpg",
                "Start Chunk": "5",
                "Num Chunks": "3",
                "Destination": "1",
            },
            "dest": "HLNV", "echo": "NONE", "ptype": "CMD",
        })
        self._assert_raw(result)


if __name__ == "__main__":
    unittest.main()
