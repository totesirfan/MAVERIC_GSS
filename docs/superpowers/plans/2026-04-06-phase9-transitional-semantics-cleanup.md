# Phase 9: Transitional Semantics Cleanup

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove MAVERIC-specific semantic assumptions from platform-core logging and classification, replacing them with adapter-driven hooks that any mission can implement.

**Architecture:** RX logging is split into a stable platform envelope (packet number, timestamps, frame type, raw/payload hex, classification flags, protocol/integrity blocks) plus an adapter-provided `mission` payload for mission-specific content. `build_rx_log_record()` moves from `parsing.py` to a platform function that calls a new adapter method `build_log_mission_data(pkt)`. `SessionLog.write_packet()` calls a new adapter method `format_log_lines(pkt)` for mission-specific text lines. The `_classify_unknown()` logic is replaced by an adapter method `is_unknown_packet(parsed)`. The replay path reads the stable platform envelope generically and falls back to legacy flat fields for pre-Phase-9 MAVERIC logs.

**Tech Stack:** Python 3.10+, pytest

---

## Design Decisions

1. **Stable platform log envelope.** Platform owns: `v`, `pkt`, `gs_ts`, `frame_type`, `tx_meta`, `raw_hex`, `payload_hex`, `raw_len`, `payload_len`, `delta_t`, `duplicate`, `uplink_echo`, `unknown`, `protocol_blocks`, `integrity_blocks`. These fields are the same for every mission and are the replay path's primary data source.

2. **Adapter-provided `mission` block.** Each mission adapter returns a dict from `build_log_mission_data(pkt)` containing mission-specific content. For MAVERIC: `csp_candidate`, `csp_plausible`, `cmd`, `sat_ts_ms`, `tail_hex`. This block is opaque to the platform.

3. **Adapter-provided text log lines.** `format_log_lines(pkt)` returns a `list[str]` of pre-formatted text lines for the human-readable text log only. The platform handles the separator, warnings, hex dump, and ASCII — the adapter handles protocol headers, command details, timestamps, and CRC display as text. Structured integrity data for JSONL replay comes from the platform envelope's `integrity_blocks` field (via `adapter.integrity_blocks()`), NOT from `format_log_lines()`. The text log and JSONL log serve different audiences — text is human-readable backup, JSONL is machine-readable replay source.

4. **`is_unknown_packet(parsed)` replaces `_classify_unknown(cmd)`.** The current logic hardcodes `cmd is None → unknown`, which is a MAVERIC assumption. The adapter now owns this classification. The platform still tracks `unknown_count` and assigns `unknown_num`.

5. **Backward-compatible replay.** The replay endpoint (`/api/logs/{session_id}`) reads platform envelope fields generically from any log. For MAVERIC-specific detail (cmd, args, routing), it checks the `mission` block first, then falls back to the legacy flat `cmd` dict for pre-Phase-9 logs.

6. **RX vs TX log entry discrimination.** New-format RX log entries are identified by the presence of the `pkt` field (packet number — RX-only). TX entries have `n` instead. This replaces the old heuristic of checking whether `entry["cmd"]` is a dict vs string, which breaks when `cmd` moves into the `mission` block. The platform envelope always has `pkt` for RX entries, making this a stable discriminator.

7. **No changes to TX logging.** `TXLog.write_command()` already receives fully decomposed parameters (src, dest, cmd, args, etc.) — it doesn't read `Packet` fields. TX logging stays as-is in Phase 9.

8. **EchoMissionAdapter gets minimal implementations.** `build_log_mission_data()` returns `{}`, `format_log_lines()` returns `[]`, `is_unknown_packet()` returns `True` (no command parsing → always unknown).

## File Plan

| Action | File | Change |
|---|---|---|
| Modify | `mav_gss_lib/mission_adapter.py` | Add 3 methods to MissionAdapter Protocol |
| Modify | `mav_gss_lib/parsing.py` | Replace `build_rx_log_record()` with platform envelope + adapter call; replace `_classify_unknown()` with adapter call |
| Modify | `mav_gss_lib/logging.py` | Update `SessionLog.write_packet()` to use adapter for mission-specific text |
| Modify | `mav_gss_lib/web_runtime/services.py` | Pass adapter to log writing calls |
| Modify | `mav_gss_lib/missions/maveric/adapter.py` | Add `build_log_mission_data()`, `format_log_lines()`, `is_unknown_packet()` |
| Modify | `tests/echo_mission.py` | Add 3 new methods to EchoMissionAdapter |
| Modify | `mav_gss_lib/web_runtime/api.py` | Update replay to read platform envelope + mission block with legacy fallback |
| Create | `tests/test_ops_logging.py` | Tests for platform envelope, mission payload, text formatting, replay compat |
| Modify | `tests/test_ops_ax25_path.py` | Update `build_rx_log_record()` call to pass adapter; update assertions for new record shape |
| Modify | `tests/test_ops_rx_pipeline.py` | Update `build_rx_log_record()` call to pass adapter; update assertions for new record shape |

