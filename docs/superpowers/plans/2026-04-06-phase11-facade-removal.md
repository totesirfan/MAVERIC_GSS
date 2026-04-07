# Phase 11: Mission-Agnostic Core and Facade Removal

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make platform-core mission-agnostic by ensuring all mission-specific resources, schema loading, labeling, and parsing are reached only through the shared mission loader and adapter contract, then remove all migration facades.

**Architecture:** The mission package contract expands with `init_mission(cfg) -> dict` — a hook the shared loader calls to let each mission handle its own initialization (node tables, command schema, etc.). `load_mission_adapter(cfg)` becomes the single startup entry point that owns metadata merge, mission init, adapter construction, and validation. Platform core never imports from `missions.maveric.*` — it routes through the adapter for resolution and the shared loader for startup. After core is clean, facades are deleted as the final step.

**Tech Stack:** Python 3.10+, pytest

---

## Design Decisions

1. **Mission package interface (v2).** Each mission package exports:
   - `ADAPTER_API_VERSION: int` — adapter contract version
   - `ADAPTER_CLASS: type` — adapter class satisfying MissionAdapter Protocol
   - `init_mission(cfg: dict) -> dict` — mission-specific initialization hook
   - `mission.yml` — mission metadata (optional, merged into cfg)

2. **`init_mission(cfg)` return contract.** Returns a dict with:
   ```python
   {
       "cmd_defs": dict,      # command schema (may be empty)
       "cmd_warn": str | None, # warning if schema couldn't load
   }
   ```
   The function owns all mission-specific initialization: populating node/ptype tables, resolving and loading the command schema from the mission package directory, etc. Platform core never calls these functions directly.

3. **`load_mission_adapter(cfg)` becomes the single startup path.** Primary signature: `load_mission_adapter(cfg) -> MissionAdapter`. The old `cmd_defs` parameter is retained as `cmd_defs: dict | None = None` for backward compatibility with `RxPipeline`'s fallback constructor and external test callers — but all new code calls `load_mission_adapter(cfg)` with one arg. The `cmd_defs` param is ignored when the mission package provides `init_mission()`. Internally:
   1. `load_mission_metadata(cfg)` — merge mission.yml into cfg
   2. `mission_pkg.init_mission(cfg)` — mission-specific init, returns resources
   3. `ADAPTER_CLASS(cmd_defs=resources["cmd_defs"])` — construct adapter
   4. `validate_adapter(...)` — validate
   The adapter stores `cmd_defs` as an attribute. Platform accesses `adapter.cmd_defs`.

4. **`runtime.cmd_defs` comes from `adapter.cmd_defs`.** WebRuntime no longer calls `load_command_defs()` or `init_nodes()` directly. It calls `load_mission_adapter(cfg)` and reads `adapter.cmd_defs`.

5. **Resolution methods on adapter (from current plan).** 6 new methods: `gs_node` property, `node_name()`, `ptype_name()`, `resolve_node()`, `resolve_ptype()`, `parse_cmd_line()`. Platform core uses these instead of importing MAVERIC functions.

6. **TXLog becomes adapter-driven for label resolution.** `TXLog.write_command()` currently imports `node_label`, `ptype_label`, `crc16`, `crc32c` from MAVERIC. It gets an `adapter` parameter and uses `adapter.node_label()` / `adapter.ptype_label()` for mission-specific label formatting. CRC functions move to canonical `protocols.crc` imports. No new `format_tx_log_lines()` method is added — TX logging is simpler than RX and inline label resolution is sufficient.

7. **Command schema path resolution is mission-owned.** `init_mission(cfg)` resolves the schema path relative to the mission package directory. `config.py`'s `get_command_defs_path()` is removed — it was a platform function doing mission-specific path resolution.

8. **Echo mission gets a minimal `init_mission()`.** Returns `{"cmd_defs": {}, "cmd_warn": None}`. No node init needed (echo adapter uses trivial stubs).

9. **Facade removal is the LAST task.** Only after all platform core imports are clean do we strip `protocol.py`, delete `imaging.py`, and clean `__init__.py`.

10. **TUI/legacy cleanup is secondary.** TUI imports are updated to canonical paths and `pkt.get()` → `pkt.field` as a separate low-priority task after core is mission-agnostic.

## File Plan

