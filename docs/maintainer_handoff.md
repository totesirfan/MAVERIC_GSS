# Maintainer Handoff

This document covers what a new maintainer needs to know to run, modify, and extend MAVERIC GSS.

## Boot Path

`MAV_WEB.py` is the only entry point. Here is the exact startup sequence:

```
MAV_WEB.py
 └─ load_gss_config()                    reads mav_gss_lib/gss.yml + defaults
 └─ create_app()
     └─ WebRuntime()
         ├─ load_mission_adapter(cfg)
         │   ├─ load_mission_metadata()   reads mission.yml or mission.example.yml → merges into cfg
         │   ├─ init_mission(cfg)         populates node tables, loads commands.yml
         │   └─ MavericMissionAdapter()   instantiated with cmd_defs
         ├─ CSPConfig + AX25Config        from merged config
         └─ RxService + TxService         with adapter reference
     └─ FastAPI lifespan startup
         ├─ load TX queue from .pending_queue.jsonl
         ├─ init ZMQ PUB socket (TX)
         ├─ create SessionLog (RX) + TXLog (TX)
         ├─ start RX receiver thread (ZMQ SUB)
         └─ start async broadcast loop (RX → WebSocket)
 └─ uvicorn.run(127.0.0.1:8080)
```

## Required Local Files

| File | Path | Source | Notes |
|------|------|--------|-------|
| Station config | `mav_gss_lib/gss.yml` | Copy from `gss.example.yml` | ZMQ addresses, log dir, version |
| Command schema | `mav_gss_lib/missions/maveric/commands.yml` | Provided separately | Gitignored for security |
| Mission metadata override | `mav_gss_lib/missions/maveric/mission.yml` | Optional local file | Overrides tracked `mission.example.yml` when present |

If `gss.yml` is missing, hardcoded defaults in `config.py` are used. If `commands.yml` is missing, the system starts but TX validation and command builder are disabled. If `mission.yml` is missing, the runtime falls back to the tracked `mission.example.yml`.

### Config Merge Order

1. `_DEFAULTS` dict in `config.py` (platform defaults)
2. `mav_gss_lib/gss.yml` (operator overrides, deep-merged)
3. `missions/<mission>/mission.yml` if present, otherwise `mission.example.yml` (mission defaults via `setdefault` — operator values win)

The final merged dict is `runtime.cfg` and is served to the frontend at `GET /api/config`.

## GNU Radio Integration

The flowgraph must be running before MAV_WEB starts. Connection uses two ZMQ sockets:

- **RX:** ZMQ SUB at `tcp://127.0.0.1:52001` — receives decoded PDUs from GNU Radio
- **TX:** ZMQ PUB at `tcp://127.0.0.1:52002` — publishes framed uplink payloads

