"""AlarmRegistry — state machine, persistence, latching, carrier suppression, removed flag."""
from __future__ import annotations

import unittest

from mav_gss_lib.platform.alarms import AlarmSource, AlarmState, Severity
from mav_gss_lib.platform.alarms.registry import AlarmRegistry, Verdict


def _v(aid, sev, *, source=AlarmSource.PARAMETER, label="TEST", detail="",
       persistence=1, latched=False, context=None):
    return Verdict(id=aid, source=source, label=label, severity=sev, detail=detail,
                   context=context or {}, persistence_required=persistence,
                   latched=latched)


def _container_v(cid, sev, **kwargs):
    """Container verdict helper — embeds container_id in context, where
    CarrierStaleIndex reads it from."""
    return _v(
        f"container.{cid}.stale", sev,
        source=AlarmSource.CONTAINER, label=f"{cid.upper()} STALE",
        context={"container_id": cid}, **kwargs,
    )


class TestStateMachine(unittest.TestCase):
    def test_first_fire(self):
        r = AlarmRegistry()
        ch = r.observe(_v("p.x", Severity.CRITICAL), now_ms=1000)
        self.assertIsNotNone(ch)
        self.assertEqual(ch.event.state, AlarmState.UNACKED_ACTIVE)
        self.assertFalse(ch.removed)
        self.assertIsNone(ch.prev_state)

    def test_redundant_same_severity_no_change(self):
        r = AlarmRegistry()
        r.observe(_v("p.x", Severity.WARNING), now_ms=1000)
        self.assertIsNone(r.observe(_v("p.x", Severity.WARNING), now_ms=1500))

    def test_detail_update_at_same_severity_emits_change(self):
        # Detail/context updates at same severity DO broadcast so UI sees fresh values.
        r = AlarmRegistry()
        r.observe(_v("p.x", Severity.WARNING, detail="35°C"), now_ms=1000)
        ch = r.observe(_v("p.x", Severity.WARNING, detail="40°C"), now_ms=1100)
        self.assertIsNotNone(ch)
        self.assertEqual(ch.event.detail, "40°C")

    def test_severity_escalation(self):
        r = AlarmRegistry()
        r.observe(_v("p.x", Severity.WARNING), now_ms=1000)
        ch = r.observe(_v("p.x", Severity.CRITICAL), now_ms=2000)
        self.assertEqual(ch.event.severity, Severity.CRITICAL)
        self.assertEqual(ch.prev_severity, Severity.WARNING)

    def test_clear_unacked_active_to_unacked_cleared(self):
        r = AlarmRegistry()
        r.observe(_v("p.x", Severity.WARNING), now_ms=1000)
        ch = r.observe(_v("p.x", None), now_ms=2000)
        self.assertEqual(ch.event.state, AlarmState.UNACKED_CLEARED)
        self.assertFalse(ch.removed)

    def test_ack_unacked_active_to_acked_active(self):
        r = AlarmRegistry()
        r.observe(_v("p.x", Severity.WARNING), now_ms=1000)
        ch = r.acknowledge("p.x", now_ms=1500, operator="op")
        self.assertEqual(ch.event.state, AlarmState.ACKED_ACTIVE)
        self.assertEqual(ch.operator, "op")
        self.assertFalse(ch.removed)

    def test_clear_acked_active_emits_removed(self):
        r = AlarmRegistry()
        r.observe(_v("p.x", Severity.WARNING), now_ms=1000)
        r.acknowledge("p.x", now_ms=1500)
        ch = r.observe(_v("p.x", None), now_ms=2000)
        self.assertIsNotNone(ch)
        self.assertTrue(ch.removed)
        self.assertEqual(r.snapshot(), [])

    def test_ack_unacked_cleared_emits_removed(self):
        r = AlarmRegistry()
        r.observe(_v("p.x", Severity.WARNING), now_ms=1000)
        r.observe(_v("p.x", None), now_ms=2000)
        ch = r.acknowledge("p.x", now_ms=2500)
        self.assertTrue(ch.removed)
        self.assertEqual(r.snapshot(), [])

    def test_recurrence_from_unacked_cleared_rearms(self):
        r = AlarmRegistry()
        r.observe(_v("p.x", Severity.WARNING), now_ms=1000)
        r.observe(_v("p.x", None), now_ms=2000)
        ch = r.observe(_v("p.x", Severity.CRITICAL), now_ms=3000)
        self.assertEqual(ch.event.state, AlarmState.UNACKED_ACTIVE)
        self.assertEqual(ch.event.first_seen_ms, 3000)
        self.assertFalse(ch.removed)