## Test Commands

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -v
```

---

## Task 1: Add New Methods to MissionAdapter Protocol and Echo Fixture

**Files:**
- Modify: `mav_gss_lib/mission_adapter.py`
- Modify: `tests/echo_mission.py`
- Create: `tests/test_ops_logging.py`

- [ ] **Step 1: Write failing tests for the new adapter methods**

Create `tests/test_ops_logging.py`:

```python
"""Tests for platform log envelope and adapter-driven mission logging.

Verifies:
  1. New adapter methods exist on MissionAdapter Protocol
  2. EchoMissionAdapter satisfies updated Protocol
  3. Platform envelope contains stable fields
  4. Adapter mission data is opaque to platform
  5. Adapter text log lines are pre-formatted strings
  6. is_unknown_packet classification is adapter-driven
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.mission_adapter import MissionAdapter, validate_adapter
from tests.echo_mission import EchoMissionAdapter, ADAPTER_API_VERSION


class TestAdapterLoggingMethods(unittest.TestCase):
    """Verify new logging methods on adapters."""

    def setUp(self):
        self.adapter = EchoMissionAdapter(cmd_defs={})

    def test_echo_adapter_still_satisfies_protocol(self):
        """EchoMissionAdapter passes isinstance check with new methods."""
        self.assertIsInstance(self.adapter, MissionAdapter)
        validate_adapter(self.adapter, ADAPTER_API_VERSION, "echo")

    def test_build_log_mission_data_returns_dict(self):
        """build_log_mission_data() returns a dict."""

        class MockPkt:
            pkt_num = 1
            gs_ts = "2026-04-06T10:30:00"
            gs_ts_short = "10:30:00"
            raw = b"\xDE\xAD"
            inner_payload = b"\xDE\xAD"
            frame_type = "RAW"
            is_dup = False
            is_uplink_echo = False
            is_unknown = True
            warnings = []
            csp = None
            cmd = None
            cmd_tail = None
            ts_result = None
            crc_status = {}
            stripped_hdr = None
            csp_plausible = False

        result = self.adapter.build_log_mission_data(MockPkt())
        self.assertIsInstance(result, dict)

    def test_format_log_lines_returns_list_of_strings(self):
        """format_log_lines() returns a list of strings."""

        class MockPkt:
            pkt_num = 1
            gs_ts = "2026-04-06T10:30:00"
            gs_ts_short = "10:30:00"
            raw = b"\xDE\xAD"
            inner_payload = b"\xDE\xAD"
            frame_type = "RAW"
            is_dup = False
            is_uplink_echo = False
            is_unknown = True
            warnings = []
            csp = None
            cmd = None
            cmd_tail = None
            ts_result = None
            crc_status = {}
            stripped_hdr = None
            csp_plausible = False

        result = self.adapter.format_log_lines(MockPkt())
        self.assertIsInstance(result, list)
        for item in result:
            self.assertIsInstance(item, str)

    def test_is_unknown_packet_returns_bool(self):
        """is_unknown_packet() returns a bool."""
        from mav_gss_lib.mission_adapter import ParsedPacket
        parsed = ParsedPacket()
        result = self.adapter.is_unknown_packet(parsed)
        self.assertIsInstance(result, bool)

    def test_echo_adapter_unknown_is_always_true(self):
        """Echo mission has no command parsing — all packets are unknown."""
        from mav_gss_lib.mission_adapter import ParsedPacket
        parsed = ParsedPacket()
        self.assertTrue(self.adapter.is_unknown_packet(parsed))

    def test_echo_adapter_mission_data_is_empty(self):
        """Echo mission produces empty mission log data."""

        class MockPkt:
            pkt_num = 1
            gs_ts = "2026-04-06T10:30:00"
            gs_ts_short = "10:30:00"
            raw = b"\xDE\xAD"
            inner_payload = b"\xDE\xAD"
            frame_type = "RAW"
            is_dup = False
            is_uplink_echo = False
            is_unknown = True
            warnings = []
            csp = None
            cmd = None
            cmd_tail = None
            ts_result = None
            crc_status = {}
            stripped_hdr = None
            csp_plausible = False

        self.assertEqual(self.adapter.build_log_mission_data(MockPkt()), {})
        self.assertEqual(self.adapter.format_log_lines(MockPkt()), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/test_ops_logging.py -v
```

Expected: FAIL — `build_log_mission_data`, `format_log_lines`, `is_unknown_packet` don't exist yet.

- [ ] **Step 3: Add 3 new methods to MissionAdapter Protocol**

In `mav_gss_lib/mission_adapter.py`, add these three method signatures to the `MissionAdapter` Protocol class, after the rendering-slot block:

```python
    # -- Logging-slot contract (Phase 9) --
    def build_log_mission_data(self, pkt) -> dict: ...
    def format_log_lines(self, pkt) -> list[str]: ...
    def is_unknown_packet(self, parsed: ParsedPacket) -> bool: ...
```

Also add all 3 new methods to the `validate_adapter()` missing-methods list so startup validation catches missing implementations:

```python
        for method_name in (
            'detect_frame_type', 'normalize_frame', 'parse_packet',
            'duplicate_fingerprint', 'is_uplink_echo',
            'build_raw_command', 'validate_tx_args',
            'packet_list_columns', 'packet_list_row',
            'packet_detail_blocks', 'protocol_blocks', 'integrity_blocks',
            'build_log_mission_data', 'format_log_lines', 'is_unknown_packet',
        ):
```

- [ ] **Step 4: Add 3 new methods to EchoMissionAdapter**

In `tests/echo_mission.py`, add these methods to the `EchoMissionAdapter` class:

```python
    def build_log_mission_data(self, pkt) -> dict:
        return {}

    def format_log_lines(self, pkt) -> list[str]:
        return []

    def is_unknown_packet(self, parsed) -> bool:
        return True
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/test_ops_logging.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 6: Run full suite to verify no regressions**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q
```

Expected: All pass (existing tests still work since old methods are unchanged).

- [ ] **Step 7: Commit**

```bash
git add mav_gss_lib/mission_adapter.py tests/echo_mission.py tests/test_ops_logging.py
git commit -m "Add logging-slot methods to MissionAdapter Protocol"
```

---

## Task 2: Implement MAVERIC Adapter Logging Methods

**Files:**
- Modify: `mav_gss_lib/missions/maveric/adapter.py`
- Modify: `tests/test_ops_logging.py`

- [ ] **Step 1: Write failing tests for MAVERIC logging methods**

Add to `tests/test_ops_logging.py`:

```python
class TestMavericLoggingMethods(unittest.TestCase):
    """Verify MAVERIC adapter produces correct log data."""

    def setUp(self):
        from mav_gss_lib.config import load_gss_config, get_command_defs_path
        from mav_gss_lib.mission_adapter import load_mission_metadata
        from mav_gss_lib.protocol import init_nodes, load_command_defs
        from mav_gss_lib.missions.maveric.adapter import MavericMissionAdapter

        cfg = load_gss_config()
        load_mission_metadata(cfg)
        init_nodes(cfg)
        cmd_defs, _ = load_command_defs(get_command_defs_path(cfg))
        self.adapter = MavericMissionAdapter(cmd_defs=cmd_defs)

    def _make_pkt(self, cmd=None, csp=None, ts_result=None, crc_status=None):
        class MockPkt:
            pass
        pkt = MockPkt()
        pkt.pkt_num = 1
        pkt.gs_ts = "2026-04-06 10:30:00 PDT"
        pkt.gs_ts_short = "10:30:00"
        pkt.frame_type = "AX.25"
        pkt.raw = b"\xDE\xAD\xBE\xEF"
        pkt.inner_payload = b"\xBE\xEF"
        pkt.delta_t = 1.5
        pkt.stripped_hdr = "WM2XBB>WS9XSW"
        pkt.csp = csp
        pkt.csp_plausible = csp is not None
        pkt.cmd = cmd
        pkt.cmd_tail = None
        pkt.ts_result = ts_result
        pkt.crc_status = crc_status or {"csp_crc32_valid": None, "csp_crc32_rx": None, "csp_crc32_comp": None}
        pkt.text = ""
        pkt.warnings = []
        pkt.is_dup = False
        pkt.is_uplink_echo = False
        pkt.is_unknown = cmd is None
        pkt.unknown_num = 1 if cmd is None else None
        return pkt

    def test_mission_data_with_command(self):
        """MAVERIC mission data includes cmd block when command is present."""
        cmd = {
            "src": 6, "dest": 1, "echo": 0, "pkt_type": 2,
            "cmd_id": "com_ping", "crc": 0x1234, "crc_valid": True,
            "args": [], "schema_match": False,
        }
        pkt = self._make_pkt(cmd=cmd)
        data = self.adapter.build_log_mission_data(pkt)
        self.assertIn("cmd", data)
        self.assertEqual(data["cmd"]["cmd_id"], "com_ping")

    def test_mission_data_with_csp(self):
        """MAVERIC mission data includes csp_candidate when CSP is present."""
        csp = {"prio": 2, "src": 0, "dest": 8, "dport": 24, "sport": 0, "flags": 0}
        pkt = self._make_pkt(csp=csp)
        data = self.adapter.build_log_mission_data(pkt)
        self.assertIn("csp_candidate", data)
        self.assertTrue(data["csp_plausible"])

    def test_mission_data_without_command_is_minimal(self):
        """MAVERIC mission data is minimal when no command is parsed."""
        pkt = self._make_pkt()
        data = self.adapter.build_log_mission_data(pkt)
        self.assertNotIn("cmd", data)

    def test_format_log_lines_with_command(self):
        """MAVERIC text log includes command routing and ID lines."""
        cmd = {
            "src": 6, "dest": 1, "echo": 0, "pkt_type": 2,
            "cmd_id": "com_ping", "crc": 0x1234, "crc_valid": True,
            "args": [], "schema_match": False,
        }
        pkt = self._make_pkt(cmd=cmd)
        lines = self.adapter.format_log_lines(pkt)
        self.assertIsInstance(lines, list)
        text = "\n".join(lines)
        self.assertIn("com_ping", text)

    def test_format_log_lines_without_command(self):
        """MAVERIC text log is empty when no command is parsed."""
        pkt = self._make_pkt()
        lines = self.adapter.format_log_lines(pkt)
        self.assertEqual(lines, [])

    def test_is_unknown_packet_with_command(self):
        """MAVERIC: packet with a parsed command is not unknown."""
        from mav_gss_lib.mission_adapter import ParsedPacket
        parsed = ParsedPacket(cmd={"cmd_id": "com_ping"})
        self.assertFalse(self.adapter.is_unknown_packet(parsed))

    def test_is_unknown_packet_without_command(self):
        """MAVERIC: packet without a parsed command is unknown."""
        from mav_gss_lib.mission_adapter import ParsedPacket
        parsed = ParsedPacket()
        self.assertTrue(self.adapter.is_unknown_packet(parsed))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/test_ops_logging.py::TestMavericLoggingMethods -v
```

Expected: FAIL — methods don't exist on MavericMissionAdapter yet.

- [ ] **Step 3: Implement `is_unknown_packet()` on MavericMissionAdapter**

Add to `mav_gss_lib/missions/maveric/adapter.py`:

```python
    def is_unknown_packet(self, parsed) -> bool:
        """MAVERIC: a packet is unknown when no command was decoded."""
        cmd = parsed.cmd if hasattr(parsed, 'cmd') else None
        return cmd is None
```

- [ ] **Step 4: Implement `build_log_mission_data()` on MavericMissionAdapter**

Add to `mav_gss_lib/missions/maveric/adapter.py`:

```python
    def build_log_mission_data(self, pkt) -> dict:
        """Return MAVERIC-specific fields for the JSONL log mission block.

        This produces the same fields that were previously inlined in
        build_rx_log_record(), but scoped under a 'mission' key in the
        platform envelope.
        """
        data = {}
        if pkt.csp:
            data["csp_candidate"] = pkt.csp
            data["csp_plausible"] = pkt.csp_plausible
        if pkt.ts_result:
            data["sat_ts_ms"] = pkt.ts_result[2]
        crc_status = pkt.crc_status
        if crc_status.get("csp_crc32_valid") is not None:
            data["csp_crc32"] = {
                "valid": crc_status["csp_crc32_valid"],
                "received": f"0x{crc_status['csp_crc32_rx']:08x}",
            }
        cmd = pkt.cmd
        if cmd:
            cmd_log = {
                "src": cmd["src"], "dest": cmd["dest"],
                "echo": cmd["echo"], "pkt_type": cmd["pkt_type"],
                "cmd_id": cmd["cmd_id"], "crc": cmd["crc"],
                "crc_valid": cmd.get("crc_valid"),
            }
            if cmd.get("schema_match"):
                typed_log = {}
                for ta in cmd["typed_args"]:
                    if ta["type"] == "epoch_ms" and "ms" in ta["value"]:
                        typed_log[ta["name"]] = ta["value"]["ms"]
                    elif ta["type"] == "blob" and isinstance(ta["value"], (bytes, bytearray)):
                        typed_log[ta["name"]] = ta["value"].hex()
                    else:
                        typed_log[ta["name"]] = ta["value"]
                cmd_log["args"] = typed_log
                if cmd["extra_args"]:
                    cmd_log["extra_args"] = cmd["extra_args"]
            else:
                cmd_log["args"] = cmd["args"]
                if cmd.get("schema_warning"):
                    cmd_log["schema_warning"] = cmd["schema_warning"]
            data["cmd"] = cmd_log
            if pkt.cmd_tail:
                data["tail_hex"] = pkt.cmd_tail.hex()
        return data
```

- [ ] **Step 5: Implement `format_log_lines()` on MavericMissionAdapter**

Add to `mav_gss_lib/missions/maveric/adapter.py`. This contains the mission-specific text formatting currently in `SessionLog.write_packet()`:

```python
    def format_log_lines(self, pkt) -> list[str]:
        """Return MAVERIC-specific text log lines for one packet.

        Platform handles: separator, warnings, hex dump, ASCII.
        Adapter handles: AX.25 header, CSP header, satellite time,
        command routing/args, CRC display.
        """
        from mav_gss_lib.protocol import format_arg_value

        lines = []

        # AX.25 header
        if pkt.stripped_hdr:
            lines.append(f"  {'AX.25 HDR':<12}{pkt.stripped_hdr}")

        # CSP header
        csp = pkt.csp
        if csp:
            tag = "CSP V1" if pkt.csp_plausible else "CSP V1 [?]"
            lines.append(f"  {tag:<12}"
                f"Prio:{csp['prio']}  Src:{csp['src']}  Dest:{csp['dest']}  "
                f"DPort:{csp['dport']}  SPort:{csp['sport']}  Flags:0x{csp['flags']:02X}")

        # Satellite time
        ts_result = pkt.ts_result
        if ts_result:
            dt_utc, dt_local, raw_ms = ts_result
            lines.append(f"  {'SAT TIME':<12}"
                f"{dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC')} \u2502 "
                f"{dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')}  ({raw_ms})")

        # Command
        cmd = pkt.cmd
        if cmd:
            lines.append(f"  {'CMD':<12}"
                f"Src:{node_name(cmd['src'])}  Dest:{node_name(cmd['dest'])}  "
                f"Echo:{node_name(cmd['echo'])}  Type:{ptype_name(cmd['pkt_type'])}")
            lines.append(f"  {'CMD ID':<12}{cmd['cmd_id']}")

            if cmd.get("schema_match"):
                for ta in cmd.get("typed_args", []):
                    lines.append(f"  {ta['name'].upper():<12}{format_arg_value(ta)}")
                for i, extra in enumerate(cmd.get("extra_args", [])):
                    lines.append(f"  {f'ARG +{i}':<12}{extra}")
            else:
                if cmd.get("schema_warning"):
                    lines.append(f"  {'\u26a0 SCHEMA':<12}{cmd['schema_warning']}")
                for i, arg in enumerate(cmd.get("args", [])):
                    lines.append(f"  {f'ARG {i}':<12}{arg}")

        # CRC
        if cmd and cmd.get("crc") is not None:
            tag = "OK" if cmd.get("crc_valid") else "FAIL"
            lines.append(f"  {'CRC-16':<12}0x{cmd['crc']:04x} [{tag}]")
        crc_status = pkt.crc_status
        if crc_status.get("csp_crc32_valid") is not None:
            tag = "OK" if crc_status["csp_crc32_valid"] else "FAIL"
            lines.append(f"  {'CRC-32C':<12}0x{crc_status['csp_crc32_rx']:08x} [{tag}]")

        return lines
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/test_ops_logging.py -v
```

Expected: All 14 tests PASS.

- [ ] **Step 7: Run full suite**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q
```

- [ ] **Step 8: Commit**

```bash
git add mav_gss_lib/missions/maveric/adapter.py tests/test_ops_logging.py
git commit -m "Implement logging-slot methods on MavericMissionAdapter"
```

---

## Task 3: Replace `build_rx_log_record()` With Platform Envelope + Adapter Call

**Files:**
- Modify: `mav_gss_lib/parsing.py`
- Modify: `mav_gss_lib/web_runtime/services.py`
- Modify: `tests/test_ops_logging.py`
- Modify: `tests/test_ops_ax25_path.py` (existing consumer of `build_rx_log_record`)
- Modify: `tests/test_ops_rx_pipeline.py` (existing consumer of `build_rx_log_record`)

- [ ] **Step 1: Write test for new platform envelope structure**

Add to `tests/test_ops_logging.py`:

```python
class TestPlatformLogEnvelope(unittest.TestCase):
    """Verify the platform log envelope structure."""

    def setUp(self):
        from mav_gss_lib.config import load_gss_config, get_command_defs_path
        from mav_gss_lib.mission_adapter import load_mission_metadata
        from mav_gss_lib.protocol import init_nodes, load_command_defs
        from mav_gss_lib.missions.maveric.adapter import MavericMissionAdapter

        cfg = load_gss_config()
        load_mission_metadata(cfg)
        init_nodes(cfg)
        cmd_defs, _ = load_command_defs(get_command_defs_path(cfg))
        self.adapter = MavericMissionAdapter(cmd_defs=cmd_defs)

    def _make_pkt(self):
        class MockPkt:
            pass
        pkt = MockPkt()
        pkt.pkt_num = 42
        pkt.gs_ts = "2026-04-06 10:30:00 PDT"
        pkt.gs_ts_short = "10:30:00"
        pkt.frame_type = "AX.25"
        pkt.raw = b"\xDE\xAD\xBE\xEF"
        pkt.inner_payload = b"\xBE\xEF"
        pkt.delta_t = 1.5
        pkt.stripped_hdr = None
        pkt.csp = None
        pkt.csp_plausible = False
        pkt.cmd = None
        pkt.cmd_tail = None
        pkt.ts_result = None
        pkt.crc_status = {"csp_crc32_valid": None, "csp_crc32_rx": None, "csp_crc32_comp": None}
        pkt.text = ""
        pkt.warnings = []
        pkt.is_dup = False
        pkt.is_uplink_echo = False
        pkt.is_unknown = True
        pkt.unknown_num = 1
        return pkt

    def test_envelope_has_stable_platform_fields(self):
        """Platform envelope contains all stable fields."""
        from mav_gss_lib.parsing import build_rx_log_record
        pkt = self._make_pkt()
        record = build_rx_log_record(pkt, "4.3.1", {"transmitter": "UHF"}, self.adapter)
        self.assertEqual(record["v"], "4.3.1")
        self.assertEqual(record["pkt"], 42)
        self.assertEqual(record["gs_ts"], "2026-04-06 10:30:00 PDT")
        self.assertEqual(record["frame_type"], "AX.25")
        self.assertEqual(record["raw_hex"], "deadbeef")
        self.assertEqual(record["payload_hex"], "beef")
        self.assertEqual(record["raw_len"], 4)
        self.assertEqual(record["payload_len"], 2)
        self.assertAlmostEqual(record["delta_t"], 1.5)
        self.assertFalse(record["duplicate"])
        self.assertFalse(record["uplink_echo"])
        self.assertTrue(record["unknown"])

    def test_envelope_has_protocol_and_integrity_blocks(self):
        """Platform envelope includes serialized protocol/integrity blocks."""
        from mav_gss_lib.parsing import build_rx_log_record
        pkt = self._make_pkt()
        pkt.csp = {"prio": 2, "src": 0, "dest": 8, "dport": 24, "sport": 0, "flags": 0}
        pkt.csp_plausible = True
        pkt.is_unknown = False
        pkt.cmd = {
            "src": 6, "dest": 1, "echo": 0, "pkt_type": 2,
            "cmd_id": "com_ping", "crc": 0x1234, "crc_valid": True,
            "args": [], "schema_match": False,
        }
        record = build_rx_log_record(pkt, "4.3.1", {"transmitter": "UHF"}, self.adapter)
        self.assertIn("protocol_blocks", record)
        self.assertIn("integrity_blocks", record)
        self.assertIsInstance(record["protocol_blocks"], list)
        self.assertIsInstance(record["integrity_blocks"], list)

    def test_envelope_has_mission_block(self):
        """Platform envelope contains adapter-provided mission block."""
        from mav_gss_lib.parsing import build_rx_log_record
        pkt = self._make_pkt()
        pkt.cmd = {
            "src": 6, "dest": 1, "echo": 0, "pkt_type": 2,
            "cmd_id": "com_ping", "crc": 0x1234, "crc_valid": True,
            "args": [], "schema_match": False,
        }
        pkt.is_unknown = False
        record = build_rx_log_record(pkt, "4.3.1", {"transmitter": "UHF"}, self.adapter)
        self.assertIn("mission", record)
        self.assertIn("cmd", record["mission"])
        self.assertEqual(record["mission"]["cmd"]["cmd_id"], "com_ping")

    def test_envelope_no_flat_maveric_fields(self):
        """Platform envelope does not contain flat MAVERIC-specific fields at top level."""
        from mav_gss_lib.parsing import build_rx_log_record
        pkt = self._make_pkt()
        pkt.csp = {"prio": 2, "src": 0, "dest": 8, "dport": 24, "sport": 0, "flags": 0}
        pkt.cmd = {
            "src": 6, "dest": 1, "echo": 0, "pkt_type": 2,
            "cmd_id": "com_ping", "crc": 0x1234, "crc_valid": True,
            "args": [], "schema_match": False,
        }
        record = build_rx_log_record(pkt, "4.3.1", {"transmitter": "UHF"}, self.adapter)
        # These were previously at top level — now inside mission block
        self.assertNotIn("csp_candidate", record)
        self.assertNotIn("csp_plausible", record)
        self.assertNotIn("cmd", record)
        self.assertNotIn("sat_ts_ms", record)
        self.assertNotIn("tail_hex", record)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/test_ops_logging.py::TestPlatformLogEnvelope -v
```

Expected: FAIL — `build_rx_log_record()` has old signature (no adapter param).

- [ ] **Step 3: Replace `build_rx_log_record()` in `parsing.py`**

Replace the entire `build_rx_log_record()` function in `mav_gss_lib/parsing.py` with:

```python
def build_rx_log_record(pkt, version, meta, adapter):
    """Build a JSONL log record from a Packet.

    Platform envelope: stable fields shared by all missions.
    Mission block: adapter-provided opaque payload.
    Protocol/integrity blocks: serialized from adapter rendering slots.
    """
    from dataclasses import asdict

    record = {
        "v": version, "pkt": pkt.pkt_num, "gs_ts": pkt.gs_ts,
        "frame_type": pkt.frame_type,
        "tx_meta": str(meta.get("transmitter", "")),
        "raw_hex": pkt.raw.hex(), "payload_hex": pkt.inner_payload.hex(),
        "raw_len": len(pkt.raw), "payload_len": len(pkt.inner_payload),
        "duplicate": pkt.is_dup,
        "uplink_echo": pkt.is_uplink_echo,
        "unknown": pkt.is_unknown,
    }
    if pkt.delta_t is not None:
        record["delta_t"] = round(pkt.delta_t, 4)

    # Protocol and integrity blocks — serialized from adapter rendering slots
    record["protocol_blocks"] = [asdict(b) for b in adapter.protocol_blocks(pkt)]
    record["integrity_blocks"] = [asdict(b) for b in adapter.integrity_blocks(pkt)]

    # Mission-specific payload — opaque to platform
    mission_data = adapter.build_log_mission_data(pkt)
    if mission_data:
        record["mission"] = mission_data

    return record
```

- [ ] **Step 4: Update the call site in `services.py`**

In `mav_gss_lib/web_runtime/services.py`, update the `broadcast_loop()` call to pass the adapter. Change line 126:

```python
                        self.log.write_jsonl(build_rx_log_record(pkt, version, meta))
```

to:

```python
                        self.log.write_jsonl(build_rx_log_record(pkt, version, meta, self.runtime.adapter))
```

- [ ] **Step 5: Run tests**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/test_ops_logging.py -v
```

Expected: All tests PASS including the new envelope tests.

- [ ] **Step 6: Update existing test consumers of `build_rx_log_record()`**

Two existing test files call `build_rx_log_record()` with the old 3-arg signature and assert `record["cmd"]` at top level. Both need updating.

In `tests/test_ops_ax25_path.py`, update `test_ax25_log_record_matches_input_bytes`:

Change:
```python
        record = build_rx_log_record(pkt, "test", META_AX25)
        self.assertEqual(record["raw_hex"], payload.hex())
        self.assertEqual(record["frame_type"], "AX.25")
        self.assertEqual(record["cmd"]["cmd_id"], "set_mode")
```

To:
```python
        record = build_rx_log_record(pkt, "test", META_AX25, self.pipeline.adapter)
        self.assertEqual(record["raw_hex"], payload.hex())
        self.assertEqual(record["frame_type"], "AX.25")
        self.assertEqual(record["mission"]["cmd"]["cmd_id"], "set_mode")
```

In `tests/test_ops_rx_pipeline.py`, update `test_log_record_contains_operationally_relevant_fields`:

Change:
```python
        record = build_rx_log_record(pkt, "test-version", META_AX25)
        self.assertIn("gs_ts", record)
        self.assertIn("frame_type", record)
        self.assertIn("raw_hex", record)
        self.assertEqual(record["cmd"]["cmd_id"], "set_mode")
        self.assertEqual(record["frame_type"], "AX.25")
```

To:
```python
        record = build_rx_log_record(pkt, "test-version", META_AX25, self.pipeline.adapter)
        self.assertIn("gs_ts", record)
        self.assertIn("frame_type", record)
        self.assertIn("raw_hex", record)
        self.assertEqual(record["mission"]["cmd"]["cmd_id"], "set_mode")
        self.assertEqual(record["frame_type"], "AX.25")
```

- [ ] **Step 7: Run full suite**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q
```

- [ ] **Step 8: Commit**

```bash
git add mav_gss_lib/parsing.py mav_gss_lib/web_runtime/services.py tests/test_ops_logging.py tests/test_ops_ax25_path.py tests/test_ops_rx_pipeline.py
git commit -m "Replace build_rx_log_record with platform envelope + adapter mission block"
```

---

## Task 4: Update `SessionLog.write_packet()` to Use Adapter

**Files:**
- Modify: `mav_gss_lib/logging.py`
- Modify: `mav_gss_lib/web_runtime/services.py`

**Note:** `write_packet()` is called from two places: `services.py` (updated here) and `backup_control/MAV_RX.py` (legacy TUI). The `adapter=None` default keeps the legacy caller working — it produces platform-only text output (separator, warnings, hex, ASCII) with no mission-specific lines. No tests call `write_packet()` directly.

- [ ] **Step 1: Update `SessionLog.write_packet()` signature and body**

Replace the `write_packet()` method in `mav_gss_lib/logging.py` (`SessionLog` class) with:

```python
    def write_packet(self, pkt, adapter=None):
        """Write one RX packet entry. Takes a Packet instance.

        Platform handles: separator, warnings, hex dump, ASCII.
        Adapter handles: mission-specific text lines (protocol headers,
        command details, CRC display) via format_log_lines().
        """
        lines = []
        label = f"U-{pkt.unknown_num}" if pkt.is_unknown and pkt.unknown_num is not None else f"#{pkt.pkt_num}"
        extras = f"{pkt.frame_type}  {len(pkt.raw)}B \u2192 {len(pkt.inner_payload)}B"
        if pkt.delta_t is not None: extras += f"  \u0394t {pkt.delta_t:.3f}s"
        if pkt.is_dup: extras += "  [DUP]"
        if pkt.is_uplink_echo: extras += "  [UL]"
        lines.append(self._separator(label, extras))
        if pkt.is_uplink_echo:
            lines.append("  \u25b2\u25b2\u25b2 UPLINK ECHO \u25b2\u25b2\u25b2")

        # Warnings
        for w in pkt.warnings:
            lines.append(self._field("\u26a0 WARNING", w))

        # Mission-specific lines (adapter-driven)
        if adapter is not None:
            lines.extend(adapter.format_log_lines(pkt))

        lines.extend(self._hex_lines(pkt.raw, "HEX"))
        if pkt.text:
            lines.append(self._field("ASCII", pkt.text))

        self._write_entry(lines)
```

- [ ] **Step 2: Update the call site in `services.py`**

In `mav_gss_lib/web_runtime/services.py`, update the `broadcast_loop()` call. Change line 127:

```python
                        self.log.write_packet(pkt)
```

to:

```python
                        self.log.write_packet(pkt, adapter=self.runtime.adapter)
```

- [ ] **Step 3: Remove unused imports from `logging.py`**

In `mav_gss_lib/logging.py`, the top-level import line:

```python
from mav_gss_lib.protocol import node_label, ptype_label, clean_text, format_arg_value, crc16, crc32c
```

The `node_label`, `ptype_label`, and `format_arg_value` imports are no longer used by `SessionLog.write_packet()` (they moved to the adapter). However, `TXLog.write_command()` still uses `node_label`, `ptype_label`, `clean_text`, `crc16`, `crc32c`. Remove only `format_arg_value`:

```python
from mav_gss_lib.protocol import node_label, ptype_label, clean_text, crc16, crc32c
```

- [ ] **Step 4: Run full suite**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add mav_gss_lib/logging.py mav_gss_lib/web_runtime/services.py
git commit -m "Update SessionLog.write_packet to use adapter for mission-specific text"
```

---

## Task 5: Replace `_classify_unknown()` With Adapter Call

**Files:**
- Modify: `mav_gss_lib/parsing.py`
- Modify: `tests/test_ops_logging.py`

- [ ] **Step 1: Write test for adapter-driven unknown classification**

Add to `tests/test_ops_logging.py`:

```python
class TestUnknownClassification(unittest.TestCase):
    """Verify adapter-driven unknown packet classification."""

    def test_rx_pipeline_uses_adapter_for_unknown(self):
        """RxPipeline delegates is_unknown to the adapter."""
        from mav_gss_lib.parsing import RxPipeline
        from tests.echo_mission import EchoMissionAdapter

        adapter = EchoMissionAdapter(cmd_defs={})
        pipeline = RxPipeline(adapter, tx_freq_map={})
        pkt = pipeline.process({"transmitter": "test"}, b"\x01\x02\x03\x04")
        # Echo adapter: is_unknown_packet always returns True
        self.assertTrue(pkt.is_unknown)
        self.assertEqual(pkt.unknown_num, 1)

    def test_maveric_pipeline_known_command_not_unknown(self):
        """MAVERIC adapter classifies parsed commands as known."""
        from mav_gss_lib.parsing import RxPipeline
        from mav_gss_lib.config import load_gss_config, get_command_defs_path
        from mav_gss_lib.mission_adapter import load_mission_metadata
        from mav_gss_lib.protocol import init_nodes, load_command_defs
        from mav_gss_lib.missions.maveric.adapter import MavericMissionAdapter

        cfg = load_gss_config()
        load_mission_metadata(cfg)
        init_nodes(cfg)
        cmd_defs, _ = load_command_defs(get_command_defs_path(cfg))
        adapter = MavericMissionAdapter(cmd_defs=cmd_defs)

        pipeline = RxPipeline(adapter, tx_freq_map={})
        # Process a minimal raw packet with no valid command
        pkt = pipeline.process({"transmitter": "test"}, b"\x00\x01\x02\x03")
        # Short payload with no valid command → unknown
        self.assertTrue(pkt.is_unknown)
```

- [ ] **Step 2: Run tests to verify they pass (they should, since current behavior is equivalent)**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/test_ops_logging.py::TestUnknownClassification -v
```

- [ ] **Step 3: Replace `_classify_unknown()` in `parsing.py`**

Replace the `_classify_unknown()` method in `RxPipeline`:

```python
    def _classify_unknown(self, parsed):
        """Classify packet as unknown or known using the adapter, update counters."""
        is_unknown = self.adapter.is_unknown_packet(parsed)
        if is_unknown:
            self.unknown_count += 1
            return True, self.unknown_count
        self.packet_count += 1
        return False, None
```

- [ ] **Step 4: Run full suite**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add mav_gss_lib/parsing.py tests/test_ops_logging.py
git commit -m "Replace _classify_unknown with adapter-driven is_unknown_packet"
```

---

## Task 6: Update Replay Path for Platform Envelope + Legacy Fallback

**Files:**
- Modify: `mav_gss_lib/web_runtime/api.py`
- Modify: `tests/test_ops_logging.py`

- [ ] **Step 1: Write tests for replay backward compatibility**

These tests write real JSONL files and exercise the actual replay normalization logic in `api.py` via `parse_replay_entry()` (a helper we extract from the inline loop for testability).

Add to `tests/test_ops_logging.py`:

```python
import json
import os
import tempfile


class TestReplayCompat(unittest.TestCase):
    """Verify replay reads both new envelope and legacy flat formats.

    Uses real JSONL files and the actual replay normalization path.
    """

    def setUp(self):
        from mav_gss_lib.config import load_gss_config, get_command_defs_path
        from mav_gss_lib.mission_adapter import load_mission_metadata
        from mav_gss_lib.protocol import init_nodes, load_command_defs

        cfg = load_gss_config()
        load_mission_metadata(cfg)
        init_nodes(cfg)
        self.cmd_defs, _ = load_command_defs(get_command_defs_path(cfg))

    def _write_jsonl(self, entries):
        """Write entries to a temp JSONL file, return path."""
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
        self.addCleanup(os.unlink, path)
        return path

    def test_new_envelope_replay_extracts_cmd_from_mission_block(self):
        """Replay normalizes new-format RX log with cmd in mission block."""
        from mav_gss_lib.web_runtime.api import parse_replay_entry

        entry = {
            "v": "4.3.1", "pkt": 1,
            "gs_ts": "2026-04-06 10:30:00 PDT",
            "frame_type": "AX.25", "raw_hex": "deadbeef", "raw_len": 4,
            "payload_hex": "beef", "payload_len": 2,
            "duplicate": False, "uplink_echo": False, "unknown": False,
            "protocol_blocks": [], "integrity_blocks": [],
            "mission": {
                "cmd": {
                    "src": 6, "dest": 1, "echo": 0, "pkt_type": 2,
                    "cmd_id": "com_ping", "crc": 0x1234, "crc_valid": True,
                    "args": [],
                },
            },
        }
        result = parse_replay_entry(entry, self.cmd_defs)
        self.assertIsNotNone(result)
        self.assertEqual(result["cmd"], "com_ping")
        self.assertEqual(result["num"], 1)
        self.assertFalse(result["is_dup"])

    def test_legacy_flat_replay_extracts_cmd_from_top_level(self):
        """Replay normalizes pre-Phase-9 MAVERIC log with flat cmd dict."""
        from mav_gss_lib.web_runtime.api import parse_replay_entry

        entry = {
            "v": "4.3.0", "pkt": 1,
            "gs_ts": "2026-04-06 10:30:00 PDT",
            "frame_type": "AX.25", "raw_hex": "deadbeef", "raw_len": 4,
            "duplicate": False, "uplink_echo": False, "unknown": False,
            "cmd": {
                "src": 6, "dest": 1, "echo": 0, "pkt_type": 2,
                "cmd_id": "com_ping", "crc": 0x1234, "crc_valid": True,
                "args": [],
            },
            "csp_candidate": {"prio": 2, "src": 0, "dest": 8},
        }
        result = parse_replay_entry(entry, self.cmd_defs)
        self.assertIsNotNone(result)
        self.assertEqual(result["cmd"], "com_ping")
        self.assertEqual(result["csp_header"], {"prio": 2, "src": 0, "dest": 8})

    def test_tx_log_entry_detected_by_missing_pkt_field(self):
        """TX log entries (no 'pkt' field) are correctly identified."""
        from mav_gss_lib.web_runtime.api import parse_replay_entry

        entry = {
            "n": 1, "ts": "2026-04-06T10:30:00",
            "cmd": "com_ping", "args": "",
            "src": 6, "dest": 1, "echo": 0, "ptype": 1,
            "raw_hex": "deadbeef", "len": 4,
        }
        result = parse_replay_entry(entry, self.cmd_defs)
        self.assertIsNotNone(result)
        self.assertEqual(result["cmd"], "com_ping")
        # TX entries have is_dup=False, is_echo=False
        self.assertFalse(result["is_dup"])
        self.assertFalse(result["is_echo"])
```

- [ ] **Step 2: Extract `parse_replay_entry()` helper and update the replay path in `api.py`**

The replay normalization logic is currently inline in `api_log_entries()`. Extract it into a testable helper `parse_replay_entry(entry, cmd_defs)` that takes one JSONL dict and returns the normalized dict (or `None` if the entry is unparseable). The route handler becomes a loop that calls this helper.

Add this function before `api_log_entries()` in `mav_gss_lib/web_runtime/api.py`:

```python
def parse_replay_entry(entry: dict, cmd_defs: dict) -> dict | None:
    """Normalize one JSONL log entry for replay.

    Reads the stable platform envelope generically, then checks
    the mission block (Phase 9+) or legacy flat fields (pre-Phase 9)
    for mission-specific data.

    Returns a normalized dict, or None if the entry is invalid.
    """
    # Timestamp extraction
    ts = entry.get("gs_ts", "") or entry.get("ts", "")
    if "T" in ts and ts.index("T") == 10:
        ts_time = ts.split("T")[1][:8]
    elif " " in ts:
        ts_time = ts.split(" ")[1] if len(ts.split(" ")) > 1 else ""
    else:
        ts_time = ts[:8]

    raw_cmd = entry.get("cmd")
    mission_block = entry.get("mission", {})

    # RX vs TX: RX entries always have "pkt" (packet number)
    is_rx = "pkt" in entry

    # Extract cmd_id
    if is_rx:
        if mission_block and "cmd" in mission_block:
            cmd_id = mission_block["cmd"].get("cmd_id", "")
        elif isinstance(raw_cmd, dict):
            cmd_id = raw_cmd.get("cmd_id", "")
        else:
            cmd_id = ""
    else:
        cmd_id = str(raw_cmd) if isinstance(raw_cmd, str) else str(entry.get("cmd", ""))

    if is_rx:
        # Mission cmd: try mission block first, fall back to legacy flat
        mission_cmd = mission_block.get("cmd") if mission_block else None
        if mission_cmd is None:
            mission_cmd = raw_cmd if isinstance(raw_cmd, dict) else None

        normalized = {
            "num": entry.get("pkt", 0),
            "time": ts_time,
            "time_utc": ts,
            "frame": entry.get("frame_type", ""),
            "size": entry.get("raw_len", entry.get("payload_len", 0)),
            "is_dup": entry.get("duplicate", False),
            "is_echo": entry.get("uplink_echo", False),
            "is_unknown": entry.get("unknown", False),
            "raw_hex": entry.get("raw_hex", ""),
            "csp_header": (mission_block.get("csp_candidate") if mission_block else None) or entry.get("csp_candidate"),
            "cmd": mission_cmd.get("cmd_id", "") if mission_cmd else "",
            "src": node_name(mission_cmd.get("src", 0)) if mission_cmd else "",
            "dest": node_name(mission_cmd.get("dest", 0)) if mission_cmd else "",
            "echo": node_name(mission_cmd.get("echo", 0)) if mission_cmd else "",
            "ptype": ptype_name(mission_cmd.get("pkt_type", 0)) if mission_cmd else "",
            "crc16_ok": mission_cmd.get("crc_valid") if mission_cmd else None,
            "warnings": entry.get("warnings", []),
        }
        typed = mission_cmd.get("typed_args") if mission_cmd else None
        raw_args = mission_cmd.get("args", {}) if mission_cmd else {}
        log_extra = [str(arg) for arg in (mission_cmd.get("extra_args") or [])] if mission_cmd else []
        if typed and isinstance(typed, list):
            normalized["args_named"] = [
                {
                    "name": ta["name"],
                    "value": ta.get("value", b"").hex()
                    if isinstance(ta.get("value"), (bytes, bytearray))
                    else str(ta.get("value", "")),
                    "important": bool(ta.get("important")),
                }
                for ta in typed
            ]
            normalized["args_extra"] = [
                arg.hex() if isinstance(arg, (bytes, bytearray)) else str(arg)
                for arg in (mission_cmd.get("extra_args") or [])
            ]
        else:
            all_values = []
            if isinstance(raw_args, dict) and raw_args:
                all_values.extend([str(value) for value in raw_args.values()])
            elif isinstance(raw_args, list):
                all_values.extend([str(arg) for arg in raw_args])
            elif raw_args and not isinstance(raw_args, dict):
                all_values.append(str(raw_args))
            all_values.extend(log_extra)
            defn = cmd_defs.get(cmd_id.lower(), {})
            rx_defs = defn.get("rx_args", [])
            named = []
            for index, schema_arg in enumerate(rx_defs):
                if schema_arg.get("type") == "blob":
                    blob_val = " ".join(all_values[index:])
                    named.append({"name": schema_arg["name"], "value": blob_val, "important": bool(schema_arg.get("important"))})
                    all_values = all_values[:index]
                    break
                if index < len(all_values):
                    named.append({"name": schema_arg["name"], "value": all_values[index], "important": bool(schema_arg.get("important"))})
            normalized["args_named"] = named
            normalized["args_extra"] = all_values[len([arg for arg in rx_defs if arg.get("type") != "blob"]):]
        crc_status = (mission_block.get("csp_crc32") if mission_block else None) or entry.get("csp_crc32")
        if isinstance(crc_status, dict):
            normalized["crc32_ok"] = crc_status.get("valid")
    else:
        normalized = {
            "num": entry.get("n", 0),
            "time": ts_time,
            "time_utc": ts,
            "frame": entry.get("uplink_mode", ""),
            "size": entry.get("raw_len", entry.get("len", 0)),
            "is_dup": False,
            "is_echo": False,
            "is_unknown": False,
            "raw_hex": entry.get("raw_hex", ""),
            "csp_header": entry.get("csp"),
            "cmd": str(entry.get("cmd", "")),
            "src": str(entry.get("src_lbl", node_name(entry.get("src", 0)))),
            "dest": str(entry.get("dest_lbl", node_name(entry.get("dest", 0)))),
            "echo": str(entry.get("echo_lbl", node_name(entry.get("echo", 0)))),
            "ptype": str(entry.get("ptype_lbl", ptype_name(entry.get("ptype", 0)))),
            "args_named": [],
            "args_extra": [],
            "warnings": [],
        }

    return normalized
```

Then update `api_log_entries()` to call this helper instead of inlining the logic. The route handler becomes a loop that calls `parse_replay_entry(entry, runtime.cmd_defs)` for each entry, with the existing time/cmd filtering applied before or after. For TX entries that need `match_tx_args`/`tx_extra_args`, apply those after the helper returns (the helper returns empty `args_named`/`args_extra` for TX, which the route fills in from `runtime.tx`).

The previous "Replace the RX entry parsing section" and "Replace the cmd_id extraction" instructions are now superseded by this helper extraction. The route handler loop uses `parse_replay_entry()` and applies the existing time/cmd filters around it.

The `parse_replay_entry()` helper above handles both new-format and legacy entries, including RX vs TX discrimination via the `pkt` field. The `api_log_entries()` route handler should be refactored to use this helper in its loop, keeping the existing time/cmd filtering and adding TX-specific `args_named`/`args_extra` post-processing from `runtime.tx.match_tx_args()`/`runtime.tx.tx_extra_args()`.

- [ ] **Step 3: Run full test suite**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q
```

- [ ] **Step 4: Commit**

```bash
git add mav_gss_lib/web_runtime/api.py tests/test_ops_logging.py
git commit -m "Update replay path for platform envelope with legacy fallback"
```

---

## Task 7: Final Verification

- [ ] **Step 1: Run all test suites**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -v

cd "/Users/irfan/Documents/MAVERIC GSS"
python3 -m pytest tests/ -v
```

- [ ] **Step 2: Verify full startup**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -c "
import logging
logging.basicConfig(level=logging.INFO)
from mav_gss_lib.web_runtime.state import WebRuntime
rt = WebRuntime()
print('adapter:', type(rt.adapter).__name__)
# Verify new methods exist
print('build_log_mission_data:', hasattr(rt.adapter, 'build_log_mission_data'))
print('format_log_lines:', hasattr(rt.adapter, 'format_log_lines'))
print('is_unknown_packet:', hasattr(rt.adapter, 'is_unknown_packet'))
print('OK')
" 2>&1
```

- [ ] **Step 3: Verify frontend still builds**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE/mav_gss_lib/web"
npm run build
```

- [ ] **Step 4: Verify echo mission still works end-to-end**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -c "
from mav_gss_lib.parsing import RxPipeline, build_rx_log_record
from tests.echo_mission import EchoMissionAdapter

adapter = EchoMissionAdapter(cmd_defs={})
pipeline = RxPipeline(adapter, tx_freq_map={})
pkt = pipeline.process({'transmitter': 'test'}, b'\x01\x02\x03\x04')
print('is_unknown:', pkt.is_unknown)
print('unknown_num:', pkt.unknown_num)

record = build_rx_log_record(pkt, '1.0.0', {'transmitter': 'test'}, adapter)
print('has mission block:', 'mission' in record)
print('has protocol_blocks:', 'protocol_blocks' in record)
print('has integrity_blocks:', 'integrity_blocks' in record)
print('no flat cmd:', 'cmd' not in record)
print('no flat csp_candidate:', 'csp_candidate' not in record)

lines = adapter.format_log_lines(pkt)
print('format_log_lines:', lines)
print('OK')
"
```

Expected: `is_unknown: True`, `has mission block: False` (echo returns `{}`), no flat MAVERIC fields.

---

## Post-Phase 9 State

**What was added:**
- 3 new methods on `MissionAdapter` Protocol: `build_log_mission_data()`, `format_log_lines()`, `is_unknown_packet()`
- Platform log envelope with `protocol_blocks`, `integrity_blocks`, and adapter-provided `mission` block
- Backward-compatible replay for pre-Phase-9 MAVERIC logs

**What changed:**
- `build_rx_log_record()` — now takes adapter param, produces platform envelope + mission block instead of flat MAVERIC fields
- `SessionLog.write_packet()` — now takes adapter param, delegates mission-specific text to adapter
- `_classify_unknown()` — now delegates to `adapter.is_unknown_packet()`
- Replay path — reads `mission` block first, falls back to legacy flat fields

**What did NOT change:**
- TX logging (`TXLog.write_command()`) — already receives decomposed params
- Frontend — no changes
- `packet_to_json()` transitional method — still exists (Phase 11 removal candidate)
- `ParsedPacket` transitional fields (`csp`, `cmd`, `cmd_tail`, `ts_result`) — still exist and still flow from `ParsedPacket` through `Packet` to the adapter. Platform-core no longer *formats* them for logging or classification — that responsibility moved to the adapter — but the runtime path still carries them from parse to adapter call. Removing the fields entirely is a later-phase concern.
- `SessionLog.write_packet()` — `adapter` param defaults to `None` for backward compatibility. Legacy callers (`backup_control/MAV_RX.py`) continue to work without adapter, producing platform-only text output (separator, warnings, hex, ASCII) with no mission-specific lines.

**MAVERIC-specific code that moved from platform-core to adapter:**
- CSP header JSONL serialization
- Command dict JSONL serialization
- Satellite timestamp JSONL serialization
- CRC status JSONL serialization
- AX.25/CSP/command text formatting
- CRC text formatting
- `cmd is None → unknown` classification
