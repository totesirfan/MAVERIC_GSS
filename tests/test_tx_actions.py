"""Direct tests for web_runtime.tx_actions handlers."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mav_gss_lib.web_runtime import tx_actions


class _RecordingWS:
    def __init__(self):
        self.sent: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


def _stub_runtime():
    rt = MagicMock()
    rt.tx.send_lock = threading.Lock()
    rt.tx.lock = threading.Lock()
    rt.tx.queue = []
    rt.tx.sending = {"active": False, "guarding": False}
    rt.tx.history = []
    rt.tx.abort = MagicMock()
    rt.tx.guard_ok = MagicMock()
    rt.tx.send_task = None

    # Renumber / save are no-ops for these tests
    rt.tx.renumber_queue = MagicMock()
    rt.tx.save_queue = MagicMock()

    async def _send_queue_update():
        return None

    rt.tx.send_queue_update = MagicMock(side_effect=_send_queue_update)
    rt.tx.run_send = MagicMock()

    # Adapter stub — simplest possible payload shape
    rt.adapter.cmd_line_to_payload.side_effect = lambda line: {"line": line}

    return rt


class TestHandleQueue(unittest.TestCase):
    """handle_queue and handle_queue_mission_cmd glue.

    validate_mission_cmd itself depends on runtime.cfg_lock/cfg/csp/ax25 and
    is already exercised end-to-end in tests/test_tx_plugin.py. Here we patch
    it to isolate the WS-handler glue: payload parse, mutation under lock,
    error propagation, and broadcast side-effect.
    """

    def test_handle_queue_appends_parsed_item(self):
        from unittest.mock import patch
        rt = _stub_runtime()
        ws = _RecordingWS()
        fake_item = {"type": "mission_cmd", "guard": False, "display": {"row": {}}}
        with patch.object(tx_actions, "validate_mission_cmd", return_value=fake_item):
            asyncio.run(tx_actions.handle_queue(rt, {"input": "com_ping"}, ws))
        self.assertEqual(rt.tx.queue, [fake_item])
        rt.tx.send_queue_update.assert_called_once()
        rt.adapter.cmd_line_to_payload.assert_called_once_with("com_ping")

    def test_handle_queue_empty_input_errors(self):
        rt = _stub_runtime()
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_queue(rt, {"input": "   "}, ws))
        self.assertEqual(rt.tx.queue, [])
        self.assertEqual(json.loads(ws.sent[0])["type"], "error")
        self.assertIn("empty input", json.loads(ws.sent[0])["error"])

    def test_handle_queue_parse_error_becomes_error_message(self):
        from unittest.mock import patch
        rt = _stub_runtime()
        rt.adapter.cmd_line_to_payload.side_effect = ValueError("bad command")
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_queue(rt, {"input": "garbage"}, ws))
        self.assertEqual(rt.tx.queue, [])
        payload = json.loads(ws.sent[0])
        self.assertEqual(payload["type"], "error")
        self.assertEqual(payload["error"], "bad command")

    def test_handle_queue_mission_cmd_appends_validated_item(self):
        from unittest.mock import patch
        rt = _stub_runtime()
        ws = _RecordingWS()
        fake_item = {"type": "mission_cmd", "guard": True, "display": {"row": {}}}
        with patch.object(tx_actions, "validate_mission_cmd", return_value=fake_item):
            asyncio.run(tx_actions.handle_queue_mission_cmd(
                rt, {"payload": {"cmd": "com_ping", "args": {}}}, ws))
        self.assertEqual(rt.tx.queue, [fake_item])
        rt.tx.send_queue_update.assert_called_once()

    def test_handle_queue_mission_cmd_validation_error(self):
        from unittest.mock import patch
        rt = _stub_runtime()
        ws = _RecordingWS()
        with patch.object(tx_actions, "validate_mission_cmd",
                          side_effect=KeyError("unknown cmd")):
            asyncio.run(tx_actions.handle_queue_mission_cmd(
                rt, {"payload": {"cmd": "bogus"}}, ws))
        self.assertEqual(rt.tx.queue, [])
        self.assertEqual(json.loads(ws.sent[0])["type"], "error")

    def test_handle_queue_errors_when_sending_active(self):
        from unittest.mock import patch
        rt = _stub_runtime()
        rt.tx.sending["active"] = True
        ws = _RecordingWS()
        fake_item = {"type": "mission_cmd", "guard": False}
        with patch.object(tx_actions, "validate_mission_cmd", return_value=fake_item):
            asyncio.run(tx_actions.handle_queue(rt, {"input": "com_ping"}, ws))
        self.assertEqual(rt.tx.queue, [])
        self.assertEqual(json.loads(ws.sent[0])["type"], "error")


class TestRequiresGuards(unittest.TestCase):
    def test_requires_idle_when_sending(self):
        rt = _stub_runtime()
        rt.tx.sending["active"] = True
        self.assertEqual(tx_actions.requires_idle(rt), "cannot modify queue during send")

    def test_requires_idle_when_not_sending(self):
        rt = _stub_runtime()
        self.assertIsNone(tx_actions.requires_idle(rt))

    def test_requires_space_when_full(self):
        rt = _stub_runtime()
        rt.tx.queue = list(range(tx_actions.MAX_QUEUE))
        err = tx_actions.requires_space(rt)
        self.assertIsNotNone(err)
        self.assertIn("queue full", err)

    def test_requires_space_when_below_limit(self):
        rt = _stub_runtime()
        self.assertIsNone(tx_actions.requires_space(rt))


class TestHandleDelete(unittest.TestCase):
    def test_delete_valid_index(self):
        rt = _stub_runtime()
        rt.tx.queue = [{"type": "delay", "delay_ms": 100}, {"type": "delay", "delay_ms": 200}]
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_delete(rt, {"index": 0}, ws))
        self.assertEqual(len(rt.tx.queue), 1)
        self.assertEqual(rt.tx.queue[0]["delay_ms"], 200)
        rt.tx.send_queue_update.assert_called_once()

    def test_delete_invalid_index_is_noop(self):
        rt = _stub_runtime()
        rt.tx.queue = [{"type": "delay", "delay_ms": 100}]
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_delete(rt, {"index": 99}, ws))
        self.assertEqual(len(rt.tx.queue), 1)

    def test_delete_errors_when_sending_active(self):
        rt = _stub_runtime()
        rt.tx.sending["active"] = True
        rt.tx.queue = [{"type": "delay", "delay_ms": 100}]
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_delete(rt, {"index": 0}, ws))
        self.assertEqual(len(rt.tx.queue), 1)  # unchanged
        self.assertEqual(len(ws.sent), 1)
        payload = json.loads(ws.sent[0])
        self.assertEqual(payload["type"], "error")


class TestHandleClear(unittest.TestCase):
    def test_clear_empties_queue(self):
        rt = _stub_runtime()
        rt.tx.queue = [{"type": "delay", "delay_ms": 1}, {"type": "delay", "delay_ms": 2}]
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_clear(rt, {}, ws))
        self.assertEqual(rt.tx.queue, [])


class TestHandleUndo(unittest.TestCase):
    def test_undo_pops_last(self):
        rt = _stub_runtime()
        rt.tx.queue = [{"type": "delay", "delay_ms": 1}, {"type": "delay", "delay_ms": 2}]
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_undo(rt, {}, ws))
        self.assertEqual(len(rt.tx.queue), 1)
        self.assertEqual(rt.tx.queue[0]["delay_ms"], 1)

    def test_undo_empty_queue_is_noop(self):
        rt = _stub_runtime()
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_undo(rt, {}, ws))
        self.assertEqual(rt.tx.queue, [])


class TestHandleGuard(unittest.TestCase):
    def test_guard_toggles_on_mission_cmd(self):
        rt = _stub_runtime()
        rt.tx.queue = [{"type": "mission_cmd", "guard": False}]
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_guard(rt, {"index": 0}, ws))
        self.assertTrue(rt.tx.queue[0]["guard"])
        asyncio.run(tx_actions.handle_guard(rt, {"index": 0}, ws))
        self.assertFalse(rt.tx.queue[0]["guard"])

    def test_guard_noop_on_delay(self):
        rt = _stub_runtime()
        rt.tx.queue = [{"type": "delay", "delay_ms": 1}]
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_guard(rt, {"index": 0}, ws))
        self.assertNotIn("guard", rt.tx.queue[0])


class TestHandleReorder(unittest.TestCase):
    def test_reorder_applies_new_order(self):
        rt = _stub_runtime()
        rt.tx.queue = [
            {"type": "delay", "delay_ms": 1},
            {"type": "delay", "delay_ms": 2},
            {"type": "delay", "delay_ms": 3},
        ]
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_reorder(rt, {"order": [2, 0, 1]}, ws))
        self.assertEqual([q["delay_ms"] for q in rt.tx.queue], [3, 1, 2])

    def test_reorder_wrong_length_is_noop(self):
        rt = _stub_runtime()
        rt.tx.queue = [{"type": "delay", "delay_ms": 1}, {"type": "delay", "delay_ms": 2}]
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_reorder(rt, {"order": [0]}, ws))
        self.assertEqual([q["delay_ms"] for q in rt.tx.queue], [1, 2])


class TestHandleAddDelay(unittest.TestCase):
    def test_add_delay_appends(self):
        rt = _stub_runtime()
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_add_delay(rt, {"delay_ms": 2500}, ws))
        self.assertEqual(len(rt.tx.queue), 1)
        self.assertEqual(rt.tx.queue[0]["type"], "delay")
        self.assertEqual(rt.tx.queue[0]["delay_ms"], 2500)

    def test_add_delay_clamps_high(self):
        rt = _stub_runtime()
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_add_delay(rt, {"delay_ms": 999_999}, ws))
        self.assertEqual(rt.tx.queue[0]["delay_ms"], 300_000)

    def test_add_delay_clamps_low(self):
        rt = _stub_runtime()
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_add_delay(rt, {"delay_ms": -100}, ws))
        self.assertEqual(rt.tx.queue[0]["delay_ms"], 0)

    def test_add_delay_with_index_inserts(self):
        rt = _stub_runtime()
        rt.tx.queue = [{"type": "delay", "delay_ms": 100}]
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_add_delay(rt, {"delay_ms": 50, "index": 0}, ws))
        self.assertEqual([q["delay_ms"] for q in rt.tx.queue], [50, 100])


class TestHandleEditDelay(unittest.TestCase):
    def test_edit_delay_changes_ms(self):
        rt = _stub_runtime()
        rt.tx.queue = [{"type": "delay", "delay_ms": 100}]
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_edit_delay(rt, {"index": 0, "delay_ms": 750}, ws))
        self.assertEqual(rt.tx.queue[0]["delay_ms"], 750)

    def test_edit_delay_on_non_delay_is_noop(self):
        rt = _stub_runtime()
        rt.tx.queue = [{"type": "mission_cmd", "guard": False}]
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_edit_delay(rt, {"index": 0, "delay_ms": 750}, ws))
        self.assertNotIn("delay_ms", rt.tx.queue[0])


class TestHandleSend(unittest.TestCase):
    def test_send_empty_queue_errors(self):
        rt = _stub_runtime()
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_send(rt, {}, ws))
        self.assertEqual(len(ws.sent), 1)
        self.assertEqual(json.loads(ws.sent[0])["type"], "error")
        self.assertFalse(rt.tx.sending["active"])

    def test_send_marks_active_and_creates_task(self):
        async def _run():
            rt = _stub_runtime()
            rt.tx.queue = [{"type": "mission_cmd", "guard": False}]

            async def _fake_run_send():
                return None

            rt.tx.run_send = _fake_run_send
            ws = _RecordingWS()
            await tx_actions.handle_send(rt, {}, ws)
            self.assertTrue(rt.tx.sending["active"])
            self.assertEqual(rt.tx.sending["total"], 1)
            if rt.tx.send_task:
                rt.tx.send_task.cancel()
                try:
                    await rt.tx.send_task
                except (asyncio.CancelledError, BaseException):
                    pass

        asyncio.run(_run())

    def test_send_already_active_errors(self):
        rt = _stub_runtime()
        rt.tx.sending["active"] = True
        rt.tx.queue = [{"type": "mission_cmd", "guard": False}]
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_send(rt, {}, ws))
        self.assertEqual(json.loads(ws.sent[0])["type"], "error")


class TestAbortAndGuardSignals(unittest.TestCase):
    def test_abort_sets_event(self):
        rt = _stub_runtime()
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_abort(rt, {}, ws))
        rt.tx.abort.set.assert_called_once()

    def test_guard_approve_sets_event(self):
        rt = _stub_runtime()
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_guard_approve(rt, {}, ws))
        rt.tx.guard_ok.set.assert_called_once()

    def test_guard_reject_sets_abort(self):
        rt = _stub_runtime()
        ws = _RecordingWS()
        asyncio.run(tx_actions.handle_guard_reject(rt, {}, ws))
        rt.tx.abort.set.assert_called_once()


class TestActionsTableCompleteness(unittest.TestCase):
    def test_every_action_has_handler_and_guard_list(self):
        expected = {
            "queue", "queue_mission_cmd", "delete", "clear", "undo", "guard",
            "reorder", "add_delay", "edit_delay", "send", "abort",
            "guard_approve", "guard_reject",
        }
        self.assertEqual(set(tx_actions.ACTIONS.keys()), expected)
        for name, spec in tx_actions.ACTIONS.items():
            self.assertTrue(callable(spec.handler), f"{name} handler not callable")
            self.assertIsInstance(spec.guards, list, f"{name} guards not a list")


if __name__ == "__main__":
    unittest.main()
