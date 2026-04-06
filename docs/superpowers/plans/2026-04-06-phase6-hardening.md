# Phase 6: Hardening

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the adapter boundary with startup validation, runtime mission reporting, and a fake second mission test fixture that proves the adapter/pipeline layer is mission-agnostic.

**Architecture:** Add a `validate_adapter()` function that checks structural interface presence and `ADAPTER_API_VERSION` at startup. Add active mission name to the API status endpoint and startup log. Create a minimal `EchoMission` test fixture that satisfies `MissionAdapter` with trivial implementations — no real protocol parsing, just enough to prove a non-MAVERIC adapter can pass through `RxPipeline` and produce valid rendering output. Scope: this phase hardens the current adapter seam. Generic runtime mission loading (replacing the hardcoded MAVERIC path in `WebRuntime` and `parsing.py`) is a future step beyond the v1 migration.

**Tech Stack:** Python 3.10+, pytest, dataclasses

---

## Design Decisions

1. **Validation is a function, not a base class.** `validate_adapter(adapter, version)` checks structural interface presence (method names via `@runtime_checkable` Protocol) and API version. This is capability validation, not full signature conformance — Python's runtime Protocol check only verifies attribute presence, not argument types. Still valuable as a startup guard against missing methods.

2. **The echo mission is a test fixture, not a real mission package.** It lives in `tests/`, not in `mav_gss_lib/missions/`. It proves the platform boundary works without pretending to be a deployable mission.

3. **`ADAPTER_API_VERSION` is checked, not enforced via import.** The platform reads `ADAPTER_API_VERSION` from the mission package's `__init__.py` and rejects unsupported versions at startup. This is simpler than import-time metaclass enforcement.

4. **Active mission name comes from config, not the adapter.** `general.mission_name` (existing config key) is already used in the UI header. Phase 6 ensures it's also in the API status response and startup log output.

## File Plan

| Action | File | Change |
|---|---|---|
| Modify | `mav_gss_lib/mission_adapter.py` | Add `validate_adapter()` function |
| Modify | `mav_gss_lib/web_runtime/state.py` | Call `validate_adapter()` at startup, log active mission |
| Modify | `mav_gss_lib/web_runtime/api.py` | Add `mission` field to `/api/status` response |
| Create | `tests/echo_mission.py` | Fake echo mission test fixture |
| Create | `tests/test_ops_mission_boundary.py` | Tests: echo mission loads, renders, passes through platform |

## Test Commands

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -v
```

---

## Task 1: Add `validate_adapter()` to Platform Core

**Files:**
- Modify: `mav_gss_lib/mission_adapter.py`

- [ ] **Step 1: Add the validation function**

Add this function after the `MissionAdapter` Protocol class, before the facade re-export section:

```python
# =============================================================================
#  PLATFORM CORE -- Adapter Validation
# =============================================================================

SUPPORTED_API_VERSIONS = {1}


def validate_adapter(adapter, api_version: int, mission_name: str) -> None:
    """Check that a mission adapter has the required methods and API version.

    Uses @runtime_checkable Protocol for structural interface presence
    (method names only, not signatures). Raises ValueError if validation fails.
    Called once at startup before the adapter is used.
    """
    if not isinstance(adapter, MissionAdapter):
        missing = []
        for method_name in (
            'detect_frame_type', 'normalize_frame', 'parse_packet',
            'duplicate_fingerprint', 'is_uplink_echo',
            'build_raw_command', 'validate_tx_args',
            'packet_list_columns', 'packet_list_row',
            'packet_detail_blocks', 'protocol_blocks', 'integrity_blocks',
        ):
            if not hasattr(adapter, method_name):
                missing.append(method_name)
        raise ValueError(
            f"Mission '{mission_name}' adapter {type(adapter).__name__} "
            f"does not satisfy MissionAdapter protocol. "
            f"Missing methods: {', '.join(missing) if missing else 'signature mismatch'}"
        )
    if api_version not in SUPPORTED_API_VERSIONS:
        raise ValueError(
            f"Mission '{mission_name}' declares ADAPTER_API_VERSION={api_version}, "
            f"but this platform supports: {sorted(SUPPORTED_API_VERSIONS)}"
        )
