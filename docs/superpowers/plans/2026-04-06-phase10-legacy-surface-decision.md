# Phase 10: Legacy Surface Decision

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Explicitly classify every legacy surface as platform-core, MAVERIC-only legacy, or deprecated, and document those decisions in code so future maintainers never wonder what's what.

**Architecture:** This is a documentation-and-cleanup phase, not a feature phase. Each legacy surface gets a status annotation in its module docstring. Deprecated internal compatibility wrappers (`parse_command`, `verify_crc`) are removed — these were test-only shims, not part of any supported API. No user-facing UI or runtime behavior changes.

**Tech Stack:** Python 3.10+, pytest

---

## Design Decisions

1. **TUI is frozen as MAVERIC-only legacy.** Phase 4 already made this decision. The TUI (`tui_rx.py`, `tui_tx.py`, `tui_common.py`) and backup entry points (`backup_control/MAV_RX.py`, `backup_control/MAV_TX.py`) are explicitly MAVERIC-only tooling. They will not be migrated to the platform/adapter architecture. They may be removed in a future version when the web UI is the sole operational path.

2. **Facades are retained with explicit Phase 11 removal notes.** `protocol.py` and `imaging.py` are compatibility facades. They stay for now because TUI and external tests import from them. Phase 11 will evaluate removal after facade consumers are updated.

3. **Deprecated compatibility wrappers are removed.** `MavericMissionAdapter.parse_command()` and `verify_crc()` are backward-compat wrappers used only by tests. The tests are updated to use `parse_packet()` directly, and the wrappers are deleted.

4. **Transitional adapter methods are documented as Phase 11 removal candidates.** `packet_to_json()`, `queue_item_to_json()`, and `history_entry()` are still in active use by the web runtime. They get explicit "Phase 11 removal candidate" docstring annotations.

5. **Dict-style Packet access is documented as TUI-only compat.** `Packet.get()` and `Packet.__getitem__()` exist only for TUI backward compatibility. They get explicit docstring annotations.

## File Plan

| Action | File | Change |
|---|---|---|
| Modify | `mav_gss_lib/tui_rx.py` | Add legacy status to docstring |
| Modify | `mav_gss_lib/tui_tx.py` | Add legacy status to docstring |
| Modify | `mav_gss_lib/tui_common.py` | Add legacy status to docstring |
| Modify | `backup_control/MAV_RX.py` | Add legacy status to docstring |
| Modify | `backup_control/MAV_TX.py` | Add legacy status to docstring |
| Modify | `mav_gss_lib/protocol.py` | Add Phase 11 removal note to docstring |
| Modify | `mav_gss_lib/imaging.py` | Add Phase 11 removal note to docstring |
| Modify | `mav_gss_lib/missions/maveric/adapter.py` | Remove `parse_command()` and `verify_crc()`; annotate transitional methods |
| Modify | `mav_gss_lib/parsing.py` | Annotate dict-compat methods on Packet |
| Modify | `tests/test_ops_protocol_core.py` | Update tests to use `parse_packet()` directly |

