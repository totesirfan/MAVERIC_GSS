"""Operations-focused TX runtime tests for MAVERIC GSS."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mav_gss_lib.web_runtime.tx_service as tx_service
from mav_gss_lib.web_runtime.tx_queue import make_mission_cmd, sanitize_queue_items, validate_mission_cmd
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

        # Events signalled by the broadcast mock when the production code
        # announces a state transition. Tests `await` the event instead of
        # polling `sending[...]` in a sleep loop.
        self.guard_confirm_event = asyncio.Event()
        self.waiting_event = asyncio.Event()

        async def _capture(msg):
            self.messages.append(msg)
            if isinstance(msg, dict):
                if msg.get("type") == "guard_confirm":
                    self.guard_confirm_event.set()
                elif msg.get("type") == "send_progress" and msg.get("waiting"):
                    self.waiting_event.set()

        async def _capture_queue_update():
            # Capture snapshots instead of broadcasting over websockets.
            self.queue_updates.append(self.runtime.tx.sending.copy())

        self.runtime.tx.broadcast = _capture
        self.runtime.tx.send_queue_update = _capture_queue_update
        self.runtime.tx.log = None
        self._orig_send_pdu = tx_service.send_pdu
        tx_service.send_pdu = self._fake_send_pdu

    def tearDown(self):
        tx_service.send_pdu = self._orig_send_pdu
        self.tmp.cleanup()

    def _fake_send_pdu(self, _sock, payload):
        """Record sent payloads while reporting success to the TX service."""
        self.sent_payloads.append(payload)
        return True

    def _make_item(self, cmd_id="com_ping", args="", dest="LPPM", guard=False):
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
                validate_mission_cmd(_make_payload("cfg_set_ll", "A" * 220), runtime=self.runtime)
        finally:
            with self.runtime.cfg_lock:
                self.runtime.cfg["tx"]["uplink_mode"] = old_mode

    def test_queue_restore_sanitizes_invalid_entries(self):
        valid = self._make_item("com_ping", "")
        invalid = {
            "type": "mission_cmd",
            "payload": _make_payload("not_real", "REQ"),
        }
        items, skipped = sanitize_queue_items([valid, {"type": "delay", "delay_ms": 250}, invalid], runtime=self.runtime)
        self.assertEqual(skipped, 1)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["type"], "mission_cmd")
        self.assertEqual(items[0]["display"]["title"], "com_ping")
        self.assertEqual(items[1]["type"], "delay")

    def test_run_send_processes_delay_then_command(self):
        self.runtime.tx.queue = [
            {"type": "delay", "delay_ms": 100},
            self._make_item("com_ping", ""),
        ]
        self.runtime.tx.renumber_queue()
        self.runtime.tx.sending.update(active=True, idx=-1, total=len(self.runtime.tx.queue), guarding=False, sent_at=0, waiting=False)

        asyncio.run(self.runtime.tx.run_send())

        self.assertEqual(len(self.sent_payloads), 1)
        self.assertEqual(self.runtime.tx.queue, [])
        self.assertEqual(len(self.runtime.tx.history), 1)
        self.assertEqual(self.runtime.tx.history[0]["type"], "mission_cmd")
        self.assertEqual(self.runtime.tx.history[0]["display"]["title"], "com_ping")
        self.assertTrue(any(msg.get("type") == "send_complete" for msg in self.messages if isinstance(msg, dict)))

    def test_run_send_waits_for_guard_confirmation(self):
        self.runtime.tx.queue = [
            self._make_item("com_ping", "", guard=True),
        ]
        self.runtime.tx.renumber_queue()
        self.runtime.tx.sending.update(active=True, idx=-1, total=1, guarding=False, sent_at=0, waiting=False)

        async def _run():
            task = asyncio.create_task(self.runtime.tx.run_send())
            await asyncio.wait_for(self.guard_confirm_event.wait(), timeout=5.0)
            # Yield the loop once so any continuation the production code
            # has queued (e.g. the set-guarding-flag ordering relative to the
            # broadcast) drains before we assert. Belt-and-suspenders safety
            # against a future refactor that swaps the flag/broadcast order.
            await asyncio.sleep(0)
            self.assertTrue(self.runtime.tx.sending["guarding"])
            self.runtime.tx.guard_ok.set()
            await task

        asyncio.run(_run())

        self.assertEqual(len(self.sent_payloads), 1)
        self.assertEqual(self.runtime.tx.queue, [])
        self.assertTrue(any(msg.get("type") == "guard_confirm" for msg in self.messages if isinstance(msg, dict)))

    def test_run_send_abort_during_guard_keeps_queue_item(self):
        self.runtime.tx.queue = [
            self._make_item("com_ping", "", guard=True),
        ]
        self.runtime.tx.renumber_queue()
        self.runtime.tx.sending.update(active=True, idx=-1, total=1, guarding=False, sent_at=0, waiting=False)

        async def _run():
            task = asyncio.create_task(self.runtime.tx.run_send())
            await asyncio.wait_for(self.guard_confirm_event.wait(), timeout=5.0)
            # Yield the loop once; see comment in
            # test_run_send_waits_for_guard_confirmation.
            await asyncio.sleep(0)
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
            self._make_item("com_ping", ""),
        ]
        self.runtime.tx.renumber_queue()
        self.runtime.tx.sending.update(active=True, idx=-1, total=2, guarding=False, sent_at=0, waiting=False)

        async def _run():
            task = asyncio.create_task(self.runtime.tx.run_send())
            await asyncio.wait_for(self.waiting_event.wait(), timeout=5.0)
            # Yield the loop once; see comment in
            # test_run_send_waits_for_guard_confirmation.
            await asyncio.sleep(0)
            self.assertTrue(self.runtime.tx.sending["waiting"])
            self.runtime.tx.abort.set()
            await task

        asyncio.run(_run())

        self.assertEqual(len(self.sent_payloads), 0)
        self.assertEqual(len(self.runtime.tx.queue), 2)
        self.assertTrue(any(msg.get("type") == "send_aborted" for msg in self.messages if isinstance(msg, dict)))

    def test_history_entry_includes_payload(self):
        """History entries must include payload for faithful requeue."""
        self.runtime.tx.queue = [self._make_item("com_ping", "")]
        self.runtime.tx.renumber_queue()
        self.runtime.tx.sending.update(active=True, idx=-1, total=1, guarding=False, sent_at=0, waiting=False)

        asyncio.run(self.runtime.tx.run_send())

        self.assertEqual(len(self.runtime.tx.history), 1)
        hist = self.runtime.tx.history[0]
        self.assertIn("payload", hist)
        self.assertEqual(hist["payload"]["cmd_id"], "com_ping")

    def test_queue_projection_includes_payload(self):
        """Queue projection must include payload for faithful duplicate."""
        item = self._make_item("com_ping", "")
        self.runtime.tx.queue = [item]
        self.runtime.tx.renumber_queue()

        projected = self.runtime.tx.queue_items_json()
        self.assertEqual(len(projected), 1)
        self.assertIn("payload", projected[0])
        self.assertEqual(projected[0]["payload"]["cmd_id"], "com_ping")


    def test_delay_ms_zero_has_no_post_send_dwell(self):
        """With `tx.delay_ms=0`, back-to-back commands must not accrue dwell time.

        The post-send dwell is bound to `tx.delay_ms`; setting it to 0
        opts out entirely for max-throughput scenarios. Two zero-delay
        commands should clear well under the 500 ms dwell floor. Threshold
        0.6 s tolerates slow-CI disk latency on `save_queue` tempfile writes.
        """
        import time as _time

        self.runtime.tx.queue = [
            self._make_item("com_ping", ""),
            self._make_item("com_ping", ""),
        ]
        self.runtime.tx.renumber_queue()
        self.runtime.tx.sending.update(active=True, idx=-1, total=2, guarding=False, sent_at=0, waiting=False)

        t0 = _time.monotonic()
        asyncio.run(self.runtime.tx.run_send())
        elapsed = _time.monotonic() - t0

        self.assertEqual(len(self.sent_payloads), 2)
        self.assertLess(elapsed, 0.6, f"run_send took {elapsed:.3f}s — expected <0.6s with delay_ms=0")

    def test_post_send_dwell_broadcasts_waiting_and_blocks(self):
        """With `tx.delay_ms>0`, the sent item dwells at queue-front with `waiting=True`.

        The dwell is what lets the UI show the SENDING animation and the
        "— delay" indicator. This verifies (a) a `send_progress` event
        with `waiting=True` is broadcast after the actual send, and (b)
        the dwell actually blocks for ~delay_ms.
        """
        import time as _time

        self.runtime.cfg["tx"]["delay_ms"] = 150
        self.runtime.tx.queue = [self._make_item("com_ping", "")]
        self.runtime.tx.renumber_queue()
        self.runtime.tx.sending.update(active=True, idx=-1, total=1, guarding=False, sent_at=0, waiting=False)

        t0 = _time.monotonic()
        asyncio.run(self.runtime.tx.run_send())
        elapsed = _time.monotonic() - t0

        self.assertEqual(len(self.sent_payloads), 1)
        self.assertGreaterEqual(elapsed, 0.13, f"run_send took {elapsed:.3f}s — expected ≥0.13s with delay_ms=150")

        waiting_events = [
            msg for msg in self.messages
            if isinstance(msg, dict)
            and msg.get("type") == "send_progress"
            and msg.get("waiting") is True
        ]
        self.assertTrue(waiting_events, f"expected a send_progress waiting=True broadcast after send, got {self.messages}")
        sent_idx = next(i for i, m in enumerate(self.messages) if isinstance(m, dict) and m.get("type") == "sent")
        waiting_idx = self.messages.index(waiting_events[0])
        self.assertGreater(waiting_idx, sent_idx, "waiting=True must come after the 'sent' event")

    def test_abort_during_post_send_dwell_still_pops_sent_item(self):
        """Aborting during the dwell must not keep the already-transmitted cmd in queue."""
        self.runtime.cfg["tx"]["delay_ms"] = 5000  # long dwell so abort can land inside it
        self.runtime.tx.queue = [self._make_item("com_ping", "")]
        self.runtime.tx.renumber_queue()
        self.runtime.tx.sending.update(active=True, idx=-1, total=1, guarding=False, sent_at=0, waiting=False)

        async def _run():
            task = asyncio.create_task(self.runtime.tx.run_send())
            await asyncio.wait_for(self.waiting_event.wait(), timeout=5.0)
            self.runtime.tx.abort.set()
            await task

        asyncio.run(_run())

        self.assertEqual(len(self.sent_payloads), 1)
        self.assertEqual(self.runtime.tx.queue, [])
        self.assertTrue(any(msg.get("type") == "send_aborted" for msg in self.messages if isinstance(msg, dict)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