```

- [ ] **Step 2: Verify it works**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -c "
from mav_gss_lib.mission_adapter import validate_adapter, MavericMissionAdapter
from mav_gss_lib.missions.maveric.wire_format import init_nodes
cfg = {'nodes': {0: 'NONE', 6: 'GS'}, 'ptypes': {1: 'CMD'}, 'general': {'gs_node': 'GS'}}
init_nodes(cfg)
adapter = MavericMissionAdapter(cmd_defs={})
validate_adapter(adapter, 1, 'maveric')
print('MAVERIC adapter: valid')

# Test rejection of bad version
try:
    validate_adapter(adapter, 99, 'maveric')
    print('ERROR: should have raised')
except ValueError as e:
    print('Bad version rejected:', e)

# Test rejection of non-adapter
try:
    validate_adapter(object(), 1, 'fake')
    print('ERROR: should have raised')
except ValueError as e:
    print('Non-adapter rejected:', e)

print('OK')
"
```

- [ ] **Step 3: Run tests**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q
```

- [ ] **Step 4: Commit**

```bash
git add mav_gss_lib/mission_adapter.py
git commit -m "Add validate_adapter() for mission startup validation"
```

---

## Task 2: Validate Adapter at Startup and Log Active Mission

**Files:**
- Modify: `mav_gss_lib/web_runtime/state.py`

- [ ] **Step 1: Add validation call to `_load_adapter`**

Update the import at the top:

```python
from mav_gss_lib.mission_adapter import MavericMissionAdapter, validate_adapter
```

Update `_load_adapter` to validate after construction:

```python
    def _load_adapter(self):
        """Instantiate and validate the mission adapter based on config."""
        import logging
        mission = self.cfg.get("general", {}).get("mission", "maveric")
        mission_name = self.cfg.get("general", {}).get("mission_name", mission.upper())
        if mission == "maveric":
            from mav_gss_lib.missions.maveric import ADAPTER_API_VERSION
            adapter = MavericMissionAdapter(self.cmd_defs)
            validate_adapter(adapter, ADAPTER_API_VERSION, mission_name)
            logging.info("Mission loaded: %s (adapter API v%d)", mission_name, ADAPTER_API_VERSION)
            return adapter
        raise ValueError(
            f"Unknown mission '{mission}' in general.mission config. "
            f"Supported: maveric"
        )
```

- [ ] **Step 2: Verify startup log**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -c "
import logging
logging.basicConfig(level=logging.INFO)
from mav_gss_lib.web_runtime.state import WebRuntime
rt = WebRuntime()
print('adapter:', type(rt.adapter).__name__)
print('OK')
" 2>&1 | grep -E "Mission loaded|adapter:|OK"
```

Expected: `Mission loaded: MAVERIC (adapter API v1)`, `adapter: MavericMissionAdapter`, `OK`

- [ ] **Step 3: Run tests**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q
```

- [ ] **Step 4: Commit**

```bash
git add mav_gss_lib/web_runtime/state.py
git commit -m "Validate adapter at startup and log active mission"
```

---

## Task 3: Add Active Mission to API Status

**Files:**
- Modify: `mav_gss_lib/web_runtime/api.py`

- [ ] **Step 1: Read the current `api_status` handler**

Read `mav_gss_lib/web_runtime/api.py` and find the `api_status()` route handler. It returns a dict with version, ZMQ status, etc.

- [ ] **Step 2: Add `mission` field**

Add `"mission"` to the response dict returned by `api_status()`:

```python
    "mission": runtime.cfg.get("general", {}).get("mission", "maveric"),
```

This goes alongside the existing `"mission_name"` field (which is the display name). `"mission"` is the config key used for adapter selection.

- [ ] **Step 3: Run tests**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q
```

- [ ] **Step 4: Commit**

```bash
git add mav_gss_lib/web_runtime/api.py
git commit -m "Add active mission identifier to /api/status"
```

---

## Task 4: Create Echo Mission Test Fixture

**Files:**
- Create: `tests/echo_mission.py`

- [ ] **Step 1: Create the echo mission adapter**

This is a minimal mission that satisfies `MissionAdapter` with trivial implementations. It does not parse any real protocol — it just echoes raw data through the rendering pipeline.

