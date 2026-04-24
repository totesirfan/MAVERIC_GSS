"""Regression tests for Session 1 safety-net changes."""

from __future__ import annotations

import asyncio
import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.server._task_utils import log_task_exception


class TestLogTaskException(unittest.TestCase):
    def test_logs_exception_when_task_raises(self):
        async def _run():
            async def boom():
                raise RuntimeError("boom")

            task = asyncio.create_task(boom())
            task.add_done_callback(log_task_exception("test-task"))
            try:
                await task
            except RuntimeError:
                pass

        with self.assertLogs(level=logging.ERROR) as captured:
            asyncio.run(_run())
        self.assertTrue(any("test-task" in line and "boom" in line for line in captured.output))

    def test_does_not_log_on_successful_task(self):
        async def _run():
            async def ok():
                return 42

            task = asyncio.create_task(ok())
            task.add_done_callback(log_task_exception("test-task"))
            await task

        with self.assertNoLogs(level=logging.ERROR):
            asyncio.run(_run())

    def test_does_not_log_on_cancelled_task(self):
        async def _run():
            async def never():
                await asyncio.sleep(10)

            task = asyncio.create_task(never())
            task.add_done_callback(log_task_exception("test-task"))
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        with self.assertNoLogs(level=logging.ERROR):
            asyncio.run(_run())


class TestTaskCallbacksWired(unittest.TestCase):
    """Verify every asyncio.create_task in the web runtime has a done-callback.

    This is a structural test: reading each call site's 6-line window and
    checking for the presence of both `add_done_callback` and
    `log_task_exception`. Comment-only lines are stripped before the check
    so `# TODO wire add_done_callback(...)` cannot fool the test into
    thinking the wiring is present.
    """

    def _assert_callback_wired(self, file_relpath: str, create_task_line_substr: str):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        src = (root / file_relpath).read_text().splitlines()
        idx = next(i for i, line in enumerate(src) if create_task_line_substr in line)
        # Strip comment-only lines to avoid false positives from commented-out wiring.
        window_lines = [ln for ln in src[idx:idx + 6] if not ln.lstrip().startswith("#")]
        window = "\n".join(window_lines)
        self.assertIn("add_done_callback", window, f"missing add_done_callback near {file_relpath}:{idx + 1}")
        self.assertIn("log_task_exception", window, f"missing log_task_exception near {file_relpath}:{idx + 1}")

    def test_rx_broadcast_task_has_callback(self):
        self._assert_callback_wired(
            "mav_gss_lib/server/app.py",
            "runtime.rx.broadcast_task = asyncio.create_task(runtime.rx.broadcast_loop())",
        )

    def test_preflight_task_has_callback(self):
        self._assert_callback_wired(
            "mav_gss_lib/server/app.py",
            "runtime.preflight_task = asyncio.create_task(run_preflight_and_broadcast(runtime))",
        )

    def test_tx_send_task_has_callback(self):
        self._assert_callback_wired(
            "mav_gss_lib/server/tx/actions.py",
            "runtime.tx.send_task = asyncio.create_task(runtime.tx.run_send())",
        )

    def test_shutdown_task_has_callback(self):
        # shutdown.py uses loop.create_task(...) after modernizing away from
        # the deprecated asyncio.get_event_loop() form.
        self._assert_callback_wired(
            "mav_gss_lib/server/shutdown.py",
            "runtime.shutdown_task = loop.create_task(check_shutdown(runtime))",
        )