class TestPersistence(unittest.TestCase):
    def test_below_threshold_silent(self):
        r = AlarmRegistry()
        last = None
        for t in range(1000, 1020, 10):
            last = r.observe(_v("p.x", Severity.WARNING, persistence=3), now_ms=t)
        self.assertIsNone(last)

    def test_at_threshold_fires(self):
        r = AlarmRegistry()
        last = None
        for t in range(1000, 1030, 10):
            last = r.observe(_v("p.x", Severity.WARNING, persistence=3), now_ms=t)
        self.assertIsNotNone(last)

    def test_break_resets(self):
        r = AlarmRegistry()
        r.observe(_v("p.x", Severity.WARNING, persistence=3), now_ms=1000)
        r.observe(_v("p.x", Severity.WARNING, persistence=3), now_ms=1010)
        r.observe(_v("p.x", None, persistence=3), now_ms=1020)
        self.assertIsNone(r.observe(_v("p.x", Severity.WARNING, persistence=3), now_ms=1030))
        self.assertIsNone(r.observe(_v("p.x", Severity.WARNING, persistence=3), now_ms=1040))
        self.assertIsNotNone(r.observe(_v("p.x", Severity.WARNING, persistence=3), now_ms=1050))


class TestLatching(unittest.TestCase):
    def test_latched_no_auto_clear(self):
        r = AlarmRegistry()
        r.observe(_v("p.x", Severity.CRITICAL, latched=True), now_ms=1000)
        ch = r.observe(_v("p.x", None, latched=True), now_ms=2000)
        self.assertIsNone(ch)
        self.assertEqual(r.snapshot()[0].state, AlarmState.UNACKED_ACTIVE)

    def test_latched_clear_via_ack(self):
        r = AlarmRegistry()
        r.observe(_v("p.x", Severity.CRITICAL, latched=True), now_ms=1000)
        r.observe(_v("p.x", None, latched=True), now_ms=2000)
        ch = r.acknowledge("p.x", now_ms=2500)
        self.assertEqual(r.snapshot()[0].state, AlarmState.ACKED_ACTIVE)
        self.assertFalse(ch.removed)


class TestCarrierSuppression(unittest.TestCase):
    def test_no_carrier_means_fresh(self):
        r = AlarmRegistry()
        self.assertFalse(r.carrier_stale_for("eps.V_BUS"))

    def test_single_carrier_propagates(self):
        r = AlarmRegistry()
        r.set_parameter_carriers({"eps.V_BUS": ["eps_hk"]})
        r.observe(_container_v("eps_hk", Severity.WARNING), now_ms=1000)
        self.assertTrue(r.carrier_stale_for("eps.V_BUS"))

    def test_multi_source_all_required_stale(self):
        r = AlarmRegistry()
        r.set_parameter_carriers({"eps.V_BUS": ["eps_hk", "tlm_beacon"]})
        r.observe(_container_v("eps_hk", Severity.WARNING), now_ms=1000)
        self.assertFalse(r.carrier_stale_for("eps.V_BUS"))
        r.observe(_container_v("tlm_beacon", Severity.WARNING), now_ms=2000)
        self.assertTrue(r.carrier_stale_for("eps.V_BUS"))


class TestAcknowledgeAll(unittest.TestCase):
    def test_acks_every_alarm(self):
        r = AlarmRegistry()
        r.observe(_v("a", Severity.WARNING), now_ms=1000)
        r.observe(_v("b", Severity.CRITICAL), now_ms=1000)
        r.observe(_v("c", Severity.WATCH), now_ms=1000)
        chs = r.acknowledge_all(now_ms=2000)
        self.assertEqual(len(chs), 3)
        for c in chs:
            self.assertEqual(c.event.state, AlarmState.ACKED_ACTIVE)


if __name__ == "__main__":
    unittest.main()
