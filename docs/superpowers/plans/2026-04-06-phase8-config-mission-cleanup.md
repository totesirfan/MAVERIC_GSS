# Phase 8: Config and Mission Package Cleanup

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a version-1 `mission.yml` for MAVERIC, update the shared mission loader to read and validate it, enhance startup diagnostics, and add config validation tests.

**Architecture:** Each mission package now includes a `mission.yml` with mission metadata (name, nodes, ptypes, node descriptions, command schema path, UI labels). The mission loader is split into two steps: `load_mission_metadata(cfg)` reads mission.yml and merges into cfg (must happen before `init_nodes` / `load_command_defs`), then `load_mission_adapter(cfg, cmd_defs)` constructs and validates the adapter. `WebRuntime.__init__()` is reordered: `load_gss_config() → load_mission_metadata() → init_nodes() → load_command_defs() → load_mission_adapter()`. `_DEFAULTS` in `config.py` is narrowed to platform-only settings FIRST (Task 2), then mission.yml merge is added (Task 3), so the new source of truth is exercised immediately. In Phase 8, `command_defs` may now be sourced from mission metadata, but path resolution still uses the existing config resolver rules; this phase does not yet make command schema paths mission-package-relative by default.

**Tech Stack:** Python 3.10+, PyYAML, pytest

---

## Design Decisions

1. **`mission.yml` is a YAML file in the mission package directory.** The loader finds it at `<mission_package_dir>/mission.yml`. It is NOT a required constructor argument — the loader resolves the path from the package's `__file__`.

2. **Two-step mission loading, but safe for all callers.** `load_mission_metadata(cfg)` reads mission.yml and merges into cfg. `load_mission_adapter(cfg, cmd_defs)` calls `load_mission_metadata(cfg)` internally before constructing the adapter, so direct callers (RxPipeline fallback, tests) don't need to know about the two-step flow. `WebRuntime` calls `load_mission_metadata()` explicitly earlier (before `init_nodes()`) so node tables and command schema paths see mission values. The merge is idempotent (setdefault-based), so calling it twice is safe.

3. **`_DEFAULTS` narrowing and mission.yml merge happen in one atomic task.** Both changes land together so the working tree is never in a broken intermediate state. Tests pass before and after.

4. **`mission.yml` content fills gaps in the runtime config.** The mission's `nodes`, `ptypes`, `node_descriptions`, and `general` settings provide defaults. The operator's `maveric_gss.yml` values take precedence (they were already merged by `load_gss_config()`).

5. **`mission.yml` is optional for v1.** If a mission package has no `mission.yml`, the loader logs a debug message but continues. This keeps the echo test fixture working.

6. **No config file split.** The operator still edits one `maveric_gss.yml`. Mission metadata in `mission.yml` provides defaults that the operator config can override.

7. **`command_defs` path handling stays conservative in Phase 8.** `mission.yml` may set `general.command_defs`, but that value is still resolved through the existing config path rules in `config.py`. This phase does not yet move `commands.yml` into the mission package or add mission-package-relative schema resolution.

8. **`missions/maveric/__init__.py` is updated** to document the package contract (ADAPTER_API_VERSION, ADAPTER_CLASS, mission.yml).

## File Plan

| Action | File | Change |
|---|---|---|
| Create | `mav_gss_lib/missions/maveric/mission.yml` | MAVERIC mission metadata |
| Modify | `mav_gss_lib/config.py` | Narrow `_DEFAULTS` to platform-only settings |
| Modify | `mav_gss_lib/mission_adapter.py` | Add `load_mission_metadata()`, call it from `load_mission_adapter()` |
| Modify | `mav_gss_lib/web_runtime/state.py` | Call `load_mission_metadata()` before `init_nodes()` |
| Modify | `mav_gss_lib/missions/maveric/__init__.py` | Document package contract |
| Create | `tests/test_ops_config_validation.py` | Config validation tests |

## Test Commands

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -v
```

---

## Task 1: Create `missions/maveric/mission.yml`

**Files:**
- Create: `mav_gss_lib/missions/maveric/mission.yml`

- [ ] **Step 1: Create the mission metadata file**

Extract MAVERIC-specific metadata from `config.py` `_DEFAULTS` into a YAML file:

```yaml
# MAVERIC CubeSat Mission Metadata
# This file defines MAVERIC-specific defaults that the platform
# merges into the runtime config at startup.

mission_name: MAVERIC

