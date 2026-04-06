# Phase 5a: Backend Rendering Contracts

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move MAVERIC-specific JSON rendering out of platform runtime code and into the MAVERIC adapter, and inject the adapter via config in `WebRuntime` instead of hardcoding `MavericMissionAdapter`.

**Architecture:** Add three temporary compatibility methods to `MavericMissionAdapter` that produce the JSON shapes the current frontend expects. The platform runtime delegates to these instead of inlining MAVERIC field mapping. These methods are NOT the architecture spec's rendering-slot contract (columns, semantic blocks, protocol blocks, integrity blocks) — they are transitional shims that preserve the current frontend JSON while moving MAVERIC logic out of platform code. Phase 5b will replace them with the spec's actual rendering-slot model. Adapter selection scope is limited to `WebRuntime` — the non-web `RxPipeline` path is not changed.

**Tech Stack:** Python 3.10+, FastAPI, PyYAML

---

## Design Decisions

1. **Frontend JSON shape does NOT change.** The adapter methods produce the exact same JSON the frontend already consumes. Phase 5b will make the frontend dynamic.

2. **Adapter gains three temporary compatibility methods.** These are NOT the architecture spec's rendering-slot contract. They are transitional shims that produce the current frontend's expected JSON shape while moving MAVERIC logic out of platform code. Phase 5b will replace them with the spec's actual model (columns, semantic blocks, protocol blocks, integrity blocks).
   - `packet_to_json(pkt) -> dict` — RX packet → current frontend JSON shape
   - `queue_item_to_json(item, match_fn, extra_fn) -> dict` — TX queue item → current frontend JSON shape
   - `history_entry(count, item, payload_len) -> dict` — sent command → current history JSON shape

3. **`node_name` / `ptype_name` imports are removed from `services.py`.** The adapter owns label resolution. The platform runtime no longer needs to know about nodes or ptypes.

4. **Mission selection via `general.mission` config (WebRuntime only).** `WebRuntime.__init__()` looks up `general.mission` (default: `"maveric"`) and instantiates the corresponding adapter. For v1, only `"maveric"` is supported. Unknown values raise a clear error at startup. Note: the non-web `RxPipeline` path still receives its adapter via constructor injection and is not changed by this plan.

5. **`parse_cmd_line` and `resolve_node/ptype` remain imported in `tx.py` and `api.py` for now.** TX command parsing is deeply MAVERIC-specific. Phase 5b will address the TX side when the frontend CommandBuilder becomes adapter-driven.

## File Plan

| Action | File | Change |
|---|---|---|
| — | `mav_gss_lib/mission_adapter.py` | No Phase 5a change (transitional methods go on concrete adapter only) |
| Modify | `mav_gss_lib/missions/maveric/adapter.py` | Implement rendering methods |
| Modify | `mav_gss_lib/web_runtime/services.py` | Delegate `packet_to_json`, `queue_items_json`, history to adapter |
| Modify | `mav_gss_lib/web_runtime/state.py` | Mission selection via config instead of hardcoded adapter |

## Test Commands

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -v

