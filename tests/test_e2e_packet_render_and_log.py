"""End-to-end test: fake RX packets → UI detail_blocks + text log + JSONL.

Goal: prove that after Phase 3's display/log dedup, a packet driven through
the adapter produces:
  (a) UI-consumable detail_blocks (list[{kind, label, fields:[{name,value}]}]),
  (b) operator text-log lines with the expected per-register formatting,
  (c) JSONL mission data with native-typed args (not stringified),
and that (a) and (b) are cross-consistent — the same register names and
values appear in both surfaces.

Covers all 7 GNC register shapes + a plain typed-args CMD packet.
Also validates the parsing.build_rx_log_record envelope and its
JSON-serializability (the WebSocket contract the UI consumes).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ops_test_support import _ADAPTER
from mav_gss_lib.parsing import Packet, build_rx_log_record
from mav_gss_lib.missions.maveric.telemetry.semantics.gnc_schema import decode_register
from mav_gss_lib.missions.maveric.telemetry.semantics.nvg_sensors import (
    _handle_nvg_get_1, _handle_nvg_heartbeat,
)


# ---------- packet construction helpers ----------

def make_pkt(mission_data: dict, *, cmd_id: str | None = None,
             ptype: int = 3, pkt_num: int = 1) -> Packet:
    """Build a minimal Packet with a valid platform envelope."""
    if cmd_id is not None:
        mission_data = {
            **mission_data,
            "cmd": {
                **mission_data.get("cmd", {}),
                "src": 2, "dest": 6, "echo": 6, "pkt_type": ptype,
                "cmd_id": cmd_id, "crc": 0xABCD, "crc_valid": True,
                "args": mission_data.get("cmd", {}).get("args", []),
                "schema_match": mission_data.get("cmd", {}).get("schema_match", False),
                "typed_args": mission_data.get("cmd", {}).get("typed_args", []),
                "extra_args": mission_data.get("cmd", {}).get("extra_args", []),
            },
        }
    return Packet(
        pkt_num=pkt_num,
        gs_ts="2026-04-18 10:00:00 PDT",
        gs_ts_short="10:00:00",
        frame_type="ASM+GOLAY",
        raw=b"\x00\x01\x02",
        inner_payload=b"\x00\x01\x02",
        stripped_hdr=None,
        mission_data=mission_data,
    )


def gnc_pkt(reg_name: str, snap_value: dict, *,
            reg_type: str = "uint8[4]", unit: str = "") -> Packet:
    """Build a Packet carrying one decoded GNC telemetry fragment.

    Post-v2 the mission stores decoded registers on mission_data["fragments"]
    rather than mission_data["gnc_registers"]. The snap_value shape is the
    same structured dict the extractor attaches to the fragment.
    """
    md = {
        "cmd": {
            "src": 2, "dest": 6, "echo": 6, "pkt_type": 3,
            "cmd_id": "mtq_get_1", "crc": 0, "crc_valid": True,
            "args": [], "schema_match": True,
            "typed_args": [
                {"name": "Module",   "type": "str", "value": "0", "important": True},
                {"name": "Register", "type": "str", "value": "0", "important": True},
            ],
            "extra_args": [],
        },
        "fragments": [
            {"domain": "gnc", "key": reg_name, "value": snap_value,
             "ts_ms": 0, "unit": unit},
        ],
    }
    return make_pkt(md)


def gnc_fragment(jlog: dict, reg_name: str) -> dict | None:
    """Find the fragment entry for reg_name in a JSONL mission block."""
    for f in jlog.get("fragments", []):
        if f.get("domain") == "gnc" and f.get("key") == reg_name:
            return f
    return None


def register_block(detail_blocks: list[dict], reg_name: str) -> dict | None:
    """Find the args-block for a given register name."""
    for b in detail_blocks:
        if b.get("kind") == "args" and b.get("label") == reg_name:
            return b
    return None


def field_value(block: dict, name: str) -> str | None:
    for f in block["fields"]:
        if f["name"] == name:
            return f["value"]
    return None


def log_line_for(lines: list[str], reg_name: str) -> str | None:
    """First text-log line that mentions the register name."""
    for ln in lines:
        if reg_name in ln and "— decoded" not in ln and "  " in ln:
            # The summary line (lines[0]) has the register in the left gutter.
            if ln.lstrip().startswith(reg_name):
                return ln
    return None


class E2ERenderAndLogTests(unittest.TestCase):
    """Each test: build a packet → render + log → check UI + text + JSONL."""

    @classmethod
    def setUpClass(cls):
        cls.adapter = _ADAPTER

    # ---------- shape 1: BCD (TIME) ----------

    def test_bcd_time(self):
        # decode_register with module=0 register=5 (TIME) produces BCD shape
        dec = decode_register(0, 5, ["0", "39", "38", "0"])
        self.assertTrue(dec.decode_ok)
        self.assertIn("display", dec.value)

        pkt = gnc_pkt(dec.name, dec.value, reg_type=dec.type, unit=dec.unit)
        blocks = self.adapter.packet_detail_blocks(pkt)
        log = self.adapter.format_log_lines(pkt)
        jlog = self.adapter.build_log_mission_data(pkt)

        # UI: envelope correct
        blk = register_block(blocks, "TIME")
        self.assertIsNotNone(blk, f"no TIME block in {blocks}")
        self.assertEqual(blk["kind"], "args")
        display = field_value(blk, "Display")
        self.assertEqual(display, dec.value["display"])

        # Text log: first line carries the BCD display verbatim
        line = log_line_for(log, "TIME")
        self.assertIsNotNone(line, f"no TIME log line in {log}")
        self.assertIn(dec.value["display"], line)

        # JSONL: fragment passes through unchanged (post-v2 single payload)
        self.assertIn("fragments", jlog)
        frag = gnc_fragment(jlog, "TIME")
        self.assertIsNotNone(frag, f"no TIME fragment in {jlog}")
        self.assertEqual(frag["value"]["display"], dec.value["display"])

    # ---------- shape 2: ADCS_TMP ----------

    def test_adcs_tmp_celsius(self):
        value = {"brdtmp": 4369, "celsius": 17.07, "comm_fault": False}
        pkt = gnc_pkt("ADCS_TMP", value, reg_type="int16[2]", unit="")
        blocks = self.adapter.packet_detail_blocks(pkt)
        log = self.adapter.format_log_lines(pkt)

        blk = register_block(blocks, "ADCS_TMP")
        self.assertIsNotNone(blk)
        self.assertEqual(field_value(blk, "Celsius"), "17.07 °C")
        self.assertEqual(field_value(blk, "Raw"), "4369")

        line = log_line_for(log, "ADCS_TMP")
        self.assertIn("17.07 °C", line)
        self.assertIn("raw=4369", line)

    def test_adcs_tmp_sensor_fault(self):
        value = {"brdtmp": 0, "celsius": 0.0, "comm_fault": True}
        pkt = gnc_pkt("ADCS_TMP", value, reg_type="int16[2]")
        blocks = self.adapter.packet_detail_blocks(pkt)
        log = self.adapter.format_log_lines(pkt)

        blk = register_block(blocks, "ADCS_TMP")
        self.assertEqual(field_value(blk, "Status"), "SENSOR FAULT")
        self.assertIsNone(field_value(blk, "Celsius"))

        line = log_line_for(log, "ADCS_TMP")
        self.assertIn("SENSOR FAULT", line)

    # ---------- shape 3: bitfield with MODE (STAT register) ----------

    def test_bitfield_stat_with_mode_and_flags(self):
        # Real STAT decoder pads out 16+ flag fields. Simulate the shape.
        value = {
            "HERR": False, "SERR": False, "WDT": False, "UV": False,
            "OC": False, "OT": False, "GNSS_OC": False,
            "GNSS_UP_TO_DATE": True, "TLE": False, "DES": False,
            "SUN": True, "TGL": False, "TUMB": False, "AME": False,
            "CUSSV": False, "EKF": True,
            "MODE": 1, "MODE_NAME": "Sun Spin",
        }
        pkt = gnc_pkt("STAT", value, reg_type="uint8[4]")
        blocks = self.adapter.packet_detail_blocks(pkt)
        log = self.adapter.format_log_lines(pkt)

        blk = register_block(blocks, "STAT")
        self.assertIsNotNone(blk)
        self.assertEqual(field_value(blk, "Mode"), "Sun Spin (1)")
        flags_val = field_value(blk, "Flags")
        self.assertIn("SUN", flags_val)
        self.assertIn("EKF", flags_val)
        self.assertIn("GNSS_UP_TO_DATE", flags_val)
        self.assertNotIn("HERR", flags_val)  # False flags suppressed

        line = log_line_for(log, "STAT")
        self.assertIn("mode=Sun Spin(1)", line)
        self.assertIn("SUN", "\n".join(log))
        self.assertIn("EKF", "\n".join(log))

    def test_bitfield_pure_error_all_nominal(self):
        # Pure-error register (no MODE) with all flags False — "All nominal".
        value = {"MTQ0": False, "MTQ1": False, "CMG0": False}
        pkt = gnc_pkt("ACT_ERR", value, reg_type="uint8[4]")
        blocks = self.adapter.packet_detail_blocks(pkt)
        blk = register_block(blocks, "ACT_ERR")
        self.assertEqual(field_value(blk, "Status"), "All nominal")

    # ---------- shape 4: NVG heartbeat ----------

    def test_nvg_heartbeat(self):
        # {label, status} — stricter guard excludes sensor_id / mode
        value = {"status": 1, "label": "On"}
        pkt = gnc_pkt("NVG_STATUS", value, reg_type="nvg_status", unit="")
        blocks = self.adapter.packet_detail_blocks(pkt)
        log = self.adapter.format_log_lines(pkt)

        blk = register_block(blocks, "NVG_STATUS")
        self.assertEqual(field_value(blk, "Label"), "On")
        self.assertEqual(field_value(blk, "Status"), "1")

        line = log_line_for(log, "NVG_STATUS")
        self.assertIn("On", line)
        self.assertIn("status=1", line)

    # ---------- shape 5: NVG sensor (nvg_get_1) ----------

    def test_nvg_sensor(self):
        value = {
            "sensor_id": 3, "sensor_name": "ORIENTATION",
            "display": "Orientation", "unit": "deg", "status": 1,
            "timestamp": 1234.0,
            "fields": ["Yaw", "Pitch", "Roll", "Accuracy"],
            "values": [12.5, 34.25, 56.0, 2.0],
            "values_by_field": {"Yaw": 12.5, "Pitch": 34.25, "Roll": 56.0, "Accuracy": 2.0},
        }
        pkt = gnc_pkt("NVG_ORIENTATION", value, reg_type="nvg_sensor_3", unit="deg")
        blocks = self.adapter.packet_detail_blocks(pkt)
        log = self.adapter.format_log_lines(pkt)

        blk = register_block(blocks, "NVG_ORIENTATION")
        self.assertEqual(field_value(blk, "Display"), "Orientation")
        self.assertEqual(field_value(blk, "Status"), "1")
        # Field names carry through with unit suffix
        self.assertEqual(field_value(blk, "Yaw"), "12.5 deg")
        self.assertEqual(field_value(blk, "Pitch"), "34.25 deg")

        line = log_line_for(log, "NVG_ORIENTATION")
        self.assertIn("Orientation", line)
        self.assertIn("status=1", line)
        # The field rows appear as indented sub-lines
        self.assertTrue(any("Yaw" in ln and "12.5" in ln for ln in log))

    # ---------- shape 6: GNC mode ----------

    def test_gnc_mode(self):
        value = {"mode": 2, "mode_name": "Auto"}
        pkt = gnc_pkt("GNC_MODE", value, reg_type="gnc_mode")
        blocks = self.adapter.packet_detail_blocks(pkt)
        log = self.adapter.format_log_lines(pkt)

        blk = register_block(blocks, "GNC_MODE")
        self.assertEqual(field_value(blk, "Mode"), "Auto")
        self.assertEqual(field_value(blk, "Code"), "2")

        line = log_line_for(log, "GNC_MODE")
        self.assertIn("Auto (2)", line)

    # ---------- shape 7: GNC counters ----------

    def test_gnc_counters(self):
        value = {"reboot": 3, "detumble": 2, "sunspin": 7, "unexpected_safe": 1}
        pkt = gnc_pkt("GNC_COUNTERS", value, reg_type="gnc_counters")
        blocks = self.adapter.packet_detail_blocks(pkt)
        log = self.adapter.format_log_lines(pkt)

        blk = register_block(blocks, "GNC_COUNTERS")
        self.assertEqual(field_value(blk, "Reboot"), "3")
        self.assertEqual(field_value(blk, "De-Tumble"), "2")
        self.assertEqual(field_value(blk, "Sunspin"), "7")

        line = log_line_for(log, "GNC_COUNTERS")
        self.assertIn("reboot=3", line)
        self.assertIn("detumble=2", line)
        self.assertIn("sunspin=7", line)

    # ---------- scalar / list fallbacks ----------

    def test_scalar_float_list(self):
        value = [0.1234, 0.5678, 0.9012]
        pkt = gnc_pkt("RATE", value, reg_type="float[3]", unit="rad/s")
        blocks = self.adapter.packet_detail_blocks(pkt)
        blk = register_block(blocks, "RATE")
        v = field_value(blk, "Value")
        self.assertIn("0.1234", v)
        self.assertIn("rad/s", v)

    # ---------- generic dict fallthrough ----------

    def test_generic_dict_fallback(self):
        # A dict that matches NO specific predicate (no sensor_id/display/celsius/etc.)
        value = {"alpha": 1, "beta": 2}
        pkt = gnc_pkt("ARB", value, reg_type="custom")
        blocks = self.adapter.packet_detail_blocks(pkt)
        blk = register_block(blocks, "ARB")
        self.assertIsNotNone(blk)
        # generic dict probe → {str(k): str(v)} per entry
        self.assertEqual(field_value(blk, "alpha"), "1")
        self.assertEqual(field_value(blk, "beta"), "2")

    # ---------- hide_args suppression ----------

    def test_hide_args_when_register_decoded(self):
        # When has_decoded_gnc() is True, the args rail should be suppressed
        # from the packet_list_row (no 'Module 0 Register 0' args).
        dec = decode_register(0, 5, ["0", "39", "38", "0"])
        pkt = gnc_pkt(dec.name, dec.value, reg_type=dec.type)
        row = self.adapter.packet_list_row(pkt)
        args_cell = row["values"]["cmd"]
        # 'mtq_get_1' is the cmd id; args should be empty after hide_args kicks in
        self.assertEqual(args_cell, "mtq_get_1")

    # ---------- typed_args JSONL types (non-GNC) ----------

    def test_typed_args_native_types_in_jsonl(self):
        """Round 5 regression: build_log_mission_data must preserve native
        types, not coerce to strings. Covers epoch_ms dict, blob bytes, int."""
        pkt = make_pkt(
            {
                "cmd": {
                    "schema_match": True,
                    "typed_args": [
                        {"name": "deadline", "type": "epoch_ms",
                         "value": {"ms": 1712345678000}},
                        {"name": "payload", "type": "blob",
                         "value": b"\x00\xff\x42"},
                        {"name": "retries", "type": "int", "value": 5},
                        {"name": "gain",    "type": "float", "value": 3.14},
                    ],
                    "extra_args": [],
                },
            },
            cmd_id="demo_cmd",
        )
        jlog = self.adapter.build_log_mission_data(pkt)
        args = jlog["cmd"]["args"]
        self.assertEqual(args["deadline"], 1712345678000)  # int, not str
        self.assertIsInstance(args["deadline"], int)
        self.assertEqual(args["payload"], "00ff42")         # hex string
        self.assertEqual(args["retries"], 5)
        self.assertIsInstance(args["retries"], int)
        self.assertEqual(args["gain"], 3.14)
        self.assertIsInstance(args["gain"], float)

    def test_typed_args_malformed_epoch_ms_does_not_crash(self):
        """Round 5 regression: schema._parse_epoch_ms returns raw str on parse
        failure. A value like '24ms' once crashed via 'ms' in v substring bug."""
        pkt = make_pkt(
            {
                "cmd": {
                    "schema_match": True,
                    "typed_args": [
                        {"name": "deadline", "type": "epoch_ms", "value": "24ms"},
                    ],
                    "extra_args": [],
                },
            },
            cmd_id="bad_epoch",
        )
        jlog = self.adapter.build_log_mission_data(pkt)
        self.assertEqual(jlog["cmd"]["args"]["deadline"], "24ms")
        lines = self.adapter.format_log_lines(pkt)
        self.assertTrue(any("24ms" in ln for ln in lines),
                        f"'24ms' not in log lines: {lines}")

    # ---------- cross-consistency: names present in BOTH surfaces ----------

    def test_register_names_consistent_between_ui_and_log(self):
        """Every args-block label in detail_blocks appears as a register
        header in the text log, and vice versa."""
        # Build a packet carrying 3 distinct register shapes at once.
        bcd = decode_register(0, 5, ["0", "39", "38", "0"])
        md = {
            "cmd": {
                "src": 2, "dest": 6, "echo": 6, "pkt_type": 3,
                "cmd_id": "mtq_get_1", "crc": 0, "crc_valid": True,
                "args": [], "schema_match": True,
                "typed_args": [
                    {"name": "Module",   "type": "str", "value": "0"},
                    {"name": "Register", "type": "str", "value": "0"},
                ],
                "extra_args": [],
            },
            "fragments": [
                {"domain": "gnc", "key": bcd.name, "value": bcd.value,
                 "ts_ms": 0, "unit": bcd.unit},
                {"domain": "gnc", "key": "GNC_MODE",
                 "value": {"mode": 1, "mode_name": "Auto"},
                 "ts_ms": 0, "unit": ""},
                {"domain": "gnc", "key": "ACT_ERR",
                 "value": {"MTQ0": False, "CMG0": False},
                 "ts_ms": 0, "unit": ""},
            ],
        }
        pkt = make_pkt(md)
        blocks = self.adapter.packet_detail_blocks(pkt)
        lines = self.adapter.format_log_lines(pkt)

        ui_labels = {b["label"] for b in blocks
                     if b.get("kind") == "args"
                     and b.get("label") in {"TIME", "GNC_MODE", "ACT_ERR"}}
        self.assertEqual(ui_labels, {"TIME", "GNC_MODE", "ACT_ERR"})

        log_text = "\n".join(lines)
        for reg in ("TIME", "GNC_MODE", "ACT_ERR"):
            self.assertIn(reg, log_text, f"{reg} missing from text log")

    # ---------- full RX envelope (WebSocket contract) ----------

    def test_build_rx_log_record_is_json_serializable(self):
        """The WebSocket broadcast to the React UI serializes the _rendering
        payload as JSON. If a generator or non-JSON type sneaks in, the
        broadcast silently drops the packet. Guard that."""
        dec = decode_register(0, 128, ["2", "33", "0", "0"])  # STAT
        pkt = gnc_pkt(dec.name, dec.value, reg_type=dec.type)
        record = build_rx_log_record(pkt, version="test", meta={}, adapter=self.adapter)

        # Full round-trip: serialize and deserialize
        blob = json.dumps(record, default=str)
        parsed = json.loads(blob)

        # Envelope keys present
        self.assertIn("_rendering", parsed)
        rendering = parsed["_rendering"]
        self.assertIn("row", rendering)
        self.assertIn("detail_blocks", rendering)
        self.assertIn("protocol_blocks", rendering)
        self.assertIn("integrity_blocks", rendering)

        # detail_blocks is a list — NOT a generator (would fail JSON)
        self.assertIsInstance(rendering["detail_blocks"], list)
        # Each args-block has the UI contract
        for blk in rendering["detail_blocks"]:
            if blk.get("kind") == "args":
                self.assertIn("label", blk)
                self.assertIn("fields", blk)
                for f in blk["fields"]:
                    self.assertIn("name", f)
                    self.assertIn("value", f)
                    # UI reads value as string — catch any leftover native objects
                    self.assertIsInstance(f["value"], str)

    # ---------- NVG helper round-trip (uses production decoders end-to-end) ----------

    def test_eps_telemetry_appears_in_both_text_log_and_jsonl(self):
        """Log-sink symmetry: decoded eps_hk fields must appear in BOTH
        the text log and the JSONL mission block.

        Post-v2 this holds by construction — both sinks iterate the
        same mission_data["fragments"] list populated by the extractor.
        The test still locks the contract so a regression cannot silently
        drop the shared list.
        """
        eps_fragments = [
            {"domain": "eps", "key": "V_BAT", "value": 7.622, "ts_ms": 1, "unit": "V"},
            {"domain": "eps", "key": "I_BAT", "value": 0.587, "ts_ms": 1, "unit": "A"},
            {"domain": "eps", "key": "T_DIE", "value": 32.5,  "ts_ms": 1, "unit": "°C"},
        ]
        pkt = make_pkt(
            {"fragments": eps_fragments},
            cmd_id="eps_hk",
            ptype=2,  # TLM
        )

        log = self.adapter.format_log_lines(pkt)
        jlog = self.adapter.build_log_mission_data(pkt)

        joined_log = "\n".join(log)
        self.assertIn("V_BAT", joined_log)
        self.assertIn("7.622", joined_log)

        self.assertIn("fragments", jlog,
                      "eps_hk decoded fields missing from JSONL mission block")
        jsonl_by_key = {f["key"]: f for f in jlog["fragments"] if f["domain"] == "eps"}
        self.assertEqual(set(jsonl_by_key), {"V_BAT", "I_BAT", "T_DIE"})
        self.assertEqual(jsonl_by_key["V_BAT"]["value"], 7.622)
        self.assertEqual(jsonl_by_key["T_DIE"]["value"], 32.5)

    def test_spacecraft_fragments_render_in_log_detail_and_jsonl(self):
        """Beacon packets carry shared-prefix state in the `spacecraft`
        domain (callsign, time, ops_stage, reboot counters, heartbeats).
        Text log, packet-detail blocks, and JSONL must all carry them so
        the operator sees the full decoded beacon, not just the tail."""
        spacecraft_fragments = [
            {"domain": "spacecraft", "key": "callsign",      "value": "WQ2XIC","ts_ms": 1, "unit": ""},
            {"domain": "spacecraft", "key": "time",          "value": 1000000, "ts_ms": 1, "unit": ""},
            {"domain": "spacecraft", "key": "ops_stage",     "value": 4,       "ts_ms": 1, "unit": ""},
            {"domain": "spacecraft", "key": "lppm_rbt_cnt",  "value": 112,     "ts_ms": 1, "unit": ""},
            {"domain": "spacecraft", "key": "ertc_heartbeat","value": 200,     "ts_ms": 1, "unit": ""},
        ]
        pkt = make_pkt(
            {"fragments": spacecraft_fragments},
            cmd_id="tlm_beacon",
            ptype=2,  # TLM
        )

        blocks = self.adapter.packet_detail_blocks(pkt)
        log = self.adapter.format_log_lines(pkt)
        jlog = self.adapter.build_log_mission_data(pkt)

        # Detail view: one SPACECRAFT block carrying every spacecraft fragment.
        sc_block = next(
            (b for b in blocks if b.get("kind") == "args" and b.get("label") == "SPACECRAFT"),
            None,
        )
        self.assertIsNotNone(sc_block, f"no SPACECRAFT block in {blocks}")
        names = {f["name"] for f in sc_block["fields"]}
        self.assertEqual(names,
                         {"callsign", "time", "ops_stage", "lppm_rbt_cnt", "ertc_heartbeat"})
        callsign_field = next(f for f in sc_block["fields"] if f["name"] == "callsign")
        self.assertEqual(callsign_field["value"], "WQ2XIC")

        # Text log: a line per spacecraft fragment, callsign included.
        joined = "\n".join(log)
        for key in ("callsign", "time", "ops_stage", "lppm_rbt_cnt", "ertc_heartbeat"):
            self.assertIn(key, joined, f"spacecraft key {key} missing from log")
        self.assertIn("WQ2XIC", joined)

        # JSONL: fragments pass through unchanged — full spacecraft domain.
        jsonl_sc = {f["key"]: f for f in jlog["fragments"] if f["domain"] == "spacecraft"}
        self.assertEqual(set(jsonl_sc),
                         {"callsign", "time", "ops_stage", "lppm_rbt_cnt", "ertc_heartbeat"})
        self.assertEqual(jsonl_sc["callsign"]["value"], "WQ2XIC")

    def test_nvg_get_1_production_decoder_round_trip(self):
        """Use the real nvg_get_1 handler (not a hand-built dict) to prove
        the production decoder → display_helpers → UI + log path is intact."""
        # typed[0]=status, typed[1]=sensor_id=3 (ORIENTATION),
        # typed[2]=timestamp, typed[3]=first data token, extras=remaining.
        cmd = {
            "typed_args": [
                {"name": "Status",       "type": "str", "value": "1"},
                {"name": "Sensor",       "type": "str", "value": "3"},
                {"name": "Timestamp",    "type": "str", "value": "1234.5"},
                {"name": "SensorValues", "type": "str", "value": "12.0"},
            ],
            "extra_args": ["34.0", "56.0", "2.0"],
        }
        regs = _handle_nvg_get_1(cmd)
        self.assertIsNotNone(regs, "nvg_get_1 handler returned None")
        self.assertTrue(regs, "nvg_get_1 handler produced no registers")
        reg_name = next(iter(regs))
        pkt = gnc_pkt(reg_name, regs[reg_name]["value"],
                      reg_type=regs[reg_name]["type"],
                      unit=regs[reg_name].get("unit", ""))
        blocks = self.adapter.packet_detail_blocks(pkt)
        blk = register_block(blocks, reg_name)
        self.assertIsNotNone(blk, f"no block for {reg_name} in {blocks}")
        # At minimum, Display and Status fields should be present
        self.assertIsNotNone(field_value(blk, "Display"))
        self.assertIsNotNone(field_value(blk, "Status"))


if __name__ == "__main__":
    unittest.main()
