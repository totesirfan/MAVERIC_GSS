"""TxService.admit gate rules (spec §6):
  1. Active-send: reject ALL queue additions.
  2. No active-send: reject re-queue of the same mission-provided
     correlation key while its CheckWindow is still open. Args are not part
     of the key in this fixture.
  3. Otherwise: accept.
"""
import unittest
from unittest.mock import MagicMock

from mav_gss_lib.server.tx.service import TxService, AdmitResult
from mav_gss_lib.platform.tx.verifiers import (
    CheckWindow, VerifierSpec, VerifierSet, VerifierOutcome, CommandInstance,
    VerifierRegistry,
)


def _runtime_with(registry, active=False):
    r = MagicMock()
    r.platform_cfg = {"tx": {"delay_ms": 100}, "general": {"log_dir": "/tmp"}}
    r.mission_cfg = {}
    r.tx_delay_ms = 100
    r.tx_blackout_ms = 0
    r.platform.verifiers = registry
    tx = TxService(r)
    tx.sending["active"] = active
    return tx


def _open_instance_for(cmd_id="mtq_set_1", dest="LPPM"):
    vs = VerifierSet(verifiers=(
        VerifierSpec("uppm_ack", "received", CheckWindow(0, 10000), "UPPM", "info"),
    ))
    return CommandInstance(
        instance_id="i1",
        correlation_key=(cmd_id, dest),
        t0_ms=0, cmd_event_id="c1",
        verifier_set=vs,
        outcomes={"uppm_ack": VerifierOutcome.pending()},
        stage="released",
    )


def _item(cmd_id="mtq_set_1", args="", dest="LPPM"):
    """Queue-item shape: payload is mission-owned; key is precomputed by CommandOps."""
    return {"type": "mission_cmd",
            "cmd_id": cmd_id,
            "correlation_key": [cmd_id, dest],
            "payload": {
                "cmd_id": cmd_id,
                "args": args if isinstance(args, dict) else {},
                "packet": {"dest": dest},
            }}


class AdmitResults(unittest.TestCase):
    def test_active_send_blocks_everything(self):
        reg = VerifierRegistry()
        tx = _runtime_with(reg, active=True)
        result, info = tx.admit(_item())
        self.assertEqual(result, AdmitResult.REJECTED_SEND_ACTIVE)

    def test_open_window_blocks_same_cmd_id_and_dest(self):
        reg = VerifierRegistry()
        reg.register(_open_instance_for())
        tx = _runtime_with(reg, active=False)
        result, info = tx.admit(_item())
        self.assertEqual(result, AdmitResult.REJECTED_WINDOW_OPEN)

    def test_same_cmd_id_different_dest_allowed(self):
        reg = VerifierRegistry()
        reg.register(_open_instance_for("com_ping", dest="LPPM"))
        tx = _runtime_with(reg, active=False)
        result, info = tx.admit(_item(cmd_id="com_ping", dest="UPPM"))
        self.assertEqual(result, AdmitResult.ACCEPTED)

    def test_different_args_still_blocked_same_cmd_id_dest(self):
        """Strict admission: args differ but (cmd_id, dest) match → block.
        Responses from spacecraft can't distinguish args anyway."""
        reg = VerifierRegistry()
        reg.register(_open_instance_for("mtq_set_1", dest="LPPM"))
        tx = _runtime_with(reg, active=False)
        result, info = tx.admit(_item(cmd_id="mtq_set_1", args="2", dest="LPPM"))
        self.assertEqual(result, AdmitResult.REJECTED_WINDOW_OPEN)

    def test_released_after_instance_reaches_terminal(self):
        """Admission reopens when the prior instance transitions to Complete."""
        reg = VerifierRegistry()
        inst = _open_instance_for()
        reg.register(inst)
        # Simulate a RES arriving — set stage to complete.
        inst.stage = "complete"
        tx = _runtime_with(reg, active=False)
        result, _ = tx.admit(_item())
        self.assertEqual(result, AdmitResult.ACCEPTED)

    def test_non_command_items_allowed_during_idle(self):
        reg = VerifierRegistry()
        tx = _runtime_with(reg, active=False)
        result, _ = tx.admit({"type": "note", "text": "stage-break"})
        self.assertEqual(result, AdmitResult.ACCEPTED)
        result, _ = tx.admit({"type": "checkpoint", "text": "confirm state"})
        self.assertEqual(result, AdmitResult.ACCEPTED)


if __name__ == "__main__":
    unittest.main()
