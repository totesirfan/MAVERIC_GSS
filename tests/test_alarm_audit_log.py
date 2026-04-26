"""SessionLog.write_alarm — JSONL audit envelope for alarm transitions."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from mav_gss_lib.logging.session import SessionLog
from mav_gss_lib.platform.alarms.contract import (
    AlarmChange, AlarmEvent, AlarmSource, AlarmState, Severity,
)


def _make_log(tmp_dir: str) -> SessionLog:
    return SessionLog(
        log_dir=tmp_dir,
        zmq_addr="tcp://127.0.0.1:52001",
        version="0.0.1",
        mission_name="MAVERIC",
        mission_id="maveric",
        station="bench",
        operator="op",
        host="testhost",
    )


class TestWriteAlarm(unittest.TestCase):
    def test_envelope_unified(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = _make_log(tmp)
            ev = AlarmEvent(
                id="param.gnc.ADCS_TMP",
                source=AlarmSource.PARAMETER, label="ADCS_TMP",
                detail="80°C", severity=Severity.CRITICAL,
                state=AlarmState.UNACKED_ACTIVE,
                first_seen_ms=1, last_eval_ms=1, last_transition_ms=1,
                context={"raw": 80},
            )
            ch = AlarmChange(event=ev, prev_state=None, prev_severity=None,
                             removed=False, operator="")
            log.write_alarm(ch, ts_ms=1)
            log.close()

            # Find the JSONL file (SessionLog names it)
            jsonl_path = next(
                p for p in os.listdir(os.path.join(tmp, "json"))
                if p.endswith(".jsonl")
            )
            with open(os.path.join(tmp, "json", jsonl_path)) as f:
                rec = json.loads(f.read().splitlines()[-1])
            self.assertEqual(rec["event_kind"], "alarm")
            self.assertEqual(rec["mission_id"], "maveric")
            self.assertEqual(rec["seq"], 0)
            self.assertIn("event_id", rec)
            self.assertIn("ts_ms", rec)
            self.assertIn("ts_iso", rec)
            self.assertEqual(rec["alarm"]["id"], "param.gnc.ADCS_TMP")
            self.assertEqual(rec["alarm"]["severity"], "critical")
            self.assertEqual(rec["alarm"]["state"], "unacked_active")
            self.assertFalse(rec["alarm"]["removed"])
            self.assertIsNone(rec["alarm"]["prev_state"])
            self.assertIsNone(rec["alarm"]["prev_severity"])
            self.assertEqual(rec["alarm"]["context"], {"raw": 80})

    def test_removed_flag_propagates(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = _make_log(tmp)
            ev = AlarmEvent(
                id="param.gnc.ADCS_TMP",
                source=AlarmSource.PARAMETER, label="ADCS_TMP",
                detail="", severity=Severity.WARNING,
                state=AlarmState.ACKED_ACTIVE,
                first_seen_ms=1, last_eval_ms=1, last_transition_ms=1,
            )
            ch = AlarmChange(event=ev, prev_state=AlarmState.UNACKED_CLEARED,
                             prev_severity=Severity.WARNING, removed=True)
            log.write_alarm(ch, ts_ms=1)
            log.close()

            jsonl_path = next(
                p for p in os.listdir(os.path.join(tmp, "json"))
                if p.endswith(".jsonl")
            )
            with open(os.path.join(tmp, "json", jsonl_path)) as f:
                rec = json.loads(f.read().splitlines()[-1])
            self.assertTrue(rec["alarm"]["removed"])
            self.assertEqual(rec["alarm"]["prev_state"], "unacked_cleared")
            self.assertEqual(rec["alarm"]["prev_severity"], "warning")

    def test_envelope_keys_complete(self):
        """Every required envelope key is present."""
        with tempfile.TemporaryDirectory() as tmp:
            log = _make_log(tmp)
            ev = AlarmEvent(
                id="platform.zmq_dead",
                source=AlarmSource.PLATFORM, label="ZMQ dead",
                detail="no frames 30s", severity=Severity.WATCH,
                state=AlarmState.UNACKED_ACTIVE,
                first_seen_ms=1000, last_eval_ms=1000, last_transition_ms=1000,
            )
            ch = AlarmChange(event=ev, prev_state=None, prev_severity=None)
            log.write_alarm(ch, ts_ms=1000)
            log.close()

            jsonl_path = next(
                p for p in os.listdir(os.path.join(tmp, "json"))
                if p.endswith(".jsonl")
            )
            with open(os.path.join(tmp, "json", jsonl_path)) as f:
                rec = json.loads(f.read().splitlines()[-1])

            required = {
                "event_id", "event_kind", "session_id", "ts_ms", "ts_iso",
                "seq", "v", "mission_id", "operator", "station",
            }
            for key in required:
                self.assertIn(key, rec, f"missing envelope key: {key}")
            self.assertEqual(rec["v"], "0.0.1")
            self.assertEqual(rec["operator"], "op")
            self.assertEqual(rec["station"], "bench")


if __name__ == "__main__":
    unittest.main()