class TestPreflightBroadcastCullsDeadClients(unittest.TestCase):
    """The preflight broadcast must remove clients whose send_text raises."""

    def test_dead_client_is_removed(self):
        import threading

        from mav_gss_lib.server.ws.preflight import _broadcast

        class FakeRuntime:
            def __init__(self):
                self.preflight_lock = threading.Lock()
                self.preflight_results = []
                self.preflight_clients = []

        class LiveWS:
            def __init__(self):
                self.sent = []

            async def send_text(self, text):
                self.sent.append(text)

        class DeadWS:
            async def send_text(self, text):
                raise ConnectionError("socket closed")

        runtime = FakeRuntime()
        live = LiveWS()
        dead = DeadWS()
        runtime.preflight_clients.extend([live, dead])

        async def _run():
            await _broadcast(runtime, {"type": "check", "label": "x", "status": "ok"})

        asyncio.run(_run())

        self.assertEqual(len(live.sent), 1, "live client should have received the event")
        self.assertNotIn(dead, runtime.preflight_clients, "dead client should have been removed")
        self.assertIn(live, runtime.preflight_clients, "live client must remain")

        # Second broadcast — dead client should not be re-attempted.
        async def _run2():
            await _broadcast(runtime, {"type": "check", "label": "second", "status": "ok"})

        asyncio.run(_run2())
        self.assertEqual(
            len(live.sent), 2,
            "live client should have received the second event too",
        )
        # If the dead client had been re-attempted, DeadWS.send_text would have
        # raised — but our assertion is indirect: DeadWS is no longer in the
        # list, so it can't be iterated at all.

    def test_backlog_still_records_event(self):
        import threading

        from mav_gss_lib.server.ws.preflight import _broadcast

        class FakeRuntime:
            def __init__(self):
                self.preflight_lock = threading.Lock()
                self.preflight_results = []
                self.preflight_clients = []

        runtime = FakeRuntime()
        asyncio.run(_broadcast(runtime, {"type": "check", "label": "y", "status": "fail"}))
        self.assertEqual(len(runtime.preflight_results), 1)
        self.assertEqual(runtime.preflight_results[0]["label"], "y")


class TestNoSleepPollingInTxRuntimeTests(unittest.TestCase):
    """Regression: test_ops_tx_runtime.py must not use asyncio.sleep polling loops."""

    def test_no_sleep_based_waits(self):
        from pathlib import Path

        path = Path(__file__).resolve().parent / "test_ops_tx_runtime.py"
        src = path.read_text()
        # The legacy pattern we are eliminating is exactly:
        #   for _ in range(20):
        #       if self.runtime.tx.sending[...]:
        #           break
        #       await asyncio.sleep(0.02)
        self.assertNotIn(
            "await asyncio.sleep(0.02)",
            src,
            "test_ops_tx_runtime.py still contains sleep-based polling — replace with Event signalling",
        )


class TestOpsTestSupportImportIsSideEffectFree(unittest.TestCase):
    def test_importing_does_not_load_config(self):
        import importlib
        import sys

        # Drop ops_test_support from the cache so we get a fresh import.
        to_drop = [name for name in list(sys.modules) if name == "ops_test_support"]
        for name in to_drop:
            del sys.modules[name]

        loaded_config_calls = []

        # Monkey-patch load_split_config BEFORE importing ops_test_support.
        import mav_gss_lib.config as config_module
        real_load = config_module.load_split_config

        def _tracking_load(*a, **kw):
            loaded_config_calls.append(True)
            return real_load(*a, **kw)

        config_module.load_split_config = _tracking_load
        try:
            importlib.import_module("ops_test_support")
            self.assertEqual(
                loaded_config_calls, [],
                "ops_test_support should not call load_split_config at import time",
            )
        finally:
            config_module.load_split_config = real_load

    def test_accessing_cmd_defs_still_works(self):
        # Force a fresh import to exercise the lazy accessor.
        import importlib
        import sys

        if "ops_test_support" in sys.modules:
            del sys.modules["ops_test_support"]
        mod = importlib.import_module("ops_test_support")
        self.assertIsNotNone(mod.CMD_DEFS)
        self.assertIsInstance(mod.CMD_DEFS, dict)


