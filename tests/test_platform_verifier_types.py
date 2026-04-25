"""Types are the public shape of the verifier registry. Lock the field set,
frozen/immutable where declared, and the VerifierSet invariant (unique
verifier_ids across the set).
"""
import unittest
from dataclasses import FrozenInstanceError

from mav_gss_lib.platform.tx.verifiers import (
    CheckWindow, VerifierSpec, VerifierSet, VerifierOutcome, CommandInstance,
)


class CheckWindowShape(unittest.TestCase):
    def test_frozen(self):
        w = CheckWindow(start_ms=0, stop_ms=10000)
        with self.assertRaises(FrozenInstanceError):
            w.start_ms = 5  # type: ignore[misc]

    def test_fields(self):
        w = CheckWindow(start_ms=0, stop_ms=30000)
        self.assertEqual(w.start_ms, 0)
        self.assertEqual(w.stop_ms, 30000)


class VerifierSpecShape(unittest.TestCase):
    def test_fields(self):
        s = VerifierSpec(
            verifier_id="uppm_ack", stage="received",
            check_window=CheckWindow(0, 10000),
            display_label="UPPM", display_tone="info",
        )
        self.assertEqual(s.stage, "received")
        self.assertEqual(s.check_window.stop_ms, 10000)


class VerifierSetInvariant(unittest.TestCase):
    def test_unique_verifier_ids(self):
        s1 = VerifierSpec("uppm_ack", "received", CheckWindow(0, 10000), "UPPM", "info")
        s2 = VerifierSpec("uppm_ack", "received", CheckWindow(0, 10000), "UPPM", "info")
        with self.assertRaises(ValueError):
            VerifierSet(verifiers=(s1, s2))

    def test_empty_is_allowed(self):
        """FTDI destinations + fixture missions get empty VerifierSet."""
        s = VerifierSet(verifiers=())
        self.assertEqual(len(s.verifiers), 0)


class VerifierOutcomeShape(unittest.TestCase):
    def test_pending_default(self):
        o = VerifierOutcome.pending()
        self.assertEqual(o.state, "pending")
        self.assertIsNone(o.matched_at_ms)
        self.assertIsNone(o.match_event_id)

    def test_pass_carries_match(self):
        o = VerifierOutcome.passed(matched_at_ms=1234, match_event_id="e1")
        self.assertEqual(o.state, "passed")
        self.assertEqual(o.matched_at_ms, 1234)


class CommandInstanceShape(unittest.TestCase):
    def _spec(self):
        return VerifierSpec("uppm_ack", "received", CheckWindow(0, 10000), "UPPM", "info")

    def test_default_stage_released(self):
        inst = CommandInstance(
            instance_id="i1",
            correlation_key=("com_ping", "LPPM"),
            t0_ms=0,
            cmd_event_id="c1",
            verifier_set=VerifierSet(verifiers=(self._spec(),)),
            outcomes={"uppm_ack": VerifierOutcome.pending()},
            stage="released",
        )
        self.assertEqual(inst.stage, "released")
        self.assertEqual(inst.outcomes["uppm_ack"].state, "pending")


if __name__ == "__main__":
    unittest.main()
