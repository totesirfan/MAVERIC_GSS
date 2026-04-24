"""Operations-focused web runtime and config workflow tests for MAVERIC GSS."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.config import get_generated_commands_dir
from mav_gss_lib.server.api.queue_io import (
    export_queue,
    import_file,
    list_import_files,
    parse_import_file,
    preview_import,
)
from mav_gss_lib.server.tx.queue import make_delay, validate_mission_cmd
from mav_gss_lib.server.state import create_runtime


def _request_for(runtime, *, token=True):
    """Build the minimal request shape expected by the API helpers."""
    headers = {}
    if token:
        headers["x-gss-token"] = runtime.session_token
    app = SimpleNamespace(state=SimpleNamespace(runtime=runtime))
    return SimpleNamespace(app=app, headers=headers)


def _make_mission_item(cmd_id="com_ping", args="", dest="LPPM", runtime=None):
    """Build a validated mission_cmd queue item for testing."""
    payload = {"cmd_id": cmd_id, "args": args, "dest": dest, "echo": "NONE", "ptype": "CMD"}
    return validate_mission_cmd(payload, runtime=runtime)


class TestWebRuntimeWorkflows(unittest.TestCase):
    """Covers config-path and import/export workflows exposed to operators."""

    def setUp(self):
        self.runtime = create_runtime()
        self.tmp = tempfile.TemporaryDirectory()
        self.generated_dir = Path(self.tmp.name) / "imports"
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        self.runtime.platform_cfg.setdefault("general", {})["generated_commands_dir"] = str(self.generated_dir)
        self.runtime.tx.queue.clear()

        async def _noop(_msg=None):
            # API helpers await this during import/export flows.
            return None

        self.runtime.tx.send_queue_update = _noop

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_import_file_produces_mission_cmd_items(self):
        payload = """
        // comment
        {"type": "mission_cmd", "payload": {"cmd_id": "com_ping", "args": "", "dest": "EPS", "echo": "NONE", "ptype": "CMD", "guard": true}} // trailing
        {"type": "delay", "delay_ms": 250}
        """.strip()
        path = self.generated_dir / "sample.jsonl"
        path.write_text(payload + "\n")
        items, skipped = parse_import_file(path, runtime=self.runtime)
        self.assertEqual(skipped, 0)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["type"], "mission_cmd")
        self.assertTrue(items[0]["guard"])
        self.assertEqual(items[0]["display"]["title"], "com_ping")
        self.assertEqual(items[1]["type"], "delay")

    def test_list_import_files_uses_configured_directory(self):
        (self.generated_dir / "a.jsonl").write_text("{}\n")
        (self.generated_dir / "b.jsonl").write_text("{}\n")
        result = asyncio.run(list_import_files(_request_for(self.runtime)))
        names = [item["name"] for item in result]
        self.assertEqual(set(names), {"a.jsonl", "b.jsonl"})

    def test_preview_returns_display_metadata(self):
        path = self.generated_dir / "queue.jsonl"
        path.write_text('{"type": "mission_cmd", "payload": {"cmd_id": "com_ping", "args": "", "dest": "EPS", "echo": "NONE", "ptype": "CMD"}}\n')
        preview = asyncio.run(preview_import("queue.jsonl", _request_for(self.runtime)))
        self.assertEqual(preview["skipped"], 0)
        self.assertEqual(len(preview["items"]), 1)
        item = preview["items"][0]
        self.assertEqual(item["type"], "mission_cmd")
        self.assertIn("display", item)
        self.assertEqual(item["display"]["title"], "com_ping")

    def test_import_produces_mission_cmd_queue_items(self):
        path = self.generated_dir / "queue.jsonl"
        path.write_text('{"type": "mission_cmd", "payload": {"cmd_id": "com_ping", "args": "", "dest": "EPS", "echo": "NONE", "ptype": "CMD"}}\n')
        result = asyncio.run(import_file("queue.jsonl", _request_for(self.runtime)))
        self.assertEqual(result["loaded"], 1)
        item = self.runtime.tx.queue[0]
        self.assertEqual(item["type"], "mission_cmd")
        self.assertEqual(item["display"]["title"], "com_ping")

    def test_import_preserves_delay_and_mission_command(self):
        path = self.generated_dir / "command_and_delay.jsonl"
        path.write_text('{"type": "mission_cmd", "payload": {"cmd_id": "com_ping", "args": "", "dest": "EPS", "echo": "NONE", "ptype": "CMD"}}\n{"type": "delay", "delay_ms": 500}\n')
        result = asyncio.run(import_file("command_and_delay.jsonl", _request_for(self.runtime)))
        self.assertEqual(result["loaded"], 2)
        self.assertEqual([item["type"] for item in self.runtime.tx.queue], ["mission_cmd", "delay"])

    def test_export_queue_writes_to_configured_directory(self):
        self.runtime.tx.queue.extend(
            [
                _make_mission_item("com_ping", "", runtime=self.runtime),
                make_delay(500),
            ]
        )
        result = asyncio.run(export_queue({"name": "ops smoke"}, _request_for(self.runtime)))
        self.assertTrue(result["ok"])
        export_path = self.generated_dir / "ops_smoke.jsonl"
        self.assertTrue(export_path.exists())
        contents = export_path.read_text()
        self.assertIn('"type": "mission_cmd"', contents)
        self.assertIn('"type": "delay"', contents)

    def test_export_queue_requires_session_token(self):
        self.runtime.tx.queue.append(
            _make_mission_item("com_ping", "", runtime=self.runtime)
        )
        response = asyncio.run(export_queue({"name": "blocked"}, _request_for(self.runtime, token=False)))
        self.assertEqual(response.status_code, 403)


    def test_log_pagination_respects_offset_and_limit(self):
        """Paginated log endpoint returns bounded results with has_more."""
        import json as _json

        # Redirect log_dir to isolated temp directory
        log_base = Path(self.tmp.name) / "logs"
        self.runtime.platform_cfg["general"]["log_dir"] = str(log_base)
        log_dir = log_base / "json"
        log_dir.mkdir(parents=True, exist_ok=True)

        # Write 5 realistic RX log entries (RX entries have "pkt" and "gs_ts")
        session_id = "downlink_20260408_120000"
        log_file = log_dir / f"{session_id}.jsonl"
        entries = []
        for i in range(5):
            entry = {
                "pkt": i + 1,
                "gs_ts": f"2026-04-08T12:00:{i:02d}Z",
                "raw_hex": f"{i:02x}" * 10,
                "raw_len": 20,
                "frame_type": "HDLC",
            }
            entries.append(_json.dumps(entry))
        log_file.write_text("\n".join(entries) + "\n")

        # Call the endpoint with offset=1, limit=2
        from mav_gss_lib.server.api.logs import api_log_entries

        req = _request_for(self.runtime)
        result = asyncio.run(api_log_entries(
            session_id=session_id,
            request=req,
            cmd=None,
            time_from=None,
            time_to=None,
            offset=1,
            limit=2,
        ))
        self.assertIsInstance(result, dict)
        self.assertIn("entries", result)
        self.assertIn("has_more", result)
        self.assertEqual(len(result["entries"]), 2)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["offset"], 1)
        self.assertEqual(result["limit"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