cd "/Users/irfan/Documents/MAVERIC GSS"
python3 -m pytest tests/ -v
```

---

## Task 1: No Changes to MissionAdapter Protocol

The three rendering methods (`packet_to_json`, `queue_item_to_json`, `history_entry`) are **transitional compatibility shims** that produce the current frontend's MAVERIC-shaped JSON. They do NOT belong on the core `MissionAdapter` Protocol because they bake in MAVERIC field assumptions (`src`, `dest`, `echo`, `ptype`, `cmd`, `args`).

Instead, they are added only to `MavericMissionAdapter` in Task 2. The platform runtime accesses them via the concrete adapter instance, not through the Protocol. The Protocol will gain the spec's actual rendering-slot methods (`packet_list_columns`, `packet_list_row`, `packet_detail_blocks`, `protocol_blocks`, `integrity_blocks`) in Phase 5b.

**No files changed. No commit needed. Proceed to Task 2.**

---

## Task 2: Implement Rendering Methods in MAVERIC Adapter

**Files:**
- Modify: `mav_gss_lib/missions/maveric/adapter.py`

- [ ] **Step 1: Add imports**

At the top of `mav_gss_lib/missions/maveric/adapter.py`, add to the `wire_format` import:

```python
from mav_gss_lib.missions.maveric.wire_format import (
    GS_NODE,
    apply_schema,
    build_cmd_raw,
    try_parse_command,
    validate_args,
    node_name,
    ptype_name,
)
```

- [ ] **Step 2: Add `packet_to_json` method**

Add this method to `MavericMissionAdapter`, after `validate_tx_args`:

```python
    def packet_to_json(self, pkt) -> dict:
        """Convert a Packet record to the JSON shape the frontend expects."""
        cmd = pkt.cmd
        args_named = []
        args_extra = []
        if cmd and cmd.get("schema_match") and cmd.get("typed_args"):
            for ta in cmd["typed_args"]:
                val = ta.get("value", "")
                if ta["type"] == "epoch_ms":
                    if hasattr(val, "ms"):
                        val = val.ms
                    elif isinstance(val, dict) and "ms" in val:
                        val = val["ms"]
                if isinstance(val, (bytes, bytearray)):
                    val = val.hex()
                args_named.append({
                    "name": ta["name"],
                    "value": str(val),
                    "important": bool(ta.get("important")),
                })
            args_extra = [
                a.hex() if isinstance(a, (bytes, bytearray)) else str(a)
                for a in cmd.get("extra_args", [])
            ]
        elif cmd:
            raw_args = cmd.get("args", [])
            if isinstance(raw_args, list):
                args_extra = [str(a) for a in raw_args]
            else:
                args_extra = [str(raw_args)] if raw_args else []

        payload = {
            "num": pkt.pkt_num,
            "time": pkt.gs_ts_short,
            "time_utc": pkt.gs_ts,
            "frame": pkt.frame_type,
            "src": node_name(cmd["src"]) if cmd else "",
            "dest": node_name(cmd["dest"]) if cmd else "",
            "echo": node_name(cmd["echo"]) if cmd else "",
            "ptype": ptype_name(cmd["pkt_type"]) if cmd else "",
            "cmd": cmd["cmd_id"] if cmd else "",
            "args_named": args_named,
            "args_extra": args_extra,
            "size": len(pkt.raw),
            "crc16_ok": cmd.get("crc_valid") if cmd else None,
            "crc32_ok": pkt.crc_status.get("csp_crc32_valid"),
            "is_echo": pkt.is_uplink_echo,
            "is_dup": pkt.is_dup,
            "is_unknown": pkt.is_unknown,
            "raw_hex": pkt.raw.hex(),
            "warnings": pkt.warnings,
            "csp_header": pkt.csp,
            "ax25_header": pkt.stripped_hdr,
        }
        if pkt.ts_result:
            dt_utc, dt_local, ms = pkt.ts_result
            payload["sat_time_utc"] = dt_utc.strftime("%H:%M:%S") + " UTC" if dt_utc else None
            payload["sat_time_local"] = dt_local.strftime("%H:%M:%S %Z") if dt_local else None
            payload["sat_time_ms"] = ms
        return payload
```

- [ ] **Step 3: Add `queue_item_to_json` method**

```python
    def queue_item_to_json(self, item: dict, match_tx_args, extra_tx_args) -> dict:
        """Convert a TX queue command item to the JSON shape the frontend expects."""
        return {
            "type": "cmd",
            "num": item.get("num", 0),
            "src": node_name(item["src"]),
            "dest": node_name(item["dest"]),
            "echo": node_name(item["echo"]),
            "ptype": ptype_name(item["ptype"]),
            "cmd": item["cmd"],
            "args": item.get("args", ""),
            "args_named": match_tx_args(item["cmd"], item.get("args", "")),
            "args_extra": extra_tx_args(item["cmd"], item.get("args", "")),
            "guard": item.get("guard", False),
            "size": len(item.get("raw_cmd", b"")),
        }
```

- [ ] **Step 4: Add `history_entry` method**

```python
    def history_entry(self, count: int, item: dict, payload_len: int) -> dict:
        """Build a sent-command history entry for the frontend."""
        from datetime import datetime
        return {
            "n": count,
            "ts": datetime.now().strftime("%H:%M:%S"),
            "src": node_name(item["src"]),
            "dest": node_name(item["dest"]),
            "echo": node_name(item["echo"]),
            "ptype": ptype_name(item["ptype"]),
            "cmd": item["cmd"],
            "args": item.get("args", ""),
            "size": payload_len,
        }
