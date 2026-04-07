"""Operations-focused TX runtime tests for MAVERIC GSS."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mav_gss_lib.web_runtime.services as services
from mav_gss_lib.web_runtime.runtime import make_mission_cmd, sanitize_queue_items, validate_mission_cmd
from mav_gss_lib.web_runtime.state import create_runtime


def _make_payload(cmd_id, args="", dest="LPPM", guard=False):
    """Build a mission payload dict for testing."""
    return {"cmd_id": cmd_id, "args": args, "dest": dest, "echo": "NONE", "ptype": "CMD", "guard": guard}


class TestTxRuntime(unittest.TestCase):
    """Covers TX validation plus send/guard/delay/abort lifecycle behavior."""

    def setUp(self):
        self.runtime = create_runtime()
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime.cfg.setdefault("general", {})["log_dir"] = self.tmp.name
        self.runtime.cfg.setdefault("tx", {})["delay_ms"] = 0
        self.runtime.tx.queue.clear()
        self.runtime.tx.history.clear()
        self.runtime.tx.zmq_sock = object()
        self.sent_payloads = []
        self.messages = []
        self.queue_updates = []

        async def _capture(msg):
            self.messages.append(msg)

        async def _capture_queue_update():
            # Capture snapshots instead of broadcasting over websockets.
            self.queue_updates.append(self.runtime.tx.sending.copy())

        self.runtime.tx.broadcast = _capture
        self.runtime.tx.send_queue_update = _capture_queue_update
        self.runtime.tx.log = None
        self._orig_send_pdu = services.send_pdu
        services.send_pdu = self._fake_send_pdu

    def tearDown(self):
        services.send_pdu = self._orig_send_pdu
        self.tmp.cleanup()

    def _fake_send_pdu(self, _sock, payload):
        """Record sent payloads while reporting success to the TX service."""
        self.sent_payloads.append(payload)
        return True

    def _make_item(self, cmd_id="ping", args="", dest="LPPM", guard=False):
        """Build a validated mission_cmd queue item."""
        payload = _make_payload(cmd_id, args, dest, guard)
        return validate_mission_cmd(payload, runtime=self.runtime)

    def test_unknown_command_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not in schema"):
            validate_mission_cmd(_make_payload("definitely_not_real", "REQ"), runtime=self.runtime)

    def test_rx_only_command_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "receive-only"):
            validate_mission_cmd(_make_payload("tlm_beacon", "1 1767230528021 0 0"), runtime=self.runtime)

    def test_missing_required_args_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_mission_cmd(_make_payload("set_voltage", ""), runtime=self.runtime)

    def test_asm_golay_size_limit_is_enforced(self):
        with self.runtime.cfg_lock:
            old_mode = self.runtime.cfg.get("tx", {}).get("uplink_mode", "AX.25")
            self.runtime.cfg["tx"]["uplink_mode"] = "ASM+Golay"
        try:
            with self.assertRaisesRegex(ValueError, "too large for ASM\\+Golay"):
                validate_mission_cmd(_make_payload("ping", "A" * 220), runtime=self.runtime)
        finally:
            with self.runtime.cfg_lock:
                self.runtime.cfg["tx"]["uplink_mode"] = old_mode

    def test_queue_restore_sanitizes_invalid_entries(self):
        valid = self._make_item("ping", "REQ")
        invalid = {
            "type": "mission_cmd",
            "payload": _make_payload("not_real", "REQ"),
        }
        items, skipped = sanitize_queue_items([valid, {"type": "delay", "delay_ms": 250}, invalid], runtime=self.runtime)
        self.assertEqual(skipped, 1)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["type"], "mission_cmd")
        self.assertEqual(items[0]["display"]["title"], "ping")
        self.assertEqual(items[1]["type"], "delay")

    def test_run_send_processes_delay_then_command(self):
        self.runtime.tx.queue = [
            {"type": "delay", "delay_ms": 100},
            self._make_item("ping", "REQ"),
        ]
        self.runtime.tx.renumber_queue()
        self.runtime.tx.sending.update(active=True, idx=-1, total=len(self.runtime.tx.queue), guarding=False, sent_at=0, waiting=False)

        asyncio.run(self.runtime.tx.run_send())

        self.assertEqual(len(self.sent_payloads), 1)
        self.assertEqual(self.runtime.tx.queue, [])
        self.assertEqual(len(self.runtime.tx.history), 1)
        self.assertEqual(self.runtime.tx.history[0]["type"], "mission_cmd")
        self.assertEqual(self.runtime.tx.history[0]["display"]["title"], "ping")
        self.assertTrue(any(msg.get("type") == "send_complete" for msg in self.messages if isinstance(msg, dict)))

    def test_run_send_waits_for_guard_confirmation(self):
        self.runtime.tx.queue = [
            self._make_item("ping", "REQ", guard=True),
        ]
        self.runtime.tx.renumber_queue()
        self.runtime.tx.sending.update(active=True, idx=-1, total=1, guarding=False, sent_at=0, waiting=False)

        async def _run():
            task = asyncio.create_task(self.runtime.tx.run_send())
            for _ in range(20):
                if self.runtime.tx.sending["guarding"]:
                    break
                await asyncio.sleep(0.02)
            self.assertTrue(self.runtime.tx.sending["guarding"])
            self.runtime.tx.guard_ok.set()
            await task

        asyncio.run(_run())

        self.assertEqual(len(self.sent_payloads), 1)
        self.assertEqual(self.runtime.tx.queue, [])
        self.assertTrue(any(msg.get("type") == "guard_confirm" for msg in self.messages if isinstance(msg, dict)))

    def test_run_send_abort_during_guard_keeps_queue_item(self):
        self.runtime.tx.queue = [
            self._make_item("ping", "REQ", guard=True),
        ]
        self.runtime.tx.renumber_queue()
        self.runtime.tx.sending.update(active=True, idx=-1, total=1, guarding=False, sent_at=0, waiting=False)

        async def _run():
            task = asyncio.create_task(self.runtime.tx.run_send())
            for _ in range(20):
                if self.runtime.tx.sending["guarding"]:
                    break
                await asyncio.sleep(0.02)
            self.assertTrue(self.runtime.tx.sending["guarding"])
            self.runtime.tx.abort.set()
            await task

        asyncio.run(_run())

        self.assertEqual(len(self.sent_payloads), 0)
        self.assertEqual(len(self.runtime.tx.queue), 1)
        self.assertTrue(any(msg.get("type") == "send_aborted" for msg in self.messages if isinstance(msg, dict)))

    def test_run_send_abort_during_delay_keeps_following_items(self):
        self.runtime.tx.queue = [
            {"type": "delay", "delay_ms": 500},
            self._make_item("ping", "REQ"),
        ]
        self.runtime.tx.renumber_queue()
        self.runtime.tx.sending.update(active=True, idx=-1, total=2, guarding=False, sent_at=0, waiting=False)

        async def _run():
            task = asyncio.create_task(self.runtime.tx.run_send())
            for _ in range(20):
                if self.runtime.tx.sending["waiting"]:
                    break
                await asyncio.sleep(0.02)
            self.assertTrue(self.runtime.tx.sending["waiting"])
            self.runtime.tx.abort.set()
            await task

        asyncio.run(_run())

        self.assertEqual(len(self.sent_payloads), 0)
        self.assertEqual(len(self.runtime.tx.queue), 2)
        self.assertTrue(any(msg.get("type") == "send_aborted" for msg in self.messages if isinstance(msg, dict)))

    def test_history_entry_includes_payload(self):
        """History entries must include payload for faithful requeue."""
        self.runtime.tx.queue = [self._make_item("ping", "REQ")]
        self.runtime.tx.renumber_queue()
        self.runtime.tx.sending.update(active=True, idx=-1, total=1, guarding=False, sent_at=0, waiting=False)

        asyncio.run(self.runtime.tx.run_send())

        self.assertEqual(len(self.runtime.tx.history), 1)
        hist = self.runtime.tx.history[0]
        self.assertIn("payload", hist)
        self.assertEqual(hist["payload"]["cmd_id"], "ping")

    def test_queue_projection_includes_payload(self):
        """Queue projection must include payload for faithful duplicate."""
        item = self._make_item("ping", "REQ")
        self.runtime.tx.queue = [item]
        self.runtime.tx.renumber_queue()

        projected = self.runtime.tx.queue_items_json()
        self.assertEqual(len(projected), 1)
        self.assertIn("payload", projected[0])
        self.assertEqual(projected[0]["payload"]["cmd_id"], "ping")


if __name__ == "__main__":
    unittest.main(verbosity=2)