nodes:
  0: NONE
  1: LPPM
  2: EPS
  3: UPPM
  4: HOLONAV
  5: ASTROBOARD
  6: GS
  7: FTDI

ptypes:
  1: CMD
  2: RES
  3: ACK
  4: TLM
  5: FILE

node_descriptions:
  LPPM: Lower Pluggable Processor Module
  UPPM: Upper Pluggable Processor Module
  EPS: Electrical Power System
  GS: Ground Station

gs_node: GS

ax25:
  src_call: WM2XBB
  src_ssid: 0
  dest_call: WS9XSW
  dest_ssid: 0

csp:
  priority: 2
  source: 0
  destination: 8
  dest_port: 24
  src_port: 0
  flags: 0
  csp_crc: true

command_defs: maveric_commands.yml

tx:
  frequency: "437.6 MHz"
  uplink_mode: AX.25

ui:
  rx_title: Mission Downlink
  tx_title: Mission Uplink
  splash_subtitle: Mission Ground Station
```

In Phase 8, that `command_defs` value is still resolved by the existing
`config.py` resolver. It provides the configured schema filename/path, but does
not yet imply that the schema file lives inside the mission package directory.

- [ ] **Step 2: Verify the file is valid YAML**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -c "
import yaml
from pathlib import Path
p = Path('mav_gss_lib/missions/maveric/mission.yml')
data = yaml.safe_load(p.read_text())
print('mission_name:', data['mission_name'])
print('nodes:', len(data['nodes']))
print('ptypes:', len(data['ptypes']))
print('command_defs:', data['command_defs'])
print('OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add mav_gss_lib/missions/maveric/mission.yml
git commit -m "Add mission.yml for MAVERIC with mission metadata"
```

---

## Task 2: Narrow Defaults + Add Mission Metadata Loading (Atomic)

Both changes land together so the working tree is never broken. `_DEFAULTS` is narrowed AND `load_mission_metadata()` + `load_mission_adapter()` internal call are added in one step.

**Files:**
- Modify: `mav_gss_lib/config.py`
- Modify: `mav_gss_lib/mission_adapter.py`
- Modify: `mav_gss_lib/web_runtime/state.py`
- Modify: `mav_gss_lib/missions/maveric/__init__.py`

- [ ] **Step 1: Narrow `_DEFAULTS` to platform-only settings**

Replace `_DEFAULTS` in `config.py` with:

```python
_DEFAULTS = {
    "nodes": {},
    "ptypes": {},
    "node_descriptions": {},
    "ax25": {
        "src_call":  "NOCALL",
        "src_ssid":  0,
        "dest_call": "NOCALL",
        "dest_ssid": 0,
    },
    "csp": {
        "priority":    2,
        "source":      0,
        "destination": 0,
        "dest_port":   0,
        "src_port":    0,
        "flags":       0x00,
        "csp_crc":     True,
    },
    "tx": {
        "zmq_addr":  "tcp://127.0.0.1:52002",
        "frequency": "",
        "delay_ms":  500,
        "uplink_mode": "AX.25",
    },
    "rx": {
        "zmq_port": 52001,
        "zmq_addr": "tcp://127.0.0.1:52001",
    },
    "general": {
        "version":      "4.3.1",
        "log_dir":      "logs",
        "generated_commands_dir": "generated_commands",
    },
}
```

Key changes:
- `nodes`, `ptypes`, `node_descriptions` → empty (mission provides them)
- `ax25` callsigns → `NOCALL` (mission provides real values)
- `csp` destination/ports → 0 (mission provides real values)
- `general` → no `mission_name`, `command_defs`, `decoder_yml`, `gs_node`, `rx_title`, `tx_title`, `splash_subtitle` (mission provides them)
- `tx.frequency` → empty (mission provides it)
- Platform-only settings retained: `zmq_addr`, `delay_ms`, `uplink_mode`, `log_dir`, `version`, `generated_commands_dir`

- [ ] **Step 2: Add `_merge_mission_metadata()` helper to `mission_adapter.py`**

Add this before `load_mission_adapter()`:

