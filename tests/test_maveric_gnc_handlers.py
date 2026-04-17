"""Tests for the GNC command-handler dispatch table + handlers that
aren't already covered by test_maveric_gnc_registers.py.

Exercises:
  _walk_fast_frame  (the tricky token-stream walker)
  _handle_mtq_get_fast
  _handle_nvg_get_1
  _handle_nvg_heartbeat
  _handle_gnc_get_mode
  _handle_gnc_get_cnts

Fixtures are the exact wire samples from the real downlink logs under
`logs/text/`, so a regression here indicates the decoder has drifted
from what the flight software sends.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.missions.maveric.telemetry.gnc_registers import (
    COMMAND_HANDLERS,
    _handle_gnc_get_cnts,
    _handle_gnc_get_mode,
    _handle_mtq_get_fast,
    _walk_fast_frame,
)
from mav_gss_lib.missions.maveric.telemetry.nvg_sensors import (
    _handle_nvg_get_1,
    _handle_nvg_heartbeat,
)


def _cmd(cmd_id: str, *arg_values: str) -> dict:
    """Build a synthetic `cmd` dict in the shape rx_ops produces after
    schema parsing. First N args go into typed_args; the rest into
    extra_args. Each typed_arg is {name, type, value}."""
    typed = [{"name": f"a{i}", "type": "str", "value": v} for i, v in enumerate(arg_values)]
    return {"cmd_id": cmd_id, "typed_args": typed, "extra_args": []}


def _cmd_variadic(cmd_id: str, typed_slots: int, *tokens: str) -> dict:
    """Build a cmd dict where the first `typed_slots` tokens fill
    typed_args and the rest overflow into extra_args. Mirrors how the
    schema layer handles a variadic command with N declared rx_args."""
    typed = [
        {"name": f"a{i}", "type": "str", "value": v}
        for i, v in enumerate(tokens[:typed_slots])
    ]
    extras = list(tokens[typed_slots:])
    return {"cmd_id": cmd_id, "typed_args": typed, "extra_args": extras}


# ── _walk_fast_frame ────────────────────────────────────────────────


class TestWalkFastFrame(unittest.TestCase):
    """The token walker is the only non-trivial parser in the whole
    plugin. Every edge case here is one GNC team could trip over."""

    def test_empty_stream(self):
        self.assertEqual(list(_walk_fast_frame([])), [])

    def test_single_register(self):
        # "0,5 0 39 38 0"  — TIME from mtq_get_1 wire
        out = list(_walk_fast_frame(["0,5", "0", "39", "38", "0"]))
        self.assertEqual(out, [(0, 5, ["0", "39", "38", "0"])])

    def test_multiple_registers(self):
        # Page 0 from mtq_get_fast (CONF, TIME, DATE condensed)
        tokens = ["0,4", "0", "0", "0", "0",
                  "0,5", "0", "54", "23", "0",
                  "0,6", "0", "1", "1", "32"]
        out = list(_walk_fast_frame(tokens))
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0], (0, 4, ["0", "0", "0", "0"]))
        self.assertEqual(out[1], (0, 5, ["0", "54", "23", "0"]))
        self.assertEqual(out[2], (0, 6, ["0", "1", "1", "32"]))

    def test_marker_with_empty_payload(self):
        # Marker followed immediately by another marker (no values)
        out = list(_walk_fast_frame(["0,5", "0,6", "1", "1", "1", "0"]))
        self.assertEqual(out, [
            (0, 5, []),
            (0, 6, ["1", "1", "1", "0"]),
        ])

    def test_trailing_marker_no_values(self):
        # Frame truncated at the last marker — register is yielded with
        # empty values; decode_register will return decode_ok=False.
        out = list(_walk_fast_frame(["0,5", "0", "39", "0,6"]))
        self.assertEqual(out, [
            (0, 5, ["0", "39"]),
            (0, 6, []),
        ])

    def test_leading_garbage_before_first_marker(self):
        # Stream starts with non-marker tokens — walker skips them.
        out = list(_walk_fast_frame(["x", "y", "0,5", "0", "39"]))
        self.assertEqual(out, [(0, 5, ["0", "39"])])

    def test_malformed_marker_is_skipped(self):
        # A `0,xyz` pseudo-marker parses as ValueError and is dropped.
        # Subsequent real markers still process.
        out = list(_walk_fast_frame(["0,xyz", "99", "0,5", "0", "39"]))
        self.assertEqual(out, [(0, 5, ["0", "39"])])

    def test_cross_module_markers(self):
        # mtq_get_fast page 2 ends with a (1, 78) marker — verify the
        # walker tracks module changes correctly.
        tokens = ["0,159", "-31320.3", "0.24", "0.0",
                  "1,78", "0.0", "0.0", "0.0002"]
        out = list(_walk_fast_frame(tokens))
        self.assertEqual(out[0][0], 0)  # module 0
        self.assertEqual(out[0][1], 159)
        self.assertEqual(out[1][0], 1)  # module 1
        self.assertEqual(out[1][1], 78)


# ── _handle_mtq_get_fast ────────────────────────────────────────────


class TestHandleMtqGetFast(unittest.TestCase):
    """Integration of walker + decode_register via the fast-frame handler."""

    def _cmd(self, *tokens: str) -> dict:
        # schema has 3 rx_args: Status, Page, Reg Data
        return _cmd_variadic("mtq_get_fast", 3, *tokens)

    def test_real_log_page_0(self):
        # Exact wire from downlink_20260417_153507_post.txt
        cmd = self._cmd("1", "0",
                        "0,4", "0", "0", "0", "0",
                        "0,5", "0", "54", "23", "0",
                        "0,6", "0", "1", "1", "32",
                        "0,103", "0.000000", "0.000000", "0.000000",
                        "0,128", "0", "0", "0", "0")
        out = _handle_mtq_get_fast(cmd)
        self.assertIsNotNone(out)
        self.assertEqual(set(out.keys()), {"CONF", "TIME", "DATE", "MTQ_USER", "STAT"})
        # Wire tokens [0, 54, 23, 0] are byte[0..3] in LE order.
        # byte[3]=00 HH=00, byte[2]=0x17 MM=17, byte[1]=0x36 SS=36.
        self.assertEqual(out["TIME"]["value"]["display"], "00:17:36")
        self.assertEqual(out["STAT"]["value"]["MODE_NAME"], "Safe")

    def test_real_log_page_2_with_module_1(self):
        cmd = self._cmd("1", "2",
                        "0,142", "0.0", "0.0", "0.0",
                        "0,145", "0.0", "0.0", "0.0",
                        "0,156", "0.0", "0.0", "0.0",
                        "0,159", "-31320.302963", "0.240334", "0.0",
                        "1,78", "0.0", "0.0", "0.00018")
        out = _handle_mtq_get_fast(cmd)
        self.assertEqual(set(out.keys()),
                         {"ATT_ERROR", "ATT_ERROR_RATE", "SV", "MAG", "MTQ"})
        self.assertAlmostEqual(out["MAG"]["value"][0], -31320.302963, places=3)
        self.assertAlmostEqual(out["MTQ"]["value"][2], 0.00018, places=6)

    def test_single_register_page_3(self):
        # Page 3 only has MTQ_USER
        cmd = self._cmd("1", "3", "0,103", "0.0", "0.0", "0.0")
        out = _handle_mtq_get_fast(cmd)
        self.assertEqual(list(out.keys()), ["MTQ_USER"])
        self.assertEqual(out["MTQ_USER"]["value"], [0.0, 0.0, 0.0])

    def test_too_few_typed_args(self):
        cmd = {"cmd_id": "mtq_get_fast", "typed_args": [], "extra_args": []}
        self.assertIsNone(_handle_mtq_get_fast(cmd))

    def test_empty_payload_returns_none(self):
        # Status + Page only, no Reg Data → insufficient typed_args
        cmd = {"cmd_id": "mtq_get_fast",
               "typed_args": [{"name": "a0", "type": "str", "value": "1"},
                              {"name": "a1", "type": "str", "value": "0"}],
               "extra_args": []}
        self.assertIsNone(_handle_mtq_get_fast(cmd))


# ── _handle_nvg_heartbeat ───────────────────────────────────────────


class TestHandleNvgHeartbeat(unittest.TestCase):

    def test_status_on(self):
        out = _handle_nvg_heartbeat(_cmd("nvg_heartbeat", "1"))
        self.assertIn("NVG_STATUS", out)
        self.assertEqual(out["NVG_STATUS"]["value"]["status"], 1)
        self.assertEqual(out["NVG_STATUS"]["value"]["label"], "On")

    def test_status_off(self):
        out = _handle_nvg_heartbeat(_cmd("nvg_heartbeat", "0"))
        self.assertEqual(out["NVG_STATUS"]["value"]["label"], "Off")

    def test_missing_typed_args_returns_none(self):
        cmd = {"cmd_id": "nvg_heartbeat", "typed_args": [], "extra_args": []}
        self.assertIsNone(_handle_nvg_heartbeat(cmd))

    def test_non_integer_status_returns_none(self):
        self.assertIsNone(_handle_nvg_heartbeat(_cmd("nvg_heartbeat", "oops")))


# ── _handle_nvg_get_1 ───────────────────────────────────────────────


class TestHandleNvgGet1(unittest.TestCase):
    """Schema has 4 rx_args: Status, Sensor, Timestamp, Sensor Values."""

    def _cmd(self, *tokens: str) -> dict:
        return _cmd_variadic("nvg_get_1", 4, *tokens)

    def test_real_log_sample_magnetometer(self):
        # `nvg_get_1 1 2 0.000000 0.000000` from downlink log
        out = _handle_nvg_get_1(self._cmd("1", "2", "0.000000", "0.000000"))
        self.assertIn("NVG_MAGNETOMETER", out)
        snap = out["NVG_MAGNETOMETER"]["value"]
        self.assertEqual(snap["sensor_id"], 2)
        self.assertEqual(snap["sensor_name"], "MAGNETOMETER")
        self.assertEqual(snap["unit"], "uT")
        self.assertEqual(snap["status"], 1)
        self.assertEqual(snap["timestamp"], 0.000000)
        self.assertEqual(snap["values"], [0.0])  # truncated payload
        self.assertIsNone(snap["values_by_field"])  # expected 4, got 1

    def test_full_payload_maps_to_fields(self):
        # 4-value payload matches sensor 3 (Orientation) field count
        out = _handle_nvg_get_1(self._cmd("1", "3", "0.0", "12.0", "34.0", "56.0", "2.0"))
        snap = out["NVG_ORIENTATION"]["value"]
        self.assertEqual(snap["values"], [12.0, 34.0, 56.0, 2.0])
        self.assertEqual(snap["values_by_field"],
                         {"Yaw": 12.0, "Pitch": 34.0, "Roll": 56.0, "Accuracy": 2.0})

    def test_unknown_sensor_id(self):
        out = _handle_nvg_get_1(self._cmd("1", "999", "0.0", "1.0"))
        self.assertIn("NVG_UNKNOWN_999", out)
        self.assertEqual(out["NVG_UNKNOWN_999"]["value"]["display"],
                         "Unknown sensor 999")

    def test_status_only_response(self):
        # `nvg_get_1 0` — no sensor follows. Matches real log pkt #184.
        cmd = {"cmd_id": "nvg_get_1",
               "typed_args": [{"name": "a0", "type": "str", "value": "0"}],
               "extra_args": []}
        self.assertIsNone(_handle_nvg_get_1(cmd))

    def test_missing_args_returns_none(self):
        cmd = {"cmd_id": "nvg_get_1", "typed_args": [], "extra_args": []}
        self.assertIsNone(_handle_nvg_get_1(cmd))


# ── _handle_gnc_get_mode ────────────────────────────────────────────


class TestHandleGncGetMode(unittest.TestCase):

    def test_safe_mode(self):
        out = _handle_gnc_get_mode(_cmd("gnc_get_mode", "0"))
        self.assertEqual(out["GNC_MODE"]["value"]["mode_name"], "Safe")

    def test_auto_mode(self):
        out = _handle_gnc_get_mode(_cmd("gnc_get_mode", "1"))
        self.assertEqual(out["GNC_MODE"]["value"]["mode_name"], "Auto")

    def test_manual_mode(self):
        out = _handle_gnc_get_mode(_cmd("gnc_get_mode", "2"))
        self.assertEqual(out["GNC_MODE"]["value"]["mode_name"], "Manual")

    def test_unknown_mode_is_labeled(self):
        out = _handle_gnc_get_mode(_cmd("gnc_get_mode", "99"))
        self.assertEqual(out["GNC_MODE"]["value"]["mode"], 99)
        self.assertEqual(out["GNC_MODE"]["value"]["mode_name"], "UNKNOWN_99")

    def test_non_integer_returns_none(self):
        self.assertIsNone(_handle_gnc_get_mode(_cmd("gnc_get_mode", "oops")))

    def test_no_args_returns_none(self):
        cmd = {"cmd_id": "gnc_get_mode", "typed_args": [], "extra_args": []}
        self.assertIsNone(_handle_gnc_get_mode(cmd))


# ── _handle_gnc_get_cnts ────────────────────────────────────────────


class TestHandleGncGetCnts(unittest.TestCase):

    def test_all_zero(self):
        out = _handle_gnc_get_cnts(_cmd("gnc_get_cnts", "0", "0", "0"))
        v = out["GNC_COUNTERS"]["value"]
        self.assertEqual(v["reboot"], 0)
        self.assertEqual(v["detumble"], 0)
        self.assertEqual(v["sunspin"], 0)
        self.assertEqual(v["unexpected_safe"], 0)

    def test_nonzero(self):
        out = _handle_gnc_get_cnts(_cmd("gnc_get_cnts", "3", "2", "7"))
        v = out["GNC_COUNTERS"]["value"]
        self.assertEqual(v["reboot"], 3)
        self.assertEqual(v["detumble"], 2)
        self.assertEqual(v["sunspin"], 7)

    def test_fewer_than_three_args_returns_none(self):
        self.assertIsNone(_handle_gnc_get_cnts(_cmd("gnc_get_cnts", "0", "0")))

    def test_non_integer_arg_returns_none(self):
        self.assertIsNone(_handle_gnc_get_cnts(_cmd("gnc_get_cnts", "0", "x", "0")))


# ── COMMAND_HANDLERS table integrity ────────────────────────────────


class TestCommandHandlersTable(unittest.TestCase):
    """Guard against silent dispatch drift — if a handler is renamed
    or removed, the test table below must be updated deliberately."""

    def test_all_six_handlers_registered(self):
        self.assertEqual(
            set(COMMAND_HANDLERS.keys()),
            {"mtq_get_1", "mtq_get_fast",
             "nvg_get_1", "nvg_heartbeat",
             "gnc_get_mode", "gnc_get_cnts"},
        )

    def test_every_handler_is_callable(self):
        for cmd_id, fn in COMMAND_HANDLERS.items():
            self.assertTrue(callable(fn), f"{cmd_id} handler is not callable")


if __name__ == "__main__":
    unittest.main()
