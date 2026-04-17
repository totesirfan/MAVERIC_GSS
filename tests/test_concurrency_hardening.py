"""Concurrency hardening regression tests (Session 4)."""

import asyncio
import os
import signal
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mav_gss_lib.web_runtime import runtime as runtime_mod


class _FakeService:
    def __init__(self):
        import threading
        self.clients = []
        self.lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.sending = {"active": False}


class _FakeRuntime:
    def __init__(self):
        self.rx = _FakeService()
        self.tx = _FakeService()
        self.had_clients = True
        self.shutdown_task = None


class TestScheduleShutdownCheckUsesRunningLoop(unittest.TestCase):
    def test_schedule_shutdown_check_does_not_call_get_event_loop(self):
        """schedule_shutdown_check must not call deprecated get_event_loop()."""
        rt = _FakeRuntime()

        async def run():
            with patch.object(asyncio, "get_event_loop") as gel:
                runtime_mod.schedule_shutdown_check(rt)
                self.assertFalse(
                    gel.called,
                    "schedule_shutdown_check called deprecated asyncio.get_event_loop()",
                )
            if rt.shutdown_task:
                rt.shutdown_task.cancel()
                try:
                    await rt.shutdown_task
                except (asyncio.CancelledError, BaseException):
                    pass

        asyncio.run(run())


class TestIdleShutdownUsesRaiseSignal(unittest.TestCase):
    def test_check_shutdown_uses_raise_signal_not_os_kill(self):
        """check_shutdown must use signal.raise_signal(SIGINT), not os.kill(pid, SIGINT)."""
        rt = _FakeRuntime()

        original_delay = runtime_mod.SHUTDOWN_DELAY
        runtime_mod.SHUTDOWN_DELAY = 0

        async def run():
            with patch.object(signal, "raise_signal") as raise_sig, \
                 patch.object(os, "kill") as os_kill:
                await runtime_mod.check_shutdown(rt)
                self.assertTrue(
                    raise_sig.called,
                    "check_shutdown did not call signal.raise_signal(SIGINT)",
                )
                self.assertFalse(
                    os_kill.called,
                    "check_shutdown still calls os.kill — should use signal.raise_signal",
                )

        try:
            asyncio.run(run())
        finally:
            runtime_mod.SHUTDOWN_DELAY = original_delay


class TestCheckShutdownLocksSendingRead(unittest.TestCase):
    def test_check_shutdown_reads_sending_under_send_lock(self):
        """check_shutdown must acquire runtime.tx.send_lock before reading sending['active']."""
        rt = _FakeRuntime()

        class _SpyDict(dict):
            lock_held_during_read = False

            def __init__(self, spy_lock, *args, **kw):
                super().__init__(*args, **kw)
                self._spy_lock = spy_lock

            def __getitem__(self, key):
                if key == "active":
                    _SpyDict.lock_held_during_read = self._spy_lock.is_held()
                return super().__getitem__(key)

        class _SpyLock:
            def __init__(self, inner):
                self._inner = inner
                self._held = False

            def __enter__(self):
                self._inner.acquire()
                self._held = True
                return self

            def __exit__(self, exc_type, exc, tb):
                self._held = False
                self._inner.release()

            def is_held(self):
                return self._held

        spy_lock = _SpyLock(rt.tx.send_lock)
        rt.tx.send_lock = spy_lock
        rt.tx.sending = _SpyDict(spy_lock, active=True)  # active → reschedule path

        original_delay = runtime_mod.SHUTDOWN_DELAY
        runtime_mod.SHUTDOWN_DELAY = 0

        async def run():
            with patch.object(runtime_mod, "schedule_shutdown_check"):
                await runtime_mod.check_shutdown(rt)

        try:
            asyncio.run(run())
        finally:
            runtime_mod.SHUTDOWN_DELAY = original_delay

        self.assertTrue(
            _SpyDict.lock_held_during_read,
            "check_shutdown read sending['active'] without holding send_lock",
        )


if __name__ == "__main__":
    unittest.main()
