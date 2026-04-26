"""Mission-owned framing covers the platform TX boundary.

Verifies:
- Platform TX path delegates to mission.commands.frame() — the server backend
  does not import the platform's framing primitives directly.
- MAVERIC framer reads ax25/csp from the live mission_config reference so
  /api/config updates take effect without a MissionSpec rebuild.
- Echo-style missions with passthrough framing work through the same
  contract (FramedCommand.wire == EncodedCommand.raw).
- TX log JSONL records carry mission-provided log_fields + frame_label.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestBackendHasNoFramingImports(unittest.TestCase):
    """Guardrail — the server must not import platform framing primitives.

    TX framing flows through `MissionSpec.commands.frame()`. The server
    publishes `FramedCommand.wire` on ZMQ as-is and never wraps, strips,
    or inspects framing layers itself.
    """

    BANNED_PATTERN = re.compile(
        r"from\s+mav_gss_lib\.platform\.framing(?:\.\w+)?\s+import|"
        r"import\s+mav_gss_lib\.platform\.framing(?:\.\w+)?"
    )

    def test_server_does_not_import_protocol_framing(self):
        root = pathlib.Path(__file__).resolve().parent.parent / "mav_gss_lib"
        server_dir = root / "server"
        assert server_dir.is_dir(), f"expected {server_dir} to exist"
        offenders: list[str] = []
        scanned = 0
        for py in server_dir.rglob("*.py"):
            scanned += 1
            text = py.read_text()
            for lineno, line in enumerate(text.splitlines(), start=1):
                if self.BANNED_PATTERN.search(line):
                    offenders.append(f"{py.relative_to(root.parent)}:{lineno}: {line.strip()}")
        assert scanned > 0, f"scanned 0 files under {server_dir} — guardrail would false-green"
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_server_does_not_reference_runtime_csp_or_ax25(self):
        root = pathlib.Path(__file__).resolve().parent.parent / "mav_gss_lib"
        server_dir = root / "server"
        assert server_dir.is_dir(), f"expected {server_dir} to exist"
        pattern = re.compile(r"runtime\.(csp|ax25)\b|\.csp\s*=|\.ax25\s*=")
        offenders: list[str] = []
        scanned = 0
        for py in server_dir.rglob("*.py"):
            scanned += 1
            text = py.read_text()
            for lineno, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    offenders.append(f"{py.relative_to(root.parent)}:{lineno}: {line.strip()}")
        assert scanned > 0, f"scanned 0 files under {server_dir} — guardrail would false-green"
        self.assertEqual(offenders, [], "\n".join(offenders))


class TestMavericFramerReadsLiveConfig(unittest.TestCase):
    def test_ax25_call_change_takes_effect_on_next_frame(self):
        from mav_gss_lib.server.state import create_runtime
        rt = create_runtime()
        payload = {"cmd_id": "com_ping", "args": "", "dest": "LPPM", "echo": "NONE", "ptype": "CMD"}
        prep = rt.platform.prepare_tx(payload)

        # Force AX.25 mode so src_call appears in the framed wire header.
        rt.platform_cfg["tx"]["uplink_mode"] = "AX.25"
        rt.mission_cfg.setdefault("ax25", {}).update({
            "src_call": "WAAAAA",
            "src_ssid": 0,
            "dest_call": "NOCALL",
            "dest_ssid": 0,
        })

        framed_before = rt.platform.frame_tx(prep.encoded)
        self.assertEqual(framed_before.frame_label, "AX.25")
        self.assertEqual(framed_before.log_fields["ax25"]["src_call"], "WAAAAA")

        # Mutate live mission_cfg in place — the same dict identity that the
        # mission captured at build time. Next frame must reflect the change.
        rt.mission_cfg["ax25"]["src_call"] = "WBBBBB"
        framed_after = rt.platform.frame_tx(prep.encoded)
        self.assertEqual(framed_after.log_fields["ax25"]["src_call"], "WBBBBB")

    def test_asm_golay_mtu_is_enforced_via_mission_framer(self):
        from mav_gss_lib.server.state import create_runtime
        rt = create_runtime()
        rt.platform_cfg["tx"]["uplink_mode"] = "ASM+Golay"
        # Assemble an oversized command bytes payload directly to exercise
        # framer admission without going through MAVERIC cmd parsing.
        from mav_gss_lib.platform import EncodedCommand
        oversize = EncodedCommand(raw=b"A" * 1024)
        with self.assertRaisesRegex(ValueError, "too large for ASM\\+Golay"):
            rt.platform.frame_tx(oversize)


class TestFixtureMissionFraming(unittest.TestCase):
    def test_echo_v2_passthrough_frame_equals_encoded(self):
        from mav_gss_lib.platform.loader import load_mission_spec_from_split
        from mav_gss_lib.platform import EncodedCommand

        spec = load_mission_spec_from_split({}, "echo_v2", {})
        encoded = EncodedCommand(raw=b"hello")
        framed = spec.commands.frame(encoded)
        self.assertEqual(framed.wire, encoded.raw)
        self.assertEqual(framed.frame_label, "RAW")
        self.assertIsNone(framed.max_payload)


class TestTxLogAcceptsMissionLogFields(unittest.TestCase):
    def test_log_fields_and_frame_label_land_in_jsonl(self):
        import tempfile
        from mav_gss_lib.logging import TXLog
        from mav_gss_lib.platform.tx.logging import tx_log_record

        with tempfile.TemporaryDirectory() as tmp:
            log = TXLog(tmp, zmq_addr="tcp://127.0.0.1:52002", version="1.2.3")
            try:
                raw_cmd = b"\x01\x02"
                wire = b"\x01\x02\x03\x04"
                record = tx_log_record(
                    7,
                    {"title": "PING", "subtitle": ""},
                    {"cmd": "ping"},
                    raw_cmd, wire,
                    session_id=log.session_id,
                    ts_ms=1_700_000_000_000,
                    version="1.2.3",
                    operator="irfan", station="GS-0",
                    frame_label="AX.25",
                    log_fields={
                        # Legacy `uplink_mode` key included on purpose — the
                        # platform tx_log_record must drop it defensively.
                        "uplink_mode": "AX.25",
                        "ax25": {"src_call": "TEST", "src_ssid": 1},
                        "csp": {"prio": 2, "dest": 8},
                    },
                )
                log.write_mission_command(
                    record, raw_cmd=raw_cmd, wire=wire,
                    log_text=["  MODE       AX.25"],
                )
            finally:
                log.close()

            with open(log.jsonl_path) as f:
                rec = json.loads(f.readline())

        self.assertEqual(rec["frame_label"], "AX.25")
        # Legacy `uplink_mode` alias must not surface — neither top-level
        # nor under the nested mission block.
        self.assertNotIn("uplink_mode", rec)
        self.assertNotIn("uplink_mode", rec["mission"])
        # AX.25 / CSP headers now live under the nested `mission` dict —
        # the unified envelope keeps top-level keys stable across missions.
        self.assertEqual(rec["mission"]["ax25"]["src_call"], "TEST")
        self.assertEqual(rec["mission"]["csp"]["dest"], 8)
        self.assertEqual(rec["operator"], "irfan")
        self.assertEqual(rec["station"], "GS-0")
        self.assertEqual(rec["event_kind"], "tx_command")


if __name__ == "__main__":
    unittest.main()