PDUs are serialized using PMT (GNU Radio's polymorphic type system). The `transport.py` module handles PMT encoding/decoding, socket setup, and connection monitoring.

ZMQ addresses are configurable in `gss.yml` under `rx.zmq_addr` and `tx.zmq_addr`.

## Web Runtime Structure

```
web_runtime/
    state.py      WebRuntime class — owns all mutable backend state
    app.py        FastAPI factory, lifespan (startup/shutdown), static file serving
    runtime.py    Queue helpers: make_mission_cmd, make_delay, validate_mission_cmd, sanitize_queue_items
    api.py        REST routes: /api/status, /api/config, /api/schema, /api/columns, /api/tx-columns, /api/logs, /api/selfcheck
    rx.py         RX WebSocket handler (clients receive live packets)
    tx.py         TX WebSocket handler (queue mutations, send control)
    services.py   RxService (ZMQ SUB → pipeline → broadcast) + TxService (queue + send loop)
    security.py   Session token validation
```

### Thread Model

- **Main thread:** asyncio event loop (uvicorn + FastAPI)
- **RX receiver thread:** blocking ZMQ SUB recv loop, puts (meta, raw) into a queue
- **Broadcast loop:** async task drains the queue, runs pipeline, broadcasts to WebSocket clients
- **TX send loop:** async task runs during queue send (delay handling, guard confirmation)

Thread safety: `cfg_lock` for config updates, `tx_send_lock` for queue mutations during send.

## Mission Adapter Contract

A mission package lives under `mav_gss_lib/missions/<name>/` and must provide:

### Package `__init__.py`

```python
ADAPTER_API_VERSION = 1              # Contract version (only 1 supported)
ADAPTER_CLASS = MyMissionAdapter     # Class satisfying MissionAdapter protocol

def init_mission(cfg: dict) -> dict:
    """Called after metadata merge. Return {"cmd_defs": dict, "cmd_warn": str|None}."""
```

### `mission.example.yml`

Tracked public-safe mission metadata merged into platform config at startup:

```yaml
mission_name: MyMission
nodes:
  0: NODE_A
  1: NODE_B
ptypes:
  1: CMD
  2: RES
gs_node: NODE_A
command_defs: commands.yml
ui:
  rx_title: Downlink
  tx_title: Uplink
```

### Optional local `mission.yml`

If present beside `mission.example.yml`, this local file is loaded instead of the tracked example. Use it for mission metadata that should not live in the public repository.

### `adapter.py`

Must satisfy the `MissionAdapter` Protocol defined in `mission_adapter.py`. Required methods:

**RX path:**
- `detect_frame_type(meta)` → frame type string
- `normalize_frame(frame_type, raw)` → (inner_payload, stripped_header, warnings)
- `parse_packet(inner_payload, warnings)` → `ParsedPacket`
- `duplicate_fingerprint(parsed)` → hashable tuple or None
- `is_uplink_echo(cmd)` → bool

**TX path:**
- `build_raw_command(src, dest, echo, ptype, cmd_id, args)` → bytes
- `validate_tx_args(cmd_id, args)` → (ok, errors)
- `parse_cmd_line(line)` → (src, dest, echo, ptype, cmd, args)
- `cmd_line_to_payload(line)` → payload dict for `build_tx_command`
- `build_tx_command(payload)` → `{raw_cmd, display, guard}` (optional TX plugin)
- `tx_queue_columns()` → column definitions for TX queue/history

**Rendering slots (UI):**
- `packet_list_columns()` → column definitions for the RX table
- `packet_list_row(pkt)` → column values for one packet
- `packet_detail_blocks(pkt)` → detail view blocks
- `protocol_blocks(pkt)` → protocol header blocks
- `integrity_blocks(pkt)` → CRC/integrity check blocks

**Resolution:**
- `gs_node` property, `node_name()`, `ptype_name()`, `node_label()`, `ptype_label()`
- `resolve_node(s)`, `resolve_ptype(s)`

**Logging:**
- `build_log_mission_data(pkt)` → dict for JSONL envelope
- `format_log_lines(pkt)` → list of text log lines
- `is_unknown_packet(parsed)` → bool

### `commands.yml`

Command schema with per-command definitions: `tx_args`, `rx_args`, routing defaults, `rx_only`, `variadic`, `nodes`.

See `mav_gss_lib/missions/template/` for a minimal working example.

## RX/TX Rendering Contract

The platform owns WebSocket serialization. Mission adapters provide structured rendering data — the platform renders it generically.

**RX packets:** Platform serializes envelope fields (`num`, `time`, `frame`, `size`, `raw_hex`, `warnings`, `is_echo`, `is_dup`, `is_unknown`) and attaches `_rendering` from the adapter's rendering-slot methods. `_rendering` contains `row` (column-keyed values), `detail_blocks`, `protocol_blocks`, and `integrity_blocks`.

**TX queue/history:** All queue items are `mission_cmd` type. The platform serializes `display` metadata from the adapter's `build_tx_command()`: `display.row` (column-keyed values), `display.detail_blocks` (structured blocks for expanded view), `display.title`, `display.subtitle`. The adapter also provides `tx_queue_columns()` with column definitions and `hide_if_all` auto-hide metadata.

**Log viewer:** RX entries pass `_rendering` through from the stored log. TX entries build `_rendering` from persisted `display`. Both use the same column-driven `CellValue` rendering. RX uses `/api/columns`, TX uses `/api/tx-columns`.

### TX Command Model

The platform owns queue mechanics (persistence, send loop, guard, delay). The mission adapter owns command semantics:

- `cmd_line_to_payload(line)` — converts raw CLI text to a mission payload dict
- `build_tx_command(payload)` — validates, encodes, returns `{raw_cmd, display, guard}`
- `tx_queue_columns()` — column definitions for queue/history rendering

The platform does not assume any universal command field structure. Duplicate/requeue re-submits the original `payload` through `build_tx_command`, preserving all routing context.

## Config Sidebar and Log Viewer

Both are lazy-loaded React components (`React.lazy` + `Suspense`). They fetch data from:

- `GET /api/config` — full merged config dict
- `GET /api/status` — runtime status (version, ZMQ states, log paths)
- `GET /api/logs` — session list from `logs/json/*.jsonl`
- `GET /api/logs/{session_id}` — parsed log entries for replay

### Cache Behavior

`index.html` is served with `Cache-Control: no-cache` to prevent stale asset hash references after rebuilds. Hashed `.js`/`.css` files under `/assets/` cache normally.

## Extending for a New Mission

1. Create `mav_gss_lib/missions/<name>/` with `__init__.py`, `mission.example.yml`, `adapter.py`, `commands.yml`
2. Use `mav_gss_lib/missions/template/` as a starting point
3. Set `general.mission` in `gss.yml` to the package name (defaults to `maveric`)

Mission packages are discovered by convention — any importable package at `mav_gss_lib.missions.<name>` is automatically found. No platform core edits required.

What stays the same: transport, web runtime, logging, UI shell, protocol support modules.

What changes: adapter methods (parsing, encoding, rendering), mission metadata (`mission.example.yml` and optional local `mission.yml`), commands.yml (command schema).

## Testing

```bash
pytest -q                                                  # Full suite
pytest tests/test_ops_mission_boundary.py -q               # Adapter contract tests
MAVERIC_FULL_GR=1 pytest tests/test_ops_golay_path.py -q   # GNU Radio end-to-end (opt-in)
```

The echo mission adapter in `tests/echo_mission.py` validates that a non-MAVERIC adapter can satisfy the full protocol.