```python
"""Fake echo mission for testing the mission-agnostic platform boundary.

This is NOT a real mission. It proves that:
  1. A non-MAVERIC adapter can be instantiated
  2. It satisfies the MissionAdapter Protocol
  3. It produces valid rendering data
  4. The platform can load, render, and exercise it
"""

from __future__ import annotations

from dataclasses import dataclass

ADAPTER_API_VERSION = 1


@dataclass
class EchoMissionAdapter:
    """Minimal mission adapter that echoes raw bytes without protocol parsing."""

    cmd_defs: dict

    def detect_frame_type(self, meta: dict) -> str:
        return "RAW"

    def normalize_frame(self, frame_type: str, raw: bytes):
        return raw, None, []

    def parse_packet(self, inner_payload: bytes, warnings=None):
        from mav_gss_lib.mission_adapter import ParsedPacket
        return ParsedPacket(warnings=warnings or [])

    def duplicate_fingerprint(self, parsed) -> tuple | None:
        return None

    def is_uplink_echo(self, cmd) -> bool:
        return False

    def build_raw_command(self, src, dest, echo, ptype, cmd_id, args):
        return f"{cmd_id} {args}".encode("ascii")

    def validate_tx_args(self, cmd_id, args):
        return True, []

    # -- Rendering-slot contract --

    def packet_list_columns(self) -> list[dict]:
        return [
            {"id": "num",  "label": "#",     "align": "right", "width": "w-10"},
            {"id": "time", "label": "time",  "width": "w-[72px]"},
            {"id": "size", "label": "size",  "align": "right", "width": "w-12"},
            {"id": "hex",  "label": "hex",   "flex": True},
        ]

    def packet_list_row(self, pkt) -> dict:
        return {
            "values": {
                "num": pkt.pkt_num,
                "time": pkt.gs_ts_short,
                "size": len(pkt.raw),
                "hex": pkt.raw.hex(),
            },
            "_meta": {},
        }

    def packet_detail_blocks(self, pkt) -> list[dict]:
        return [
            {"kind": "raw", "label": "Echo Data", "fields": [
                {"name": "Size", "value": str(len(pkt.raw))},
                {"name": "Hex", "value": pkt.raw.hex()},
            ]},
        ]

    def protocol_blocks(self, pkt) -> list:
        return []

    def integrity_blocks(self, pkt) -> list:
        return []

    # -- Transitional compatibility (Phase 5a) --

    def packet_to_json(self, pkt) -> dict:
        return {
            "num": pkt.pkt_num,
            "time": pkt.gs_ts_short,
            "time_utc": pkt.gs_ts,
            "frame": "RAW",
            "src": "", "dest": "", "echo": "", "ptype": "",
            "cmd": "", "args_named": [], "args_extra": [],
            "size": len(pkt.raw),
            "crc16_ok": None, "crc32_ok": None,
            "is_echo": False, "is_dup": pkt.is_dup,
            "is_unknown": True,
            "raw_hex": pkt.raw.hex(),
            "warnings": pkt.warnings,
            "csp_header": None, "ax25_header": None,
            "_rendering": {
                "row": self.packet_list_row(pkt),
                "detail_blocks": self.packet_detail_blocks(pkt),
                "protocol_blocks": [],
                "integrity_blocks": [],
            },
        }

    def queue_item_to_json(self, item, match_tx_args, extra_tx_args):
        return {
            "type": "cmd",
            "num": item.get("num", 0),
            "src": "", "dest": "", "echo": "", "ptype": "",
            "cmd": item.get("cmd", ""),
            "args": item.get("args", ""),
            "args_named": [], "args_extra": [],
            "guard": item.get("guard", False),
            "size": len(item.get("raw_cmd", b"")),
        }

    def history_entry(self, count, item, payload_len):
        from datetime import datetime
        return {
            "n": count,
            "ts": datetime.now().strftime("%H:%M:%S"),
            "src": "", "dest": "", "echo": "", "ptype": "",
            "cmd": item.get("cmd", ""),
            "args": item.get("args", ""),
            "size": payload_len,
        }
```