| Action | File | Change |
|---|---|---|
| Modify | `mav_gss_lib/mission_adapter.py` | Add resolution methods to Protocol; make `cfg` the primary entry point for `load_mission_adapter()`; retain deprecated `cmd_defs` param for compat; call `init_mission()` |
| Modify | `mav_gss_lib/missions/maveric/__init__.py` | Add `init_mission(cfg)` hook |
| Modify | `mav_gss_lib/missions/maveric/adapter.py` | Add 8 resolution methods (gs_node, node_name, ptype_name, node_label, ptype_label, resolve_node, resolve_ptype, parse_cmd_line) |
| Move | `mav_gss_lib/config/maveric_commands.yml` → `mav_gss_lib/missions/maveric/commands.yml` | Command schema to mission package |
| Modify | `mav_gss_lib/missions/maveric/mission.yml` | Update `command_defs` to `commands.yml` |
| Modify | `mav_gss_lib/missions/maveric/wire_format.py` | Update `load_command_defs()` default path |
| Modify | `mav_gss_lib/config.py` | Remove `get_command_defs_path()` |
| Modify | `tests/echo_mission.py` | Add `init_mission()`, 8 resolution stubs |
| Create | `tests/test_ops_adapter_resolution.py` | Tests for resolution methods and init_mission |
| Modify | `mav_gss_lib/web_runtime/state.py` | Use `load_mission_adapter(cfg)` single call; `cmd_defs` from adapter |
| Modify | `mav_gss_lib/web_runtime/tx.py` | Replace `protocol.*` with `runtime.adapter.*` |
| Modify | `mav_gss_lib/web_runtime/api.py` | Replace `protocol.*` with adapter calls via runtime |
| Modify | `mav_gss_lib/web_runtime/services.py` | Replace `protocol.*` with adapter calls |
| Modify | `mav_gss_lib/logging.py` | TXLog adapter-driven; remove MAVERIC imports |
| Modify | `mav_gss_lib/parsing.py` | Remove Packet dict-compat methods |
| Modify | `mav_gss_lib/tui_rx.py` | Canonical imports; `pkt.get()` → `pkt.field` |
| Modify | `mav_gss_lib/tui_tx.py` | Canonical imports |
| Modify | `mav_gss_lib/tui_common.py` | Canonical imports |
| Modify | `backup_control/MAV_RX.py` | Canonical imports |
| Modify | `backup_control/MAV_TX.py` | Canonical imports |
| Modify | `mav_gss_lib/protocol.py` | Strip to `clean_text()` only |
| Delete | `mav_gss_lib/imaging.py` | Remove facade |
| Modify | `mav_gss_lib/__init__.py` | Remove all re-exports |
| Modify | `tests/*.py` | Update imports; update `build_rx_log_record` callers |
| Modify | `MAV_IMG.py` | Canonical imports |

## Test Commands

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -v

cd "/Users/irfan/Documents/MAVERIC GSS"
python3 -m pytest tests/ -v
```

---

## Task 1: Add `init_mission()` Hook and Expand Mission Loader

**Files:**
- Modify: `mav_gss_lib/missions/maveric/__init__.py`
- Modify: `mav_gss_lib/mission_adapter.py`
- Modify: `tests/echo_mission.py`
- Create: `tests/test_ops_adapter_resolution.py`

- [ ] **Step 1: Write failing tests for `init_mission()` and new loader signature**

Create `tests/test_ops_adapter_resolution.py`:

```python
"""Tests for mission init hook, adapter resolution methods, and single-entry loader.

Verifies:
  1. init_mission() exists on mission packages and returns expected shape
  2. load_mission_adapter(cfg) works without cmd_defs param
  3. adapter.cmd_defs is populated by the loader
  4. Echo mission init_mission returns empty cmd_defs
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.mission_adapter import MissionAdapter, validate_adapter, _MISSION_REGISTRY


class TestInitMission(unittest.TestCase):
    """Verify init_mission hook on mission packages."""

    def test_maveric_init_mission_returns_cmd_defs(self):
        """MAVERIC init_mission() returns cmd_defs and cmd_warn."""
        from mav_gss_lib.config import load_gss_config
        from mav_gss_lib.mission_adapter import load_mission_metadata
        from mav_gss_lib.missions.maveric import init_mission

        cfg = load_gss_config()
        load_mission_metadata(cfg)
        resources = init_mission(cfg)
        self.assertIn("cmd_defs", resources)
        self.assertIn("cmd_warn", resources)
        self.assertIsInstance(resources["cmd_defs"], dict)
        self.assertGreater(len(resources["cmd_defs"]), 0)

    def test_echo_init_mission_returns_empty(self):
        """Echo init_mission() returns empty cmd_defs."""
        from tests.echo_mission import init_mission
        resources = init_mission({})
        self.assertEqual(resources["cmd_defs"], {})
        self.assertIsNone(resources["cmd_warn"])

    def test_load_mission_adapter_single_arg(self):
        """load_mission_adapter(cfg) works with only cfg (no cmd_defs)."""
        from mav_gss_lib.config import load_gss_config
        from mav_gss_lib.mission_adapter import load_mission_adapter

        cfg = load_gss_config()
        adapter = load_mission_adapter(cfg)
        self.assertIsInstance(adapter, MissionAdapter)
        self.assertIsInstance(adapter.cmd_defs, dict)
        self.assertGreater(len(adapter.cmd_defs), 0)

    def test_echo_via_loader_single_arg(self):
        """Echo mission loads via single-arg loader."""
        from mav_gss_lib.mission_adapter import load_mission_adapter

        _MISSION_REGISTRY["echo_test"] = "tests.echo_mission"
        try:
            cfg = {"general": {"mission": "echo_test"}}
            adapter = load_mission_adapter(cfg)
            self.assertIsInstance(adapter, MissionAdapter)
            self.assertEqual(adapter.cmd_defs, {})
        finally:
            del _MISSION_REGISTRY["echo_test"]


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/test_ops_adapter_resolution.py -v
```

Expected: FAIL — `init_mission` doesn't exist; `load_mission_adapter` requires `cmd_defs`.

- [ ] **Step 3: Add `init_mission()` to MAVERIC mission package**

In `mav_gss_lib/missions/maveric/__init__.py`, add the `init_mission` function:

```python
"""
mav_gss_lib.missions.maveric -- MAVERIC CubeSat Mission Implementation

