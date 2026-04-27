"""Tests for TX → RX blackout window (simulated T/R switching)."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.server.state import create_runtime


class TestRxBlackoutDrop(unittest.TestCase):
    """RxService._should_drop_rx respects runtime.tx_blackout_until."""

    def setUp(self):
        self.runtime = create_runtime()

    def test_drops_when_before_deadline(self):
        self.runtime.tx_blackout_until = time.time() + 1.0
        self.assertTrue(self.runtime.rx._should_drop_rx(time.time()))

    def test_keeps_when_after_deadline(self):
        self.runtime.tx_blackout_until = time.time() - 0.1
        self.assertFalse(self.runtime.rx._should_drop_rx(time.time()))

    def test_keeps_when_feature_idle(self):
        self.runtime.tx_blackout_until = 0.0
        self.assertFalse(self.runtime.rx._should_drop_rx(time.time()))


import asyncio
import tempfile

import mav_gss_lib.server.tx._send_coordinator as tx_service
from mav_gss_lib.server.tx.queue import validate_mission_cmd


def _make_payload(cmd_id="com_ping", args="", dest="LPPM"):
    return {"cmd_id": cmd_id, "args": args, "dest": dest, "echo": "NONE", "ptype": "CMD"}


class TestTxArmsBlackout(unittest.TestCase):
    """run_send arms (or clears) runtime.tx_blackout_until based on config."""

    def setUp(self):
        self.runtime = create_runtime()
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime.platform_cfg.setdefault("general", {})["log_dir"] = self.tmp.name
        self.runtime.platform_cfg.setdefault("tx", {})["delay_ms"] = 0
        self.runtime.tx.queue.clear()
        self.runtime.tx.history.clear()
        self.runtime.tx.zmq_sock = object()
        self.runtime.tx.log = None
        self.rx_messages = []
        self.tx_messages = []

        async def _capture_tx(msg):
            self.tx_messages.append(msg)

        async def _capture_rx(msg):
            self.rx_messages.append(msg)

        async def _capture_queue_update():
            return None

        self.runtime.tx.broadcast = _capture_tx
        self.runtime.rx.broadcast = _capture_rx
        self.runtime.tx.send_queue_update = _capture_queue_update

        self._orig_send_pdu = tx_service.send_pdu
        tx_service.send_pdu = lambda _sock, _payload: True

    def tearDown(self):
        tx_service.send_pdu = self._orig_send_pdu
        self.tmp.cleanup()

    def _queue_ping(self):
        item = validate_mission_cmd(_make_payload("com_ping"), runtime=self.runtime)
        self.runtime.tx.queue.append(item)
        self.runtime.tx.sending.update(
            active=True, idx=-1, total=1, guarding=False, sent_at=0, waiting=False,
        )

    def test_arms_deadline_when_configured(self):
        self.runtime.platform_cfg["rx"]["tx_blackout_ms"] = 750
        self._queue_ping()
        before = time.time()
        asyncio.run(self.runtime.tx.run_send())
        after = time.time()

        self.assertGreaterEqual(self.runtime.tx_blackout_until, before + 0.75 - 0.02)
        self.assertLessEqual(self.runtime.tx_blackout_until, after + 0.75 + 0.02)
        self.assertTrue(
            any(m.get("type") == "blackout" and m.get("ms") == 750 for m in self.rx_messages),
            f"no blackout event in rx_messages: {self.rx_messages}",
        )

    def test_disabled_leaves_deadline_zero(self):
        self.runtime.platform_cfg["rx"]["tx_blackout_ms"] = 0
        self._queue_ping()
        asyncio.run(self.runtime.tx.run_send())
        self.assertEqual(self.runtime.tx_blackout_until, 0.0)
        self.assertFalse(
            any(m.get("type") == "blackout" for m in self.rx_messages),
            "blackout event should not be emitted when feature is disabled",
        )

    def test_disabling_clears_stale_deadline_and_broadcasts_clear(self):
        # Prior batch armed a far-future deadline.
        self.runtime.tx_blackout_until = time.time() + 10.0
        self.runtime.platform_cfg["rx"]["tx_blackout_ms"] = 0
        self._queue_ping()
        asyncio.run(self.runtime.tx.run_send())
        self.assertEqual(self.runtime.tx_blackout_until, 0.0)
        # An explicit clear (ms=0) must reach RX clients so pop-out views hide
        # their indicator without waiting for the stale timer to drain.
        clears = [m for m in self.rx_messages if m.get("type") == "blackout" and m.get("ms") == 0]
        self.assertEqual(len(clears), 1, f"expected one clear event, got {self.rx_messages}")

    def test_disabled_without_prior_window_does_not_broadcast(self):
        # Feature disabled, no prior deadline — no clear event should fire.
        self.runtime.tx_blackout_until = 0.0
        self.runtime.platform_cfg["rx"]["tx_blackout_ms"] = 0
        self._queue_ping()
        asyncio.run(self.runtime.tx.run_send())
        self.assertFalse(
            any(m.get("type") == "blackout" for m in self.rx_messages),
            "no blackout event should be emitted when disabled with no armed deadline",
        )


if __name__ == "__main__":
    unittest.main()
