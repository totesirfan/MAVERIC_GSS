"""End-to-end: registry → /ws/alarms broadcast, fire/ack/recurrence, removed flag,
plus one-tick lifespan integration."""
from __future__ import annotations

import json
import time
import unittest

from mav_gss_lib.platform.alarms.contract import (
    AlarmSource, AlarmState, Severity,
)
from mav_gss_lib.platform.alarms.evaluators.parameter import (
    PluginRegistry, evaluate_parameter,
)
from mav_gss_lib.platform.alarms.registry import AlarmRegistry, Verdict
from mav_gss_lib.platform.alarms.schema import parse_alarm_rules


class TestRegistryE2E(unittest.TestCase):
    def test_full_lifecycle_emits_removed_on_drop(self):
        """Fire CRITICAL, ack, clear (acked+cleared → removed=True), re-fire fresh."""
        registry = AlarmRegistry()
        rules = parse_alarm_rules({"alarm": {"static": {
            "warning": {"max": 60}, "critical": {"max": 70},
        }}})

        # Fire
        verdicts = evaluate_parameter("param.gnc.ADCS_TMP", rules, 80,
                                      plugins=PluginRegistry({}))
        ch1 = registry.observe(verdicts[0], now_ms=1000)
        self.assertEqual(ch1.event.state, AlarmState.UNACKED_ACTIVE)
        self.assertFalse(ch1.removed)

        # Ack
        ch2 = registry.acknowledge("param.gnc.ADCS_TMP", now_ms=2000, operator="op")
        self.assertEqual(ch2.event.state, AlarmState.ACKED_ACTIVE)
        self.assertFalse(ch2.removed)

        # Clear (value drops below warning) — registry pops the entry
        verdicts = evaluate_parameter("param.gnc.ADCS_TMP", rules, 30,
                                      plugins=PluginRegistry({}))
        ch3 = registry.observe(verdicts[0], now_ms=3000)
        self.assertIsNotNone(ch3)
        self.assertTrue(ch3.removed)
        self.assertEqual(registry.snapshot(), [])

        # Re-fire fresh
        verdicts = evaluate_parameter("param.gnc.ADCS_TMP", rules, 80,
                                      plugins=PluginRegistry({}))
        ch4 = registry.observe(verdicts[0], now_ms=4000)
        self.assertEqual(ch4.event.state, AlarmState.UNACKED_ACTIVE)
        self.assertEqual(ch4.event.first_seen_ms, 4000)

    def test_carrier_suppression_blocks_evaluation(self):
        """Stale carrier → parameter-evaluator hook should skip; verify the
        registry-side gate (`carrier_stale_for`) is the single source."""
        registry = AlarmRegistry()
        registry.set_parameter_carriers({"gnc.RATE": ["tlm_beacon"]})
        registry.observe(Verdict(
            id="container.tlm_beacon.stale", source=AlarmSource.CONTAINER,
            label="BEACON STALE", severity=Severity.WARNING, detail="",
            context={"container_id": "tlm_beacon"},
        ), now_ms=1000)
        self.assertTrue(registry.carrier_stale_for("gnc.RATE"))

        # Recovery clears suppression
        registry.observe(Verdict(
            id="container.tlm_beacon.stale", source=AlarmSource.CONTAINER,
            label="BEACON STALE", severity=None, detail="",
            context={"container_id": "tlm_beacon"},
        ), now_ms=2000)
        self.assertFalse(registry.carrier_stale_for("gnc.RATE"))