```python
def _merge_mission_metadata(cfg: dict, mission_meta: dict) -> None:
    """Merge mission.yml metadata into the runtime config dict in place.

    Mission metadata provides defaults. The operator's maveric_gss.yml
    values take precedence (they were already merged into cfg by
    load_gss_config).
    """
    for key in ("nodes", "ptypes", "node_descriptions", "ax25", "csp"):
        if key in mission_meta:
            existing = cfg.get(key, {})
            if isinstance(existing, dict) and existing:
                merged = dict(mission_meta[key])
                merged.update(existing)
                cfg[key] = merged
            else:
                cfg[key] = mission_meta[key]

    general = cfg.setdefault("general", {})
    if "mission_name" in mission_meta:
        general.setdefault("mission_name", mission_meta["mission_name"])
    if "gs_node" in mission_meta:
        general.setdefault("gs_node", mission_meta["gs_node"])
    if "command_defs" in mission_meta:
        general.setdefault("command_defs", mission_meta["command_defs"])

    ui = mission_meta.get("ui", {})
    for key in ("rx_title", "tx_title", "splash_subtitle"):
        if key in ui:
            general.setdefault(key, ui[key])

    tx_meta = mission_meta.get("tx", {})
    tx_cfg = cfg.setdefault("tx", {})
    for key in ("frequency", "uplink_mode"):
        if key in tx_meta:
            tx_cfg.setdefault(key, tx_meta[key])
```

- [ ] **Step 2: Add `load_mission_metadata()` function**

Add this after `_merge_mission_metadata()`:

```python
def load_mission_metadata(cfg: dict) -> dict:
    """Read mission.yml and merge metadata into cfg. Returns the raw metadata dict.

    Must be called BEFORE init_nodes() and load_command_defs() so those
    see mission-provided values (nodes, ptypes, command_defs path).

    If the mission package has no mission.yml, returns empty dict and
    continues without error.
    """
    import importlib
    import logging
    import os

    mission = cfg.get("general", {}).get("mission", "maveric")
    module_path = _MISSION_REGISTRY.get(mission)
    if module_path is None:
        return {}

    try:
        mission_pkg = importlib.import_module(module_path)
    except ImportError:
        return {}

    pkg_dir = os.path.dirname(os.path.abspath(mission_pkg.__file__))
    mission_yml_path = os.path.join(pkg_dir, "mission.yml")

    if not os.path.isfile(mission_yml_path):
        logging.debug("No mission.yml found for '%s' at %s", mission, mission_yml_path)
        return {}

    try:
        import yaml
        with open(mission_yml_path) as f:
            mission_meta = yaml.safe_load(f) or {}
    except Exception as exc:
        logging.warning("Could not read %s: %s", mission_yml_path, exc)
        return {}

    _merge_mission_metadata(cfg, mission_meta)
    return mission_meta
```

- [ ] **Step 3: Make `load_mission_adapter()` call `load_mission_metadata()` internally**

In `load_mission_adapter()`, add this line right after the `mission_name` assignment and before the registry lookup:

```python
    # Ensure mission metadata is merged (idempotent — safe if already called)
    load_mission_metadata(cfg)
```

This makes `load_mission_adapter()` safe for all callers (RxPipeline fallback, tests) without requiring them to call `load_mission_metadata()` separately.

- [ ] **Step 4: Update `load_mission_adapter()` startup logging**

Update the final logging line to include the schema path:

```python
    cmd_path = cfg.get("general", {}).get("command_defs", "")
    logging.info(
        "Mission loaded: %s [id=%s, adapter API v%d, schema=%s]",
        mission_name, mission, api_version, cmd_path,
    )
```

- [ ] **Step 5: Reorder `WebRuntime.__init__()` startup**

In `mav_gss_lib/web_runtime/state.py`, update imports:

```python
from mav_gss_lib.mission_adapter import load_mission_adapter, load_mission_metadata
```

Replace the init body:

```python
    def __init__(self) -> None:
        self.session_token = secrets.token_urlsafe(24)
        self.max_packets = MAX_PACKETS
        self.max_history = MAX_HISTORY
        self.max_queue = MAX_QUEUE

        self.cfg = load_gss_config()
        load_mission_metadata(self.cfg)    # merge mission.yml BEFORE init_nodes
        init_nodes(self.cfg)
        self.cmd_defs, self.cmd_warn = load_command_defs(get_command_defs_path(self.cfg))
        self.adapter = self._load_adapter()

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

- [ ] **Step 6: Update `missions/maveric/__init__.py` docstring**

```python
"""
mav_gss_lib.missions.maveric -- MAVERIC CubeSat Mission Implementation

Mission package contract:
  - ADAPTER_API_VERSION: int — adapter contract version
  - ADAPTER_CLASS: type — adapter class (MavericMissionAdapter)
  - mission.yml: mission metadata (nodes, ptypes, callsigns, schema path, UI labels)
  - adapter.py: MissionAdapter implementation
  - wire_format.py: command wire format, schema, node tables
  - imaging.py: image chunk reassembly
"""