```

- [ ] **Step 5: Smoke test**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -c "
from mav_gss_lib.mission_adapter import MissionAdapter, MavericMissionAdapter
from mav_gss_lib.missions.maveric.wire_format import init_nodes
cfg = {'nodes': {0: 'NONE', 2: 'EPS', 6: 'GS'}, 'ptypes': {1: 'CMD'}, 'general': {'gs_node': 'GS'}}
init_nodes(cfg)
adapter = MavericMissionAdapter(cmd_defs={})
print('isinstance:', isinstance(adapter, MissionAdapter))
# Verify methods exist
assert hasattr(adapter, 'packet_to_json')
assert hasattr(adapter, 'queue_item_to_json')
assert hasattr(adapter, 'history_entry')
print('OK')
"
```

- [ ] **Step 6: Run full test suite**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -v

cd "/Users/irfan/Documents/MAVERIC GSS"
python3 -m pytest tests/ -v
```

- [ ] **Step 7: Commit**

```bash
git add mav_gss_lib/missions/maveric/adapter.py
git commit -m "Implement rendering methods in MavericMissionAdapter"
```

---

## Task 3: Delegate `packet_to_json` in RxService

**Files:**
- Modify: `mav_gss_lib/web_runtime/services.py`

- [ ] **Step 1: Replace `RxService.packet_to_json` body**

Replace the entire `packet_to_json` method (lines 99–150) with:

```python
    def packet_to_json(self, pkt) -> dict:
        return self.runtime.adapter.packet_to_json(pkt)
```

- [ ] **Step 2: Replace `TxService.queue_items_json` body**

Replace the `queue_items_json` method (lines 359–382) with:

```python
    def queue_items_json(self):
        """Project the current queue into the websocket/API JSON shape."""
        result = []
        for item in self.queue:
            if item["type"] == "delay":
                result.append({"type": "delay", "delay_ms": item["delay_ms"]})
                continue
            result.append(
                self.runtime.adapter.queue_item_to_json(
                    item, self.match_tx_args, self.tx_extra_args,
                )
            )
        return result
```

- [ ] **Step 3: Replace history entry construction in `run_send`**

In `TxService.run_send()`, find the `hist_entry = {...}` line (line 528) and replace it with:

```python
                hist_entry = self.runtime.adapter.history_entry(self.count, item, len(payload))
```

- [ ] **Step 4: Clean up unused imports**

In the imports at the top of `services.py` (line 31), change:

```python
from mav_gss_lib.protocol import node_name, parse_cmd_line, ptype_name, resolve_node, resolve_ptype
```

to:

```python
from mav_gss_lib.protocol import parse_cmd_line, resolve_node, resolve_ptype
```

Remove `node_name` and `ptype_name` — they are no longer used directly in this file.

Also remove the unused `from datetime import datetime` if it becomes unused (check: it may still be used elsewhere in the file). Keep `import mav_gss_lib.protocol as protocol` — it is still used.

- [ ] **Step 5: Run full test suite**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -v

cd "/Users/irfan/Documents/MAVERIC GSS"
python3 -m pytest tests/ -v
```

Expected: All 68 tests pass. The JSON output is identical — we moved the logic, not changed it.

- [ ] **Step 6: Commit**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
git add mav_gss_lib/web_runtime/services.py
git commit -m "Delegate packet/queue/history JSON rendering to adapter"
```

---

## Task 4: Mission Selection via Config

**Files:**
- Modify: `mav_gss_lib/web_runtime/state.py`

- [ ] **Step 1: Replace hardcoded adapter instantiation**

In `WebRuntime.__init__()` (line 60), replace:

```python
        self.adapter = MavericMissionAdapter(self.cmd_defs)
```

with:

```python
        self.adapter = self._load_adapter()
```

Add the `_load_adapter` method to `WebRuntime`:

```python
    def _load_adapter(self):
        """Instantiate the mission adapter based on config."""
        mission = self.cfg.get("general", {}).get("mission", "maveric")
        if mission == "maveric":
            return MavericMissionAdapter(self.cmd_defs)
        raise ValueError(
            f"Unknown mission '{mission}' in general.mission config. "
            f"Supported: maveric"
        )