- [ ] **Step 2: Verify it satisfies MissionAdapter**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -c "
from tests.echo_mission import EchoMissionAdapter, ADAPTER_API_VERSION
from mav_gss_lib.mission_adapter import MissionAdapter, validate_adapter
adapter = EchoMissionAdapter(cmd_defs={})
print('isinstance:', isinstance(adapter, MissionAdapter))
validate_adapter(adapter, ADAPTER_API_VERSION, 'echo')
print('validate_adapter: passed')
print('columns:', adapter.packet_list_columns())
print('OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add tests/echo_mission.py
git commit -m "Add echo mission test fixture for platform boundary testing"
```

---

## Task 5: Write Mission Boundary Tests

**Files:**
- Create: `tests/test_ops_mission_boundary.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests that the platform boundary works with a non-MAVERIC mission.

These tests prove:
  1. EchoMissionAdapter satisfies MissionAdapter Protocol
  2. validate_adapter() accepts it
  3. RxPipeline processes packets through the echo adapter
  4. Rendering-slot methods produce valid output
  5. The transitional JSON methods produce valid output
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.mission_adapter import (
    MissionAdapter,
    ParsedPacket,
    validate_adapter,
)
from mav_gss_lib.parsing import RxPipeline
from tests.echo_mission import EchoMissionAdapter, ADAPTER_API_VERSION


class TestMissionBoundary(unittest.TestCase):
    """Verify the platform works with a non-MAVERIC mission adapter."""

    def setUp(self):
        self.adapter = EchoMissionAdapter(cmd_defs={})

    def test_echo_adapter_satisfies_protocol(self):
        """EchoMissionAdapter passes isinstance check against MissionAdapter."""
        self.assertIsInstance(self.adapter, MissionAdapter)

    def test_validate_adapter_accepts_echo(self):
        """validate_adapter() does not raise for a conforming echo adapter."""
        validate_adapter(self.adapter, ADAPTER_API_VERSION, "echo")

    def test_validate_adapter_rejects_bad_version(self):
        """validate_adapter() raises ValueError for unsupported API version."""
        with self.assertRaises(ValueError) as ctx:
            validate_adapter(self.adapter, 99, "echo")
        self.assertIn("ADAPTER_API_VERSION=99", str(ctx.exception))

    def test_validate_adapter_rejects_non_adapter(self):
        """validate_adapter() raises ValueError for an object missing methods."""
        with self.assertRaises(ValueError) as ctx:
            validate_adapter(object(), 1, "fake")
        self.assertIn("does not satisfy", str(ctx.exception))

    def test_echo_adapter_renders_columns(self):
        """packet_list_columns() returns a non-empty list of column defs."""
        cols = self.adapter.packet_list_columns()
        self.assertGreater(len(cols), 0)
        ids = [c["id"] for c in cols]
        self.assertIn("num", ids)
        self.assertIn("size", ids)

    def test_echo_adapter_renders_row(self):
        """packet_list_row() returns values keyed by column IDs."""
        from tests.echo_mission import EchoMissionAdapter

        class MockPkt:
            pkt_num = 1
            gs_ts_short = "10:30:00"
            gs_ts = "2026-04-06T10:30:00"
            raw = b"\xDE\xAD\xBE\xEF"
            is_dup = False
            is_unknown = True
            is_uplink_echo = False
            warnings = []

        row = self.adapter.packet_list_row(MockPkt())
        self.assertIn("values", row)
        self.assertEqual(row["values"]["num"], 1)
        self.assertEqual(row["values"]["size"], 4)
        self.assertEqual(row["values"]["hex"], "deadbeef")

    def test_echo_adapter_renders_detail_blocks(self):
        """packet_detail_blocks() returns at least one block with fields."""

        class MockPkt:
            pkt_num = 1
            gs_ts_short = "10:30:00"
            gs_ts = "2026-04-06T10:30:00"
            raw = b"\xCA\xFE"
            is_dup = False
            is_unknown = True
            is_uplink_echo = False
            warnings = []

        blocks = self.adapter.packet_detail_blocks(MockPkt())
        self.assertGreater(len(blocks), 0)
        self.assertEqual(blocks[0]["kind"], "raw")
        self.assertIn("fields", blocks[0])

    def test_echo_adapter_no_protocol_or_integrity_blocks(self):
        """Echo mission has no protocol/integrity — returns empty lists."""

        class MockPkt:
            pkt_num = 1
            gs_ts_short = "10:30:00"
            raw = b"\x00"
            is_dup = False
            is_unknown = True
            is_uplink_echo = False
            warnings = []
            csp = None
            stripped_hdr = None
            crc_status = {}
            cmd = None

        self.assertEqual(self.adapter.protocol_blocks(MockPkt()), [])
        self.assertEqual(self.adapter.integrity_blocks(MockPkt()), [])

    def test_rx_pipeline_with_echo_adapter(self):
        """RxPipeline processes a raw PDU through the echo adapter."""
        pipeline = RxPipeline(self.adapter, tx_freq_map={})
        meta = {"transmitter": "raw test"}
        raw = b"\x01\x02\x03\x04"
        pkt = pipeline.process(meta, raw)
        self.assertEqual(pkt.pkt_num, 1)
        self.assertEqual(pkt.raw, raw)
        self.assertEqual(pkt.frame_type, "RAW")

    def test_echo_packet_to_json(self):
        """Transitional packet_to_json() produces valid JSON shape."""

        class MockPkt:
            pkt_num = 1
            gs_ts_short = "10:30:00"
            gs_ts = "2026-04-06T10:30:00"
            frame_type = "RAW"
            raw = b"\xAB\xCD"
            is_dup = False
            is_unknown = True
            is_uplink_echo = False
            warnings = []
            csp = None
            stripped_hdr = None
            crc_status = {}
            cmd = None
            ts_result = None

        result = self.adapter.packet_to_json(MockPkt())
        self.assertEqual(result["num"], 1)
        self.assertEqual(result["frame"], "RAW")
        self.assertEqual(result["raw_hex"], "abcd")
        self.assertIn("_rendering", result)
        self.assertIn("row", result["_rendering"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new tests**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/test_ops_mission_boundary.py -v
```

Expected: All tests pass.

- [ ] **Step 3: Run the full test suite**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -v

cd "/Users/irfan/Documents/MAVERIC GSS"
python3 -m pytest tests/ -v
```

Expected: All existing tests still pass + new mission boundary tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_ops_mission_boundary.py
git commit -m "Add mission boundary tests with echo mission fixture"
```

---

## Task 6: Final Verification

- [ ] **Step 1: Verify all acceptance criteria**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -c "
# Acceptance criteria check
print('1. MAVERIC is a mission implementation:')
import mav_gss_lib.missions.maveric
print('   Located at:', mav_gss_lib.missions.maveric.__file__)
print('   ADAPTER_API_VERSION:', mav_gss_lib.missions.maveric.ADAPTER_API_VERSION)

print()
print('2. Core owns transport, protocol-family, workflow shell, UI shell:')
import mav_gss_lib.protocols
import mav_gss_lib.transport
print('   protocols/ exists:', bool(mav_gss_lib.protocols.__file__))
print('   transport exists:', bool(mav_gss_lib.transport.__file__))

print()
print('3. Missions own parsing, semantics, columns, detail:')
from mav_gss_lib.missions.maveric.adapter import MavericMissionAdapter
adapter = MavericMissionAdapter(cmd_defs={})
print('   columns:', len(adapter.packet_list_columns()), 'defined')
print('   Has packet_detail_blocks:', hasattr(adapter, 'packet_detail_blocks'))

print()
print('4. Protocol/integrity rendered through standard contracts:')
from mav_gss_lib.mission_adapter import ProtocolBlock, IntegrityBlock
print('   ProtocolBlock:', ProtocolBlock.__name__)
print('   IntegrityBlock:', IntegrityBlock.__name__)

print()
print('5. Core transitional state:')
print('   ParsedPacket has transitional MAVERIC-shaped fields (marked, accepted for v1)')
print('   MissionAdapter Protocol methods are mission-agnostic')

print()
print('6. Non-MAVERIC test mission exists:')
from tests.echo_mission import EchoMissionAdapter
from mav_gss_lib.mission_adapter import MissionAdapter, validate_adapter
echo = EchoMissionAdapter(cmd_defs={})
validate_adapter(echo, 1, 'echo')
print('   EchoMissionAdapter satisfies MissionAdapter:', isinstance(echo, MissionAdapter))

print()
print('ALL ACCEPTANCE CRITERIA MET')
"
```

- [ ] **Step 2: Run complete test suite**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -v

cd "/Users/irfan/Documents/MAVERIC GSS"
python3 -m pytest tests/ -v
```

- [ ] **Step 3: Commit**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
git add -A
git commit -m "Phase 6 complete: mission boundary hardened with validation and echo test fixture"
```

---

## Post-Phase 6 State

**What was added:**
- `validate_adapter()` in platform core — checks structural interface presence + API version
- Startup validation and mission logging in `WebRuntime._load_adapter()`
- Active `mission` field in `/api/status` response
- `EchoMissionAdapter` test fixture — minimal non-MAVERIC mission
- 9 mission boundary tests proving the platform is mission-agnostic

**Migration acceptance criteria status:**
1. MAVERIC is a mission implementation under `missions/maveric/`, not the platform identity ✓
2. Core owns transport (`transport.py`), protocol-family support (`protocols/`), workflow shell, and UI shell ✓
3. Missions own parsing, command semantics, columns, and semantic detail content ✓
4. Protocol and integrity sections are rendered through `ProtocolBlock`/`IntegrityBlock` contracts ✓
5. Core still has transitional MAVERIC-shaped fields in `ParsedPacket` and MAVERIC-aware classification in `parsing.py` — these are explicitly marked transitional and do not block v1 acceptance, but are not yet fully generic ⚠
6. A non-MAVERIC test mission (echo) exists and passes through the adapter/pipeline boundary at the adapter and `RxPipeline` level. Generic runtime mission loading (replacing the hardcoded MAVERIC path in `WebRuntime`) is a post-v1 step ✓