ADAPTER_API_VERSION = 1

from mav_gss_lib.missions.maveric.adapter import MavericMissionAdapter as ADAPTER_CLASS  # noqa: F401
```

- [ ] **Step 7: Run tests — all should pass**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q
```

- [ ] **Step 8: Verify full startup**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -c "
from mav_gss_lib.web_runtime.state import WebRuntime
rt = WebRuntime()
print('adapter:', type(rt.adapter).__name__)
print('mission_name:', rt.cfg.get('general', {}).get('mission_name'))
print('nodes:', len(rt.cfg.get('nodes', {})))
print('gs_node:', rt.cfg.get('general', {}).get('gs_node'))
print('command_defs:', rt.cfg.get('general', {}).get('command_defs'))
print('ax25 src:', rt.cfg.get('ax25', {}).get('src_call'))
print('OK')
" 2>&1 | grep -v "^INFO:"
```

Expected: `mission_name: MAVERIC`, `nodes: 8`, `gs_node: GS`, `ax25 src: WM2XBB` — all from mission.yml.

- [ ] **Step 9: Commit (all changes atomic)**

```bash
git add mav_gss_lib/config.py mav_gss_lib/mission_adapter.py mav_gss_lib/web_runtime/state.py mav_gss_lib/missions/maveric/__init__.py
git commit -m "Narrow defaults, add mission metadata loading, reorder startup"
```

---

## Task 3: Add Config Validation Tests

**Files:**
- Create: `tests/test_ops_config_validation.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for mission config validation and startup diagnostics.

Verifies:
  1. mission.yml is read and merged correctly
  2. Missing mission.yml produces a warning but doesn't crash
  3. Config validation catches invalid mission configs
  4. Startup diagnostics include mission metadata