Mission package contract:
  - ADAPTER_API_VERSION: int — adapter contract version
  - ADAPTER_CLASS: type — adapter class (MavericMissionAdapter)
  - init_mission(cfg): mission-specific initialization hook
  - mission.yml: mission metadata (nodes, ptypes, callsigns, schema path, UI labels)
  - adapter.py: MissionAdapter implementation
  - wire_format.py: command wire format, schema, node tables
  - imaging.py: image chunk reassembly
"""

ADAPTER_API_VERSION = 1

from mav_gss_lib.missions.maveric.adapter import MavericMissionAdapter as ADAPTER_CLASS  # noqa: F401


def init_mission(cfg: dict) -> dict:
    """Initialize MAVERIC mission resources.

    Called by the shared mission loader after metadata merge.
    Populates node/ptype tables and loads the command schema.

    Returns:
        {"cmd_defs": dict, "cmd_warn": str | None}
    """
    import os
    from mav_gss_lib.missions.maveric.wire_format import init_nodes, load_command_defs

    init_nodes(cfg)

    # Resolve command schema path: check mission package dir first
    cmd_defs_name = cfg.get("general", {}).get("command_defs", "commands.yml")
    pkg_dir = os.path.dirname(os.path.abspath(__file__))

    if os.path.isabs(cmd_defs_name):
        path = cmd_defs_name
    else:
        mission_path = os.path.join(pkg_dir, cmd_defs_name)
        if os.path.isfile(mission_path):
            path = mission_path
        else:
            # Fall back to config dir for backward compat
            config_dir = os.path.join(pkg_dir, "..", "..", "config")
            config_path = os.path.normpath(os.path.join(config_dir, cmd_defs_name))
            path = config_path if os.path.isfile(config_path) else mission_path

    cmd_defs, cmd_warn = load_command_defs(path)
    return {"cmd_defs": cmd_defs, "cmd_warn": cmd_warn}
```

- [ ] **Step 4: Add `init_mission()` to echo mission fixture**

In `tests/echo_mission.py`, add at module level (after `ADAPTER_CLASS`):

```python
def init_mission(cfg: dict) -> dict:
    """Echo mission has no initialization requirements."""
    return {"cmd_defs": {}, "cmd_warn": None}
```

- [ ] **Step 5: Update `load_mission_adapter()` to single-entry-point**

In `mav_gss_lib/mission_adapter.py`, replace the current `load_mission_adapter(cfg, cmd_defs)` with:

```python
def load_mission_adapter(cfg: dict, cmd_defs: dict | None = None):
    """Load, instantiate, and validate a mission adapter from config.

    This is the single shared mission-loading path. It owns:
      1. load_mission_metadata(cfg) — merge mission.yml
      2. mission_pkg.init_mission(cfg) — mission-specific init
      3. ADAPTER_CLASS(cmd_defs=...) — adapter construction
      4. validate_adapter() — interface validation

    The cmd_defs parameter is deprecated and ignored when the mission
    package provides init_mission(). It exists only for backward
    compatibility with callers that haven't been updated yet.

    Returns a validated adapter with cmd_defs populated.
    """
    import importlib
    import logging

    mission = cfg.get("general", {}).get("mission", "maveric")
    mission_name = cfg.get("general", {}).get("mission_name", mission.upper())

    # Ensure mission metadata is merged (idempotent — safe if already called)
    load_mission_metadata(cfg)

    module_path = _MISSION_REGISTRY.get(mission)
    if module_path is None:
        raise ValueError(
            f"Unknown mission '{mission}' in general.mission config. "
            f"Supported: {', '.join(sorted(_MISSION_REGISTRY))}"
        )

    try:
        mission_pkg = importlib.import_module(module_path)
    except ImportError as exc:
        raise ValueError(
            f"Mission '{mission}' package '{module_path}' could not be imported: {exc}"
        ) from exc

    api_version = getattr(mission_pkg, "ADAPTER_API_VERSION", None)
    if api_version is None:
        raise ValueError(
            f"Mission '{mission}' package '{module_path}' has no ADAPTER_API_VERSION"
        )

    adapter_cls = getattr(mission_pkg, "ADAPTER_CLASS", None)
    if adapter_cls is None:
        raise ValueError(
            f"Mission '{mission}' package '{module_path}' has no ADAPTER_CLASS"
        )

    # Call mission init hook if available
    init_fn = getattr(mission_pkg, "init_mission", None)
    if init_fn is not None:
        resources = init_fn(cfg)
        resolved_cmd_defs = resources.get("cmd_defs", {})
    elif cmd_defs is not None:
        # Backward compat: caller provided cmd_defs directly
        resolved_cmd_defs = cmd_defs
    else:
        resolved_cmd_defs = {}

    adapter = adapter_cls(cmd_defs=resolved_cmd_defs)
    validate_adapter(adapter, api_version, mission_name)

    cmd_path = cfg.get("general", {}).get("command_defs", "")
    logging.info(
        "Mission loaded: %s [id=%s, adapter API v%d, schema=%s]",
        mission_name, mission, api_version, cmd_path,
    )
    return adapter
```

- [ ] **Step 6: Run tests**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/test_ops_adapter_resolution.py -v
python3 -m pytest tests/ -q
```

All existing tests should still pass because `cmd_defs` param is now optional with backward compat.

- [ ] **Step 7: Commit**

```bash
git add mav_gss_lib/mission_adapter.py mav_gss_lib/missions/maveric/__init__.py tests/echo_mission.py tests/test_ops_adapter_resolution.py
git commit -m "Add init_mission hook and make load_mission_adapter single-entry-point"
```

---

## Task 2: Add Resolution Methods to Adapter Protocol

**Files:**
- Modify: `mav_gss_lib/mission_adapter.py`
- Modify: `mav_gss_lib/missions/maveric/adapter.py`
- Modify: `tests/echo_mission.py`
- Modify: `tests/test_ops_adapter_resolution.py`

- [ ] **Step 1: Write failing tests for resolution methods**

Add to `tests/test_ops_adapter_resolution.py`:

```python
class TestEchoResolution(unittest.TestCase):
    """Verify echo adapter resolution stubs."""

    def setUp(self):
        from tests.echo_mission import EchoMissionAdapter, ADAPTER_API_VERSION
        self.adapter = EchoMissionAdapter(cmd_defs={})

    def test_echo_satisfies_protocol(self):
        self.assertIsInstance(self.adapter, MissionAdapter)
        validate_adapter(self.adapter, 1, "echo")

    def test_node_name(self):
        self.assertEqual(self.adapter.node_name(0), "0")

    def test_ptype_name(self):
        self.assertEqual(self.adapter.ptype_name(1), "1")

    def test_resolve_node_numeric(self):
        self.assertEqual(self.adapter.resolve_node("5"), 5)

    def test_resolve_node_non_numeric(self):
        self.assertIsNone(self.adapter.resolve_node("GS"))

    def test_resolve_ptype_numeric(self):
        self.assertEqual(self.adapter.resolve_ptype("2"), 2)

    def test_gs_node(self):
        self.assertEqual(self.adapter.gs_node, 0)

    def test_parse_cmd_line(self):
        result = self.adapter.parse_cmd_line("test arg1 arg2")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 6)

    def test_node_label(self):
        result = self.adapter.node_label(5)
        self.assertIn("5", result)

    def test_ptype_label(self):
        result = self.adapter.ptype_label(1)
        self.assertIn("1", result)


class TestMavericResolution(unittest.TestCase):
    """Verify MAVERIC adapter resolves correctly."""

    def setUp(self):
        from mav_gss_lib.config import load_gss_config
        from mav_gss_lib.mission_adapter import load_mission_adapter
        cfg = load_gss_config()
        self.adapter = load_mission_adapter(cfg)

    def test_node_name_known(self):
        self.assertEqual(self.adapter.node_name(6), "GS")

    def test_ptype_name_known(self):
        self.assertEqual(self.adapter.ptype_name(1), "CMD")

    def test_resolve_node_by_name(self):
        self.assertEqual(self.adapter.resolve_node("GS"), 6)

    def test_resolve_node_by_id(self):
        self.assertEqual(self.adapter.resolve_node("6"), 6)

    def test_resolve_ptype_by_name(self):
        self.assertEqual(self.adapter.resolve_ptype("CMD"), 1)

    def test_gs_node_is_6(self):
        self.assertEqual(self.adapter.gs_node, 6)

    def test_parse_cmd_line_full(self):
        src, dest, echo, ptype, cmd_id, args = self.adapter.parse_cmd_line("6 1 0 1 ping REQ")
        self.assertEqual(cmd_id, "ping")

    def test_node_label_known(self):
        result = self.adapter.node_label(6)
        self.assertIn("GS", result)

    def test_ptype_label_known(self):
        result = self.adapter.ptype_label(1)
        self.assertIn("CMD", result)
```

- [ ] **Step 2: Add methods to MissionAdapter Protocol**

In `mav_gss_lib/mission_adapter.py`, add after the logging-slot block:

```python
    # -- Resolution contract (Phase 11) --
    @property
    def gs_node(self) -> int: ...
    def node_name(self, node_id: int) -> str: ...
    def ptype_name(self, ptype_id: int) -> str: ...
    def node_label(self, node_id: int) -> str: ...
    def ptype_label(self, ptype_id: int) -> str: ...
    def resolve_node(self, s: str) -> int | None: ...
    def resolve_ptype(self, s: str) -> int | None: ...
    def parse_cmd_line(self, line: str) -> tuple: ...
```

Add all to `validate_adapter()` method list. Add `gs_node` property check via `hasattr`.

- [ ] **Step 3: Implement on MavericMissionAdapter**

Add to `mav_gss_lib/missions/maveric/adapter.py`. The top-level imports already include `node_name` and `ptype_name` from wire_format — rename them to avoid collision:

Update the import at top of adapter.py:

```python
from mav_gss_lib.missions.maveric.wire_format import (
    GS_NODE,
    apply_schema,
    build_cmd_raw,
    node_name as _wire_node_name,
    ptype_name as _wire_ptype_name,
    try_parse_command,
    validate_args,
)
```

Then add methods:

```python
    # -- Resolution contract (Phase 11) --

    @property
    def gs_node(self) -> int:
        return GS_NODE

    def node_name(self, node_id: int) -> str:
        return _wire_node_name(node_id)

    def ptype_name(self, ptype_id: int) -> str:
        return _wire_ptype_name(ptype_id)

    def node_label(self, node_id: int) -> str:
        from mav_gss_lib.missions.maveric.wire_format import node_label
        return node_label(node_id)

    def ptype_label(self, ptype_id: int) -> str:
        from mav_gss_lib.missions.maveric.wire_format import ptype_label
        return ptype_label(ptype_id)

    def resolve_node(self, s: str) -> int | None:
        from mav_gss_lib.missions.maveric.wire_format import resolve_node
        return resolve_node(s)

    def resolve_ptype(self, s: str) -> int | None:
        from mav_gss_lib.missions.maveric.wire_format import resolve_ptype
        return resolve_ptype(s)

    def parse_cmd_line(self, line: str) -> tuple:
        from mav_gss_lib.missions.maveric.wire_format import parse_cmd_line
        return parse_cmd_line(line)
```

Update all internal references from `node_name(...)` to `_wire_node_name(...)` and `ptype_name(...)` to `_wire_ptype_name(...)` throughout the existing adapter methods (packet_to_json, packet_list_row, packet_detail_blocks, queue_item_to_json, history_entry, format_log_lines).

- [ ] **Step 4: Implement on EchoMissionAdapter**

Add to `tests/echo_mission.py`:

```python
    @property
    def gs_node(self) -> int:
        return 0

    def node_name(self, node_id: int) -> str:
        return str(node_id)

    def ptype_name(self, ptype_id: int) -> str:
        return str(ptype_id)

    def node_label(self, node_id: int) -> str:
        return str(node_id)

    def ptype_label(self, ptype_id: int) -> str:
        return str(ptype_id)

    def resolve_node(self, s: str) -> int | None:
        try:
            return int(s)
        except ValueError:
            return None

    def resolve_ptype(self, s: str) -> int | None:
        try:
            return int(s)
        except ValueError:
            return None

    def parse_cmd_line(self, line: str) -> tuple:
        parts = line.split()
        cmd = parts[0] if parts else ""
        args = " ".join(parts[1:])
        return (0, 0, 0, 0, cmd, args)
```

- [ ] **Step 5: Run tests**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/test_ops_adapter_resolution.py -v
python3 -m pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add mav_gss_lib/mission_adapter.py mav_gss_lib/missions/maveric/adapter.py tests/echo_mission.py tests/test_ops_adapter_resolution.py
git commit -m "Add resolution and label methods to MissionAdapter Protocol"
```

---

## Task 3: Move Command Schema and Simplify Startup

**Files:**
- Move: `mav_gss_lib/config/maveric_commands.yml` → `mav_gss_lib/missions/maveric/commands.yml`
- Modify: `mav_gss_lib/missions/maveric/mission.yml`
- Modify: `mav_gss_lib/missions/maveric/wire_format.py`
- Modify: `mav_gss_lib/config.py`
- Modify: `mav_gss_lib/web_runtime/state.py`

- [ ] **Step 1: Move the command schema file**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
cp mav_gss_lib/config/maveric_commands.yml mav_gss_lib/missions/maveric/commands.yml
```

Keep the original until all paths are updated. It will be removed at the end.

- [ ] **Step 2: Update `mission.yml`**

Change `command_defs: maveric_commands.yml` to `command_defs: commands.yml`.

- [ ] **Step 3: Update `load_command_defs()` default path in `wire_format.py`**

Replace the path resolution block:

```python
    from pathlib import Path as _Path
    _cfg_dir = _Path(__file__).resolve().parent.parent.parent / "config"
    if path is None:
        path = str(_cfg_dir / "maveric_commands.yml")
    elif not os.path.isabs(path):
        path = str(_cfg_dir / path)
```

with:

```python
    from pathlib import Path as _Path
    _mission_dir = _Path(__file__).resolve().parent
    if path is None:
        path = str(_mission_dir / "commands.yml")
    elif not os.path.isabs(path):
        path = str((_mission_dir / path).resolve())
```

- [ ] **Step 4: Remove `get_command_defs_path()` from `config.py`**

Delete the function. It was platform code doing mission-specific path resolution. `init_mission()` now owns this.

- [ ] **Step 5: Simplify `WebRuntime.__init__()`**

Replace the current init body with:

```python
    def __init__(self) -> None:
        self.session_token = secrets.token_urlsafe(24)
        self.max_packets = MAX_PACKETS
        self.max_history = MAX_HISTORY
        self.max_queue = MAX_QUEUE

        self.cfg = load_gss_config()
        self.adapter = load_mission_adapter(self.cfg)
        self.cmd_defs = self.adapter.cmd_defs

        self.rx_status = ["OFFLINE"]
        self.tx_status = ["OFFLINE"]

        self.csp = CSPConfig()
        self.ax25 = AX25Config()
        apply_csp(self.cfg, self.csp)
        apply_ax25(self.cfg, self.ax25)

        self.shutdown_task = None
        self.had_clients = False
        self.cfg_lock = threading.Lock()
        self.rx = RxService(self)
        self.tx = TxService(self)
```

Remove the `_load_adapter()` method. Update imports — remove `get_command_defs_path` import and the now-unnecessary `load_mission_metadata` import.

Update `state.py` imports:

```python
from mav_gss_lib.config import (
    apply_ax25,
    apply_csp,
    load_gss_config,
)
from mav_gss_lib.mission_adapter import load_mission_adapter
from mav_gss_lib.protocols.ax25 import AX25Config
from mav_gss_lib.protocols.csp import CSPConfig
from .services import RxService, TxService
```

No more imports from `mav_gss_lib.protocol` or `mav_gss_lib.missions.maveric.*`.

- [ ] **Step 6: Update `.gitignore` for new schema location**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
grep -n "maveric_commands" .gitignore
```

If the old path was gitignored, add the new path. Keep the example file committed.

- [ ] **Step 7: Remove old schema file**

```bash
rm mav_gss_lib/config/maveric_commands.yml
```

- [ ] **Step 8: Run tests**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q
```

Fix any tests that imported `get_command_defs_path` — they should use `load_mission_adapter(cfg)` instead.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Move command schema to mission package, simplify WebRuntime startup"
```

---

## Task 4: Migrate Platform Core to Adapter Calls

**Files:**
- Modify: `mav_gss_lib/web_runtime/tx.py`
- Modify: `mav_gss_lib/web_runtime/api.py`
- Modify: `mav_gss_lib/web_runtime/services.py`
- Modify: `mav_gss_lib/logging.py`

- [ ] **Step 1: Update `web_runtime/tx.py`**

Remove:
```python
import mav_gss_lib.protocol as protocol
from mav_gss_lib.protocol import parse_cmd_line, resolve_node, resolve_ptype
```

Replace each usage with adapter calls via `runtime.adapter`:
- `protocol.GS_NODE` → `runtime.adapter.gs_node`
- `parse_cmd_line(line)` → `runtime.adapter.parse_cmd_line(line)`
- `resolve_node(str(...))` → `runtime.adapter.resolve_node(str(...))`
- `resolve_ptype(str(...))` → `runtime.adapter.resolve_ptype(str(...))`

- [ ] **Step 2: Update `web_runtime/api.py`**

Remove:
```python
from mav_gss_lib.protocol import node_name, ptype_name, resolve_node, resolve_ptype
```

`parse_replay_entry()` needs adapter for `node_name`/`ptype_name`. Add `adapter=None` parameter. When provided, use `adapter.node_name()` / `adapter.ptype_name()`. The route handler passes `runtime.adapter`.

`parse_import_file()` needs adapter for `resolve_node`/`resolve_ptype`. It already has a `runtime` parameter — use `runtime.adapter.resolve_node()` / `runtime.adapter.resolve_ptype()`.

Remove `get_command_defs_path` from imports if still present.

- [ ] **Step 3: Update `web_runtime/services.py`**

Remove:
```python
import mav_gss_lib.protocol as protocol
from mav_gss_lib.protocol import parse_cmd_line, resolve_node, resolve_ptype
```

Replace `protocol.node_name(item["dest"])` with `self.runtime.adapter.node_name(item["dest"])`.

- [ ] **Step 4: Make TXLog adapter-driven in `logging.py`**

Remove MAVERIC imports:
```python
from mav_gss_lib.protocol import node_label, ptype_label, clean_text, crc16, crc32c
```

Replace with:
```python
from mav_gss_lib.protocol import clean_text
from mav_gss_lib.protocols.crc import crc16, crc32c
```

Add `adapter=None` parameter to `TXLog.write_command()`. Use `adapter.node_label()` / `adapter.ptype_label()` when adapter is provided, fall back to `str()` when not.

Update the call site in `services.py` `TxService.run_send()` to pass `self.runtime.adapter`.

Add `_BaseLog._route_line()` and `_BaseLog._format_csp()` — these use `node_label`/`ptype_label`. Either make them accept an adapter param, or move them to the adapter's `format_tx_log_lines()` method. The simplest approach: pass adapter to `write_command()` and use `adapter.node_label()`/`adapter.ptype_label()` inline.

- [ ] **Step 5: Run tests**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q
```

- [ ] **Step 6: Verify no MAVERIC imports in platform core**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
grep -rn "from mav_gss_lib.protocol import\|from mav_gss_lib.missions" mav_gss_lib/web_runtime/ mav_gss_lib/logging.py mav_gss_lib/parsing.py mav_gss_lib/config.py --include="*.py" | grep -v "__pycache__" | grep -v "clean_text" | grep -v "mission_adapter"
```

Expected: no output.

- [ ] **Step 7: Commit**

```bash
git add mav_gss_lib/web_runtime/ mav_gss_lib/logging.py
git commit -m "Migrate platform core to adapter calls, eliminate MAVERIC imports"
```

---

## Task 5: Migrate Legacy and Test Imports (Secondary)

**Files:**
- Modify: `mav_gss_lib/tui_rx.py`, `tui_tx.py`, `tui_common.py`
- Modify: `backup_control/MAV_RX.py`, `MAV_TX.py`
- Modify: `MAV_IMG.py`
- Modify: `mav_gss_lib/parsing.py` (remove Packet dict-compat)
- Modify: all `tests/*.py` files

- [ ] **Step 1: Update TUI imports to canonical paths**

Replace `import mav_gss_lib.protocol as protocol` with `import mav_gss_lib.missions.maveric.wire_format as protocol` in all TUI files. Replace named imports similarly.

- [ ] **Step 2: Update backup_control imports**

Same pattern for `backup_control/MAV_RX.py` and `backup_control/MAV_TX.py`.

- [ ] **Step 3: Update `MAV_IMG.py` imports**

Replace facade imports with canonical sources.

- [ ] **Step 4: Replace `pkt.get()` / `pkt["key"]` with `pkt.field` in `tui_rx.py`**

Mechanical replacement of all 58 dict-style accesses.

- [ ] **Step 5: Delete Packet dict-compat methods in `parsing.py`**

Remove `get()` and `__getitem__()` from the Packet dataclass.

- [ ] **Step 6: Update test file imports**

For each test file, replace `from mav_gss_lib.protocol import X` with canonical imports from `protocols.*` or `missions.maveric.wire_format`.

Update tests that called `load_mission_adapter(cfg, cmd_defs)` with two args — they can now use `load_mission_adapter(cfg)` with one arg.

Update tests that imported `get_command_defs_path` — use `load_mission_adapter(cfg)` instead.

- [ ] **Step 7: Run all test suites**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q

cd "/Users/irfan/Documents/MAVERIC GSS"
python3 -m pytest tests/ -q
```

- [ ] **Step 8: Commit**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
git add -A
git commit -m "Migrate legacy and test imports to canonical paths, remove Packet dict-compat"
```

---

## Task 6: Delete Facades

**Files:**
- Modify: `mav_gss_lib/protocol.py` — strip to `clean_text()` only
- Delete: `mav_gss_lib/imaging.py`
- Modify: `mav_gss_lib/__init__.py` — remove re-exports
- Modify: `mav_gss_lib/mission_adapter.py` — remove MavericMissionAdapter facade re-export

- [ ] **Step 1: Strip `protocol.py` to platform utility**

Replace entire file with:

```python
"""
mav_gss_lib.protocol -- Platform Utilities