## Test Commands

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -v
```

---

## Task 1: Document TUI and Backup Entry Points as Legacy

**Files:**
- Modify: `mav_gss_lib/tui_rx.py`
- Modify: `mav_gss_lib/tui_tx.py`
- Modify: `mav_gss_lib/tui_common.py`
- Modify: `backup_control/MAV_RX.py`
- Modify: `backup_control/MAV_TX.py`

- [ ] **Step 1: Update `tui_rx.py` docstring**

Replace the module docstring:

```python
"""
mav_gss_lib.tui_rx -- RX Monitor Widgets (Textual)

Author:  Irfan Annuar - USC ISI SERC
"""
```

with:

```python
"""
mav_gss_lib.tui_rx -- RX Monitor Widgets (Textual)

STATUS: MAVERIC-only legacy. This module is part of the backup Textual TUI
and is not on the platform/adapter migration path. It accesses Packet fields
directly via dict-compat methods (pkt.get(), pkt[key]) and imports from the
protocol.py compatibility facade. The web UI (MAV_WEB.py) is the primary
operational interface.

Author:  Irfan Annuar - USC ISI SERC
"""
```

- [ ] **Step 2: Update `tui_tx.py` docstring**

Replace the module docstring:

```python
"""
mav_gss_lib.tui_tx -- TX Dashboard Widgets (Textual)

Author:  Irfan Annuar - USC ISI SERC
"""
```

with:

```python
"""
mav_gss_lib.tui_tx -- TX Dashboard Widgets (Textual)

STATUS: MAVERIC-only legacy. This module is part of the backup Textual TUI
and is not on the platform/adapter migration path. The web UI (MAV_WEB.py)
is the primary operational interface.

Author:  Irfan Annuar - USC ISI SERC
"""
```

- [ ] **Step 3: Update `tui_common.py` docstring**

Replace the module docstring:

```python
"""
mav_gss_lib.tui_common -- Shared Textual TUI Utilities

Author:  Irfan Annuar - USC ISI SERC
"""
```

with:

```python
"""
mav_gss_lib.tui_common -- Shared Textual TUI Utilities

STATUS: MAVERIC-only legacy. Shared widgets and helpers for the backup
Textual TUI (tui_rx.py, tui_tx.py). Not on the platform/adapter migration
path. The web UI (MAV_WEB.py) is the primary operational interface.

Author:  Irfan Annuar - USC ISI SERC
"""
```

- [ ] **Step 4: Update `backup_control/MAV_RX.py` docstring**

Replace the module docstring:

```python
"""
MAV_RX -- MAVERIC Ground Station Monitor (Textual Dashboard)

Author:  Irfan Annuar - USC ISI SERC
"""
```

with:

```python
"""
MAV_RX -- MAVERIC Ground Station Monitor (Textual Dashboard)

STATUS: MAVERIC-only legacy. Backup Textual TUI for RX monitoring.
Not on the platform/adapter migration path. The web UI (MAV_WEB.py)
is the primary operational interface.

Author:  Irfan Annuar - USC ISI SERC
"""
```

- [ ] **Step 5: Update `backup_control/MAV_TX.py` docstring**

Replace the module docstring:

```python
"""
MAV_TX -- MAVERIC Command Terminal (Textual Dashboard)

Author:  Irfan Annuar - USC ISI SERC
"""
```

with:

```python
"""
MAV_TX -- MAVERIC Command Terminal (Textual Dashboard)

STATUS: MAVERIC-only legacy. Backup Textual TUI for TX commanding.
Not on the platform/adapter migration path. The web UI (MAV_WEB.py)
is the primary operational interface.

Author:  Irfan Annuar - USC ISI SERC
"""
```

- [ ] **Step 6: Run tests**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q
```

- [ ] **Step 7: Commit**

```bash
git add mav_gss_lib/tui_rx.py mav_gss_lib/tui_tx.py mav_gss_lib/tui_common.py backup_control/MAV_RX.py backup_control/MAV_TX.py
git commit -m "Document TUI and backup entry points as MAVERIC-only legacy"
```

---

## Task 2: Document Facade Modules and Annotate Transitional Code

**Files:**
- Modify: `mav_gss_lib/protocol.py`
- Modify: `mav_gss_lib/imaging.py`
- Modify: `mav_gss_lib/parsing.py`
- Modify: `mav_gss_lib/missions/maveric/adapter.py`

- [ ] **Step 1: Update `protocol.py` docstring**

Replace the module docstring:

```python
"""
mav_gss_lib.protocol -- Compatibility Facade

Re-exports from:
  - mav_gss_lib.protocols.*          (CRC, CSP, KISS, AX.25, frame detect)
  - mav_gss_lib.missions.maveric.*   (node tables, command wire format, schema)

New code should import directly from the canonical locations.

Author:  Irfan Annuar - USC ISI SERC
"""
```

with:

```python
"""
mav_gss_lib.protocol -- Compatibility Facade

STATUS: Phase 11 removal candidate. Re-exports from canonical locations
for backward compatibility with TUI modules, backup_control/, external
tests, and logging.py. New code should import directly from:
  - mav_gss_lib.protocols.*          (CRC, CSP, KISS, AX.25, frame detect)
  - mav_gss_lib.missions.maveric.*   (node tables, command wire format, schema)

Author:  Irfan Annuar - USC ISI SERC
"""
```

- [ ] **Step 2: Update `imaging.py` docstring**

Replace the module docstring:

```python
"""
mav_gss_lib.imaging -- Compatibility facade

Canonical location: mav_gss_lib.missions.maveric.imaging
This module re-exports ImageAssembler for backward compatibility.
"""
```

with:

```python
"""
mav_gss_lib.imaging -- Compatibility facade

STATUS: Phase 11 removal candidate. Canonical location is
mav_gss_lib.missions.maveric.imaging. Re-exports ImageAssembler for
backward compatibility with MAV_IMG.py and backup_control/.
"""
```

- [ ] **Step 3: Annotate dict-compat methods on Packet in `parsing.py`**

Replace the two dict-compat methods:

```python
    def get(self, key, default=None):
        """Dict-style access for backward compatibility during migration."""
        return getattr(self, key, default)

    def __getitem__(self, key):
        """Dict-style access for backward compatibility during migration."""
        return getattr(self, key)
```

with:

```python
    def get(self, key, default=None):
        """Dict-style access — TUI-only backward compat (Phase 11 removal candidate)."""
        return getattr(self, key, default)

    def __getitem__(self, key):
        """Dict-style access — TUI-only backward compat (Phase 11 removal candidate)."""
        return getattr(self, key)
```

- [ ] **Step 4: Annotate transitional adapter methods in `adapter.py`**

Update the docstrings for the three transitional methods on `MavericMissionAdapter`.

For `packet_to_json`:
```python
    def packet_to_json(self, pkt) -> dict:
        """Transitional: convert Packet to the JSON shape the current frontend expects.

        STATUS: Phase 11 removal candidate. Will be replaced when the frontend
        consumes rendering-slot data exclusively and the flat JSON shape is retired.
        """
```

For `queue_item_to_json`:
```python
    def queue_item_to_json(self, item: dict, match_tx_args, extra_tx_args) -> dict:
        """Transitional: convert TX queue item to the JSON shape the current frontend expects.

        STATUS: Phase 11 removal candidate.
        """
```

For `history_entry`:
```python
    def history_entry(self, count: int, item: dict, payload_len: int) -> dict:
        """Transitional: build sent-command history entry for the current frontend.

        STATUS: Phase 11 removal candidate.
        """
```

- [ ] **Step 5: Run tests**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add mav_gss_lib/protocol.py mav_gss_lib/imaging.py mav_gss_lib/parsing.py mav_gss_lib/missions/maveric/adapter.py
git commit -m "Annotate facades and transitional code with legacy status"
```

---

## Task 3: Remove Deprecated Compatibility Wrappers

**Files:**
- Modify: `mav_gss_lib/missions/maveric/adapter.py`
- Modify: `tests/test_ops_protocol_core.py`

- [ ] **Step 1: Update tests to use `parse_packet()` directly**

In `tests/test_ops_protocol_core.py`, the tests `test_adapter_normalizes_ax25_and_parses_schema_matched_command` and `test_adapter_crc_and_uplink_echo_behavior` use the deprecated `parse_command()` and `verify_crc()` wrappers.

Find the test method `test_adapter_normalizes_ax25_and_parses_schema_matched_command`. Replace this line:

```python
        cmd, tail, ts_result = self.adapter.parse_command(inner)
```

with:

```python
        parsed = self.adapter.parse_packet(inner)
        cmd, tail, ts_result = parsed.cmd, parsed.cmd_tail, parsed.ts_result
```

Find the test method `test_adapter_crc_and_uplink_echo_behavior`. Replace these lines:

```python
        cmd, _tail, _ts = self.adapter.parse_command(inner)
        warnings = []
        clean = self.adapter.verify_crc(cmd, inner, warnings)