"""

import unittest
import sys
import os
import logging
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.config import load_gss_config
from mav_gss_lib.mission_adapter import (
    load_mission_adapter,
    _merge_mission_metadata,
    _MISSION_REGISTRY,
    MissionAdapter,
)
from mav_gss_lib.protocol import init_nodes, load_command_defs
from mav_gss_lib.config import get_command_defs_path


class TestMissionYml(unittest.TestCase):
    """Verify mission.yml reading and merging."""

    def test_maveric_mission_yml_exists(self):
        """MAVERIC mission.yml is present in the package directory."""
        from mav_gss_lib.missions import maveric
        pkg_dir = os.path.dirname(os.path.abspath(maveric.__file__))
        yml_path = os.path.join(pkg_dir, "mission.yml")
        self.assertTrue(os.path.isfile(yml_path), f"Expected {yml_path} to exist")

    def test_maveric_mission_yml_has_required_fields(self):
        """MAVERIC mission.yml contains required metadata fields."""
        import yaml
        from mav_gss_lib.missions import maveric
        pkg_dir = os.path.dirname(os.path.abspath(maveric.__file__))
        with open(os.path.join(pkg_dir, "mission.yml")) as f:
            data = yaml.safe_load(f)
        self.assertIn("mission_name", data)
        self.assertIn("nodes", data)
        self.assertIn("ptypes", data)
        self.assertIn("command_defs", data)
        self.assertEqual(data["mission_name"], "MAVERIC")

    def test_merge_fills_missing_keys(self):
        """_merge_mission_metadata fills keys absent from cfg."""
        cfg = {"general": {}}
        meta = {
            "mission_name": "TEST",
            "nodes": {0: "NONE", 1: "CPU"},
            "gs_node": "CPU",
        }
        _merge_mission_metadata(cfg, meta)
        self.assertEqual(cfg["nodes"], {0: "NONE", 1: "CPU"})
        self.assertEqual(cfg["general"]["mission_name"], "TEST")
        self.assertEqual(cfg["general"]["gs_node"], "CPU")

    def test_merge_does_not_override_operator_config(self):
        """Operator config values take precedence over mission.yml."""
        cfg = {
            "general": {"mission_name": "OPERATOR_NAME"},
            "nodes": {0: "ZERO", 99: "CUSTOM"},
        }
        meta = {
            "mission_name": "MISSION_NAME",
            "nodes": {0: "NONE", 1: "CPU"},
        }
        _merge_mission_metadata(cfg, meta)
        # Operator values win
        self.assertEqual(cfg["general"]["mission_name"], "OPERATOR_NAME")
        self.assertEqual(cfg["nodes"][0], "ZERO")
        self.assertEqual(cfg["nodes"][99], "CUSTOM")
        # Mission fills gaps
        self.assertEqual(cfg["nodes"][1], "CPU")


class TestStartupDiagnostics(unittest.TestCase):
    """Verify startup logging includes mission metadata."""

    def test_startup_log_includes_mission_info(self):
        """load_mission_adapter() logs mission name, id, API version."""
        from mav_gss_lib.mission_adapter import load_mission_metadata
        cfg = load_gss_config()
        load_mission_metadata(cfg)
        init_nodes(cfg)
        cmd_defs, _ = load_command_defs(get_command_defs_path(cfg))

        with self.assertLogs(level=logging.INFO) as cm:
            load_mission_adapter(cfg, cmd_defs)

        log_output = "\n".join(cm.output)
        self.assertIn("Mission loaded", log_output)
        self.assertIn("MAVERIC", log_output)
        self.assertIn("adapter API v1", log_output)

    def test_missing_mission_yml_does_not_crash(self):
        """A mission with no mission.yml still loads (with warning)."""
        _MISSION_REGISTRY["echo_test"] = "tests.echo_mission"
        try:
            cfg = {"general": {"mission": "echo_test"}}
            adapter = load_mission_adapter(cfg, {})
            self.assertIsInstance(adapter, MissionAdapter)
        finally:
            del _MISSION_REGISTRY["echo_test"]


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new tests**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/test_ops_config_validation.py -v
```

- [ ] **Step 3: Run full test suite**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -v

cd "/Users/irfan/Documents/MAVERIC GSS"
python3 -m pytest tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_ops_config_validation.py
git commit -m "Add config validation and mission.yml tests"
```

---

## Task 4: Final Verification

- [ ] **Step 1: Verify full startup with narrowed defaults**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -c "
import logging
logging.basicConfig(level=logging.INFO)
from mav_gss_lib.web_runtime.state import WebRuntime
rt = WebRuntime()
cfg = rt.cfg
print()
print('=== Mission Config Summary ===')
print('mission:', cfg.get('general', {}).get('mission', 'maveric'))
print('mission_name:', cfg.get('general', {}).get('mission_name'))
print('nodes:', len(cfg.get('nodes', {})))
print('ptypes:', len(cfg.get('ptypes', {})))
print('gs_node:', cfg.get('general', {}).get('gs_node'))
print('command_defs:', cfg.get('general', {}).get('command_defs'))
print('ax25 src:', cfg.get('ax25', {}).get('src_call'))
print('frequency:', cfg.get('tx', {}).get('frequency'))
print('adapter:', type(rt.adapter).__name__)
print('OK')
" 2>&1
```

Expected: All MAVERIC values present (from mission.yml merge), adapter loads correctly.

- [ ] **Step 2: Run both test suites**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -v

cd "/Users/irfan/Documents/MAVERIC GSS"
python3 -m pytest tests/ -v
```

- [ ] **Step 3: Verify web frontend still builds**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE/mav_gss_lib/web"
npm run build
```

- [ ] **Step 4: Commit**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
git add -A
git commit -m "Phase 8 complete: mission.yml created, config narrowed, validation tests added"
```

---

## Post-Phase 8 State

**What was added:**
- `missions/maveric/mission.yml` — MAVERIC mission metadata (nodes, ptypes, descriptions, callsigns, command schema path, UI labels)
- `_merge_mission_metadata()` — merges mission.yml into runtime config
- `load_mission_metadata()` reads mission.yml and merges metadata into runtime config
- `load_mission_adapter()` defensively calls `load_mission_metadata()` and logs enhanced diagnostics
- 6 config validation tests (mission.yml existence, required fields, merge behavior, operator override, startup diagnostics, missing yml tolerance)

**What changed:**
- `config.py` `_DEFAULTS` narrowed to platform-only settings (empty nodes/ptypes, NOCALL callsigns, no mission name)
- Mission-specific defaults now come from `mission.yml`, not hardcoded platform defaults
- Startup log line includes mission id, API version, and schema path
- `command_defs` may now come from mission metadata, but path resolution still follows the existing config resolver rules in v1

**What did NOT change:**
- Operator config file (`maveric_gss.yml`) — still works, still overrides mission defaults
- Frontend — no changes
- Restart-required enforcement — already in place from Phase 5a