Generic text utilities used across the platform.
All protocol-family and mission re-exports have been removed (Phase 11).
Import directly from canonical locations:
  - mav_gss_lib.protocols.*                   (CRC, CSP, KISS, AX.25)
  - mav_gss_lib.missions.maveric.wire_format  (nodes, commands, schema)

Author:  Irfan Annuar - USC ISI SERC
"""

_CLEAN_TABLE = bytearray(0xB7 for _ in range(256))  # middle dot
for _b in range(32, 127):
    _CLEAN_TABLE[_b] = _b
_CLEAN_TABLE = bytes(_CLEAN_TABLE)


def clean_text(data: bytes) -> str:
    """Printable ASCII representation with non-printable bytes as middle dot."""
    return data.translate(_CLEAN_TABLE).decode('latin-1')
```

- [ ] **Step 2: Delete `imaging.py`**

```bash
rm mav_gss_lib/imaging.py
```

Update any remaining consumer (MAV_IMG.py, backup_control/MAV_RX.py) to import from `mav_gss_lib.missions.maveric.imaging` directly (should already be done in Task 5).

- [ ] **Step 3: Clean `__init__.py`**

Replace with:

```python
"""
mav_gss_lib -- Ground Station Platform Library

Mission-agnostic platform for CubeSat ground station software.
The web runtime (MAV_WEB.py) is the primary operational interface.