```

with:

```python
        parsed = self.adapter.parse_packet(inner)
        cmd = parsed.cmd
        clean = parsed.crc_status
```

And further down in the same test, replace:

```python
        bad = self.adapter.verify_crc(cmd, bytes(corrupted), warnings)
```

with:

```python
        warnings = []
        bad_parsed = self.adapter.parse_packet(bytes(corrupted), warnings)
        bad = bad_parsed.crc_status
```

- [ ] **Step 2: Run tests to verify the updated tests pass**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/test_ops_protocol_core.py -v
```

- [ ] **Step 3: Remove deprecated wrappers from `adapter.py`**

Delete the `parse_command()` and `verify_crc()` methods from `MavericMissionAdapter` in `mav_gss_lib/missions/maveric/adapter.py`:

```python
    def parse_command(self, inner_payload: bytes):
        """Backward-compatible wrapper around parse_packet()."""
        parsed = self.parse_packet(inner_payload)
        return parsed.cmd, parsed.cmd_tail, parsed.ts_result

    def verify_crc(self, cmd, inner_payload: bytes, warnings: list[str]):
        """Backward-compatible CRC wrapper around parse_packet()."""
        parsed = self.parse_packet(inner_payload, warnings)
        return parsed.crc_status
```

- [ ] **Step 4: Run full test suite**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q

cd "/Users/irfan/Documents/MAVERIC GSS"
python3 -m pytest tests/ -q
```

- [ ] **Step 5: Commit**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
git add mav_gss_lib/missions/maveric/adapter.py tests/test_ops_protocol_core.py
git commit -m "Remove deprecated parse_command/verify_crc wrappers, update tests"
```

---

## Task 4: Final Verification

- [ ] **Step 1: Run all test suites**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -v

cd "/Users/irfan/Documents/MAVERIC GSS"
python3 -m pytest tests/ -v
```

- [ ] **Step 2: Verify frontend builds**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE/mav_gss_lib/web"
npm run build
```

- [ ] **Step 3: Verify no remaining ambiguous surfaces**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -c "
# Verify all legacy surfaces have STATUS annotations
import ast, sys
files = [
    'mav_gss_lib/tui_rx.py',
    'mav_gss_lib/tui_tx.py',
    'mav_gss_lib/tui_common.py',
    'mav_gss_lib/protocol.py',
    'mav_gss_lib/imaging.py',
]
for f in files:
    doc = ast.get_docstring(ast.parse(open(f).read()))
    has_status = doc and 'STATUS:' in doc
    print(f'{f}: {\"OK\" if has_status else \"MISSING STATUS\"}')

# Verify deprecated wrappers are gone
from mav_gss_lib.missions.maveric.adapter import MavericMissionAdapter
assert not hasattr(MavericMissionAdapter, 'parse_command'), 'parse_command still exists'
assert not hasattr(MavericMissionAdapter, 'verify_crc'), 'verify_crc still exists'
print('Deprecated wrappers: removed')
print('OK')
"
```

---

## Post-Phase 10 State

**Decisions documented:**
- TUI (`tui_rx.py`, `tui_tx.py`, `tui_common.py`): MAVERIC-only legacy, not on migration path
- `backup_control/MAV_RX.py`, `backup_control/MAV_TX.py`: MAVERIC-only legacy (annotated in docstrings)
- `protocol.py` facade: Phase 11 removal candidate
- `imaging.py` facade: Phase 11 removal candidate
- `Packet.get()`, `Packet.__getitem__()`: TUI-only compat, Phase 11 removal candidate
- `packet_to_json()`, `queue_item_to_json()`, `history_entry()`: Phase 11 removal candidates

**What was removed:**
- `MavericMissionAdapter.parse_command()`: deprecated internal test-only wrapper, tests updated to use `parse_packet()` directly
- `MavericMissionAdapter.verify_crc()`: deprecated internal test-only wrapper, tests updated to use `parse_packet()` directly

**What did NOT change:**
- No user-facing UI or runtime behavior changes
- TUI still works (it's frozen, not removed)
- Web UI unchanged
- All facades still functional