```

- [ ] **Step 2: Verify it still works with default config**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -c "
from mav_gss_lib.web_runtime.state import WebRuntime
rt = WebRuntime()
print('adapter type:', type(rt.adapter).__name__)
print('OK')
"
```

Expected: `adapter type: MavericMissionAdapter`, `OK`.

- [ ] **Step 3: Verify unknown mission raises error**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -c "
from mav_gss_lib.web_runtime.state import WebRuntime
from mav_gss_lib.config import load_gss_config
import mav_gss_lib.web_runtime.state as st
# Monkey-patch to test unknown mission
orig = st.load_gss_config
def patched(path=None):
    cfg = orig(path)
    cfg['general']['mission'] = 'unknown_mission'
    return cfg
st.load_gss_config = patched
try:
    rt = WebRuntime()
    print('ERROR: should have raised')
except ValueError as e:
    print('Correctly raised:', e)
finally:
    st.load_gss_config = orig
"
```

Expected: `Correctly raised: Unknown mission 'unknown_mission'...`

- [ ] **Step 4: Run full test suite**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -v

cd "/Users/irfan/Documents/MAVERIC GSS"
python3 -m pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
git add mav_gss_lib/web_runtime/state.py
git commit -m "Select mission adapter via general.mission config (WebRuntime only)"
```

---

## Task 5: Final Verification

- [ ] **Step 1: Verify adapter rendering produces valid JSON**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -c "
import json
from mav_gss_lib.web_runtime.state import WebRuntime
rt = WebRuntime()
# Build a test queue item
from mav_gss_lib.web_runtime.runtime import make_cmd
item = make_cmd(6, 2, 0, 1, 'ping', '', runtime=rt)
item['num'] = 1
# Test queue_item_to_json
result = rt.adapter.queue_item_to_json(item, rt.tx.match_tx_args, rt.tx.tx_extra_args)
print('queue JSON:', json.dumps(result, indent=2))
# Test history_entry
hist = rt.adapter.history_entry(1, item, 42)
print('history JSON:', json.dumps(hist, indent=2))
print('OK')
"
```

- [ ] **Step 2: Run both test suites**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -v

cd "/Users/irfan/Documents/MAVERIC GSS"
python3 -m pytest tests/ -v
```

- [ ] **Step 3: Verify no `node_name`/`ptype_name` in services.py**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
grep -n "node_name\|ptype_name" mav_gss_lib/web_runtime/services.py || echo "CLEAN: no node_name/ptype_name in services.py"
```

Expected: `CLEAN` — these are now in the adapter only.

- [ ] **Step 4: Commit**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
git add -A
git commit -m "Phase 5a complete: backend rendering contracts delegated to adapter"
```

---

## Post-Phase 5a State

**What changed:**
- `MavericMissionAdapter` has 3 new transitional rendering methods (NOT on core Protocol)
- `RxService.packet_to_json()` delegates to adapter
- `TxService.queue_items_json()` delegates to adapter
- `TxService.run_send()` history entry delegates to adapter
- `WebRuntime` selects adapter via `general.mission` config (WebRuntime only — non-web paths unchanged)
- `node_name` / `ptype_name` removed from `services.py` imports

**What did NOT change:**
- `MissionAdapter` Protocol (no new methods — transitional shims are on the concrete adapter only)
- Frontend (still receives the same JSON)
- Non-web `RxPipeline` adapter injection (still via constructor)
- TX command parsing (`parse_cmd_line`, `resolve_node/ptype` still used in `tx.py`, `api.py`)
- Log entry normalization in `api.py` (deferred to Phase 5b)
- Import file parsing in `api.py` (deferred to Phase 5b)

**What Phase 5b will do:**
- Add the architecture spec's actual rendering-slot methods to `MissionAdapter` Protocol (`packet_list_columns`, `packet_list_row`, `packet_detail_blocks`, `protocol_blocks`, `integrity_blocks`)
- Make the frontend consume adapter-provided columns and rendering slots dynamically
- Replace the Phase 5a transitional rendering methods with the spec contract
- Move TX command parsing behind the adapter
- Move log normalization behind the adapter