Core modules:
    mission_adapter  -- Mission boundary Protocol and shared loader
    protocols/       -- Protocol-family support (CRC, CSP, AX.25, KISS)
    parsing          -- RX packet processing pipeline
    logging          -- Session logging (JSONL + text)
    config           -- Shared config loader
    transport        -- ZMQ + PMT pub/sub
    web_runtime/     -- FastAPI web backend

Mission packages:
    missions/maveric/  -- MAVERIC CubeSat mission implementation

Author:  Irfan Annuar - USC ISI SERC
"""
```

- [ ] **Step 4: Remove MavericMissionAdapter facade re-export from `mission_adapter.py`**

Delete the line at the bottom:
```python
from mav_gss_lib.missions.maveric.adapter import MavericMissionAdapter  # noqa: F401
```

Update any remaining callers of `from mav_gss_lib.mission_adapter import MavericMissionAdapter` to import from `mav_gss_lib.missions.maveric.adapter` directly.

- [ ] **Step 5: Run all test suites**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q

cd "/Users/irfan/Documents/MAVERIC GSS"
python3 -m pytest tests/ -q
```

- [ ] **Step 6: Verify no facade imports remain**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
# Check for any remaining facade imports in the entire codebase
grep -rn "from mav_gss_lib.protocol import" mav_gss_lib/ tests/ backup_control/ --include="*.py" | grep -v "clean_text" | grep -v "__pycache__"
grep -rn "from mav_gss_lib.imaging import" mav_gss_lib/ tests/ backup_control/ --include="*.py" | grep -v "__pycache__"
grep -rn "from mav_gss_lib import " mav_gss_lib/ tests/ backup_control/ --include="*.py" | grep -v "__pycache__"
```

Expected: no output for any of these.

- [ ] **Step 7: Build frontend**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE/mav_gss_lib/web"
npm run build
```

- [ ] **Step 8: Commit**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
git add -A
git commit -m "Remove protocol.py facade, imaging.py facade, and __init__.py re-exports"
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
print('cmd_defs:', len(rt.cmd_defs))
print('node_name(6):', rt.adapter.node_name(6))
print('resolve_node(GS):', rt.adapter.resolve_node('GS'))
print('gs_node:', rt.adapter.gs_node)
print('OK')
" 2>&1
```

- [ ] **Step 3: Verify echo mission**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -c "
from mav_gss_lib.mission_adapter import load_mission_adapter, _MISSION_REGISTRY
_MISSION_REGISTRY['echo'] = 'tests.echo_mission'
adapter = load_mission_adapter({'general': {'mission': 'echo'}})
print('type:', type(adapter).__name__)
print('cmd_defs:', adapter.cmd_defs)
print('node_name(5):', adapter.node_name(5))
print('gs_node:', adapter.gs_node)
del _MISSION_REGISTRY['echo']
print('OK')
"
```

- [ ] **Step 4: Verify no MAVERIC imports in platform core**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -c "
import ast, sys

core_files = [
    'mav_gss_lib/web_runtime/state.py',
    'mav_gss_lib/web_runtime/api.py',
    'mav_gss_lib/web_runtime/tx.py',
    'mav_gss_lib/web_runtime/services.py',
    'mav_gss_lib/web_runtime/runtime.py',
    'mav_gss_lib/web_runtime/rx.py',
    'mav_gss_lib/web_runtime/app.py',
    'mav_gss_lib/logging.py',
    'mav_gss_lib/parsing.py',
    'mav_gss_lib/config.py',
    'mav_gss_lib/mission_adapter.py',
]
issues = []
for f in core_files:
    tree = ast.parse(open(f).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if 'missions.maveric' in node.module and 'mission_adapter' not in f:
                issues.append(f'{f}: imports from {node.module}')
if issues:
    for issue in issues:
        print('FAIL:', issue)
    sys.exit(1)
print('All platform-core files are mission-agnostic')
print('OK')
"
```

- [ ] **Step 5: Build frontend**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE/mav_gss_lib/web"
npm run build
```

---

## Post-Phase 11 State

**Mission package interface (v2):**
```
missions/<mission_id>/
  __init__.py          — ADAPTER_API_VERSION, ADAPTER_CLASS, init_mission(cfg)
  mission.yml          — mission metadata
  adapter.py           — MissionAdapter implementation
  commands.yml         — command schema (mission-specific)
  wire_format.py       — wire format, node tables, schema loader (MAVERIC)
  imaging.py           — image reassembly (MAVERIC)
```

**Platform core imports:**
- Platform modules import from: `mission_adapter`, `protocols.*`, `config`, `transport`, `parsing`, `logging`, `protocol` (clean_text only)
- Platform modules do NOT import from: `missions.maveric.*`
- Resolution calls go through: `adapter.node_name()`, `adapter.resolve_node()`, etc.
- Startup goes through: `load_mission_adapter(cfg)` (single entry point)

**What was removed:**
- `protocol.py` re-exports (40+ symbols)
- `imaging.py` facade
- `__init__.py` re-exports
- `MavericMissionAdapter` re-export from `mission_adapter.py`
- `Packet.get()` / `__getitem__()` dict-compat
- `get_command_defs_path()` from config.py
- `cmd_defs` parameter from `load_mission_adapter()` — retained as deprecated `None`-default for backward compat with RxPipeline fallback; ignored when `init_mission()` is present; all new callers use single-arg form
- Direct MAVERIC imports from all platform-core modules

**Architecture after Phase 11:**
- Platform core is mission-agnostic — zero imports from `missions.maveric.*`
- The shared mission loader is the single boundary between platform and mission
- MAVERIC is a normal mission package that implements the standard contract
- A second mission can be added by creating a new package with `ADAPTER_API_VERSION`, `ADAPTER_CLASS`, `init_mission()`, and `mission.yml`