class TestLogWriterBatchesFlushes(unittest.TestCase):
    """Regression for C-3: _writer_loop must not call flush() per item."""

    def test_flush_is_not_called_per_item(self):
        import tempfile, time
        from mav_gss_lib.logging import SessionLog

        with tempfile.TemporaryDirectory() as tmp:
            log = SessionLog(tmp, "tcp://127.0.0.1:0", "0.0.0")
            try:
                jsonl_flushes = [0]
                text_flushes = [0]
                real_jsonl_flush = log._jsonl_f.flush
                real_text_flush = log._text_f.flush

                def _count_jsonl():
                    jsonl_flushes[0] += 1
                    real_jsonl_flush()

                def _count_text():
                    text_flushes[0] += 1
                    real_text_flush()

                log._jsonl_f.flush = _count_jsonl
                log._text_f.flush = _count_text

                for i in range(200):
                    log.write_jsonl({"i": i})
                    log._write_entry([f"line-{i}"])
            finally:
                log.close()

            total_flushes = jsonl_flushes[0] + text_flushes[0]
            self.assertGreater(
                total_flushes, 0,
                "writer loop never flushed — durability regression",
            )
            self.assertLess(
                total_flushes, 25,
                f"writer loop flushed {total_flushes} times for 400 items — expected <25 (batched)",
            )

    def test_close_flushes_pending_writes(self):
        import tempfile
        from mav_gss_lib.logging import SessionLog

        with tempfile.TemporaryDirectory() as tmp:
            log = SessionLog(tmp, "tcp://127.0.0.1:0", "0.0.0")
            jsonl_path = log.jsonl_path
            log.write_jsonl({"hello": "world"})
            log.close()

            with open(jsonl_path) as fh:
                content = fh.read()
            self.assertIn('"hello"', content)

    def test_idle_writer_flushes_within_cadence(self):
        """A single write followed by silence must reach disk within ~_FLUSH_EVERY_S."""
        import tempfile, time
        from mav_gss_lib.logging import SessionLog
        from mav_gss_lib.logging._base import _BaseLog

        with tempfile.TemporaryDirectory() as tmp:
            log = SessionLog(tmp, "tcp://127.0.0.1:0", "0.0.0")
            try:
                jsonl_path = log.jsonl_path
                log.write_jsonl({"alone": True})
                time.sleep(_BaseLog._FLUSH_EVERY_S + 0.4)
                with open(jsonl_path) as fh:
                    content = fh.read()
                self.assertIn(
                    '"alone"', content,
                    "idle writer thread did not flush within _FLUSH_EVERY_S — "
                    "_writer_loop is likely blocking on queue.get() without a timeout",
                )
            finally:
                log.close()


class TestTxEventsAreAsyncio(unittest.TestCase):
    """Regression for H-15: abort/guard_ok must be asyncio.Event, not threading.Event."""

    def test_abort_is_asyncio_event(self):
        import asyncio as _asyncio
        from mav_gss_lib.server.state import create_runtime

        runtime = create_runtime()
        self.assertIsInstance(runtime.tx.abort, _asyncio.Event)

    def test_guard_ok_is_asyncio_event(self):
        import asyncio as _asyncio
        from mav_gss_lib.server.state import create_runtime

        runtime = create_runtime()
        self.assertIsInstance(runtime.tx.guard_ok, _asyncio.Event)

    def test_wait_ms_returns_immediately_when_abort_fires(self):
        """abort during a 5s delay must wake within ~50 ms, not within 100 ms polling."""
        import asyncio as _asyncio
        import time as _time
        from mav_gss_lib.server.state import create_runtime

        runtime = create_runtime()

        async def _run():
            task = _asyncio.create_task(runtime.tx._wait_ms(5000))
            await _asyncio.sleep(0.02)
            t0 = _time.monotonic()
            runtime.tx.abort.set()
            result = await task
            elapsed = _time.monotonic() - t0
            return result, elapsed

        result, elapsed = _asyncio.run(_run())
        self.assertTrue(result)
        self.assertLess(elapsed, 0.300, f"wakeup latency {elapsed:.3f}s — suggests polling, not asyncio.Event")


if __name__ == "__main__":
    unittest.main(verbosity=2)