class TestTickOnce(unittest.TestCase):
    """Drive `_tick_once` directly. No sleep, no event loop required."""

    def test_one_tick_drives_silence_and_stale(self):
        from collections import deque
        from types import SimpleNamespace
        from mav_gss_lib.platform.alarms.dispatch import AlarmDispatch
        from mav_gss_lib.platform.alarms.evaluators.container import ContainerStaleSpec
        from mav_gss_lib.platform.alarms.evaluators.platform import SILENCE_CRITICAL_S
        from mav_gss_lib.server.app import _tick_once

        registry = AlarmRegistry()
        audited: list = []

        class _Sink:
            def write_alarm(self, ch, ts_ms):
                audited.append(ch)

        class _NoopTarget:
            async def broadcast_text(self, _text):
                pass  # not exercised; loop=None disables broadcast

        dispatch = AlarmDispatch(
            audit_sink=_Sink(),
            broadcast_target=_NoopTarget(),
            loop=None,  # broadcast disabled in unit context
        )

        runtime = SimpleNamespace(
            alarm_registry=registry,
            _alarm_dispatch=dispatch,
            rx=SimpleNamespace(
                last_rx_at=time.time() - SILENCE_CRITICAL_S - 1,
                status=SimpleNamespace(get=lambda: "OK"),
                crc_window=deque(),
                dup_window=deque(),
                last_arrival_ms={"tlm_beacon": int(time.time() * 1000) - 50_000_000},
            ),
            radio=SimpleNamespace(
                enabled=lambda: False,
                status=lambda: {"state": "disabled"},
            ),
        )
        container_specs = {
            "tlm_beacon": ContainerStaleSpec(
                "tlm_beacon", "TLM BEACON", 60000,
                warning_after_ms=1_800_000, critical_after_ms=43_200_000,
            ),
        }

        _tick_once(runtime, container_specs, int(time.time() * 1000))

        ids = sorted(c.event.id for c in audited)
        self.assertIn("platform.silence", ids)
        self.assertIn("container.tlm_beacon.stale", ids)

    def test_idle_manual_radio_suppresses_startup_zmq_and_radio_alarms(self):
        from collections import deque
        from types import SimpleNamespace
        from mav_gss_lib.platform.alarms.dispatch import AlarmDispatch
        from mav_gss_lib.server.app import _tick_once

        registry = AlarmRegistry()
        audited: list = []

        class _Sink:
            def write_alarm(self, ch, ts_ms):
                audited.append(ch)

        class _NoopTarget:
            async def broadcast_text(self, _text):
                pass

        dispatch = AlarmDispatch(
            audit_sink=_Sink(),
            broadcast_target=_NoopTarget(),
            loop=None,
        )

        runtime = SimpleNamespace(
            alarm_registry=registry,
            _alarm_dispatch=dispatch,
            rx=SimpleNamespace(
                last_rx_at=0,
                status=SimpleNamespace(get=lambda: "RETRY"),
                crc_window=deque(),
                dup_window=deque(),
                last_arrival_ms={},
            ),
            radio=SimpleNamespace(
                status=lambda: {
                    "enabled": True,
                    "autostart": False,
                    "state": "stopped",
                },
            ),
        )

        _tick_once(runtime, {}, int(time.time() * 1000))

        self.assertEqual(audited, [])
        self.assertEqual(registry.snapshot(), [])

    def test_radio_startup_grace_suppresses_transient_zmq_retry(self):
        from collections import deque
        from types import SimpleNamespace
        from mav_gss_lib.platform.alarms.dispatch import AlarmDispatch
        from mav_gss_lib.server.app import _tick_once

        registry = AlarmRegistry()
        audited: list = []

        class _Sink:
            def write_alarm(self, ch, ts_ms):
                audited.append(ch)

        class _NoopTarget:
            async def broadcast_text(self, _text):
                pass

        now_ms = int(time.time() * 1000)
        runtime = SimpleNamespace(
            alarm_registry=registry,
            _alarm_dispatch=AlarmDispatch(
                audit_sink=_Sink(),
                broadcast_target=_NoopTarget(),
                loop=None,
            ),
            rx=SimpleNamespace(
                last_rx_at=0,
                status=SimpleNamespace(get=lambda: "RETRY"),
                crc_window=deque(),
                dup_window=deque(),
                last_arrival_ms={},
            ),
            radio=SimpleNamespace(
                status=lambda: {
                    "enabled": True,
                    "autostart": False,
                    "state": "running",
                    "started_at_ms": now_ms,
                },
            ),
        )

        _tick_once(runtime, {}, now_ms)

        self.assertEqual(audited, [])
        self.assertEqual(registry.snapshot(), [])

    def test_zmq_retry_alarms_after_radio_startup_grace(self):
        from collections import deque
        from types import SimpleNamespace
        from mav_gss_lib.platform.alarms.dispatch import AlarmDispatch
        from mav_gss_lib.server.app import (
            RADIO_ZMQ_STARTUP_GRACE_MS,
            _tick_once,
        )

        registry = AlarmRegistry()
        audited: list = []

        class _Sink:
            def write_alarm(self, ch, ts_ms):
                audited.append(ch)

        class _NoopTarget:
            async def broadcast_text(self, _text):
                pass

        now_ms = int(time.time() * 1000)
        runtime = SimpleNamespace(
            alarm_registry=registry,
            _alarm_dispatch=AlarmDispatch(
                audit_sink=_Sink(),
                broadcast_target=_NoopTarget(),
                loop=None,
            ),
            rx=SimpleNamespace(
                last_rx_at=0,
                status=SimpleNamespace(get=lambda: "RETRY"),
                crc_window=deque(),
                dup_window=deque(),
                last_arrival_ms={},
            ),
            radio=SimpleNamespace(
                status=lambda: {
                    "enabled": True,
                    "autostart": False,
                    "state": "running",
                    "started_at_ms": now_ms - RADIO_ZMQ_STARTUP_GRACE_MS - 1,
                },
            ),
        )

        _tick_once(runtime, {}, now_ms)

        self.assertEqual([ch.event.id for ch in audited], ["platform.zmq"])


if __name__ == "__main__":
    unittest.main()
