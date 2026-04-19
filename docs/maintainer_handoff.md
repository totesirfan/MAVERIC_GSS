# Maintainer Handoff

This document covers what a new maintainer needs to know to run, modify, and extend MAVERIC GSS.

## Boot path

`MAV_WEB.py` is the only entry point. Here is the exact startup sequence:

```
MAV_WEB.py
 └─ bootstrap_dependencies()             updater.py — zip auto-heal + self-install missing deps
 └─ create_app()                         web_runtime/app.py
     └─ create_runtime()                 web_runtime/state.py
         └─ WebRuntime.__init__()
             ├─ load_gss_config()         reads mav_gss_lib/gss.yml + defaults
             ├─ load_mission_adapter(cfg)
             │   ├─ load_mission_metadata() reads mission.yml or mission.example.yml → merges into cfg
             │   ├─ init_mission(cfg)     populates node tables, loads commands.yml, builds ImageAssembler
             │   └─ MavericMissionAdapter() instantiated with cmd_defs + nodes + image_assembler
             ├─ CSPConfig + AX25Config    from merged config
             └─ RxService + TxService     with adapter reference
     ├─ app.include_router(api, rx, tx, session_ws, preflight_ws)
     └─ get_plugin_routers(adapter, config_accessor)  → auto-mount mission plugin routers
 └─ uvicorn.run(127.0.0.1:8080)
     └─ FastAPI lifespan startup
         ├─ load TX queue from .pending_queue.jsonl
         ├─ init ZMQ PUB socket (TX)
         ├─ create SessionLog (RX) + TXLog (TX)
         ├─ start RX receiver thread (ZMQ SUB)
         ├─ start async broadcast loop (RX → WebSocket)
         ├─ schedule_update_check()       async updater check (web_runtime/update_ws.py)
         └─ run_preflight_and_broadcast() async preflight check (web_runtime/preflight_ws.py)
```

Note: `load_gss_config()` is called inside `WebRuntime.__init__`, not at module top. The module-level `CFG = load_gss_config()` in `MAV_WEB.py` is unused bookkeeping for the console banner only.

## Required local files

| File | Path | Source | Notes |
|------|------|--------|-------|
| Station config | `mav_gss_lib/gss.yml` | Copy from `gss.example.yml` | ZMQ addresses, log dir, version |
| Command schema | `mav_gss_lib/missions/maveric/commands.yml` | Provided separately | Gitignored for security |
| Mission metadata override | `mav_gss_lib/missions/maveric/mission.yml` | Optional local file | Overrides tracked `mission.example.yml` when present |

If `gss.yml` is missing, hardcoded defaults in `config.py` are used. If `commands.yml` is missing, the MAVERIC mission starts but command schema validation is unavailable. If `mission.yml` is missing, the runtime falls back to the tracked `mission.example.yml`.

### Config merge order

1. `_DEFAULTS` dict in `config.py` (platform defaults)
2. `mav_gss_lib/gss.yml` (operator overrides, deep-merged)
3. `missions/<mission>/mission.yml` if present, otherwise `mission.example.yml` (scalar `general` / `tx` / `ui` defaults via `setdefault`; block keys `ax25`, `csp`, `nodes`, `ptypes`, `node_descriptions`, `imaging` merge operator values over mission base — see `_merge_mission_metadata` in `mission_adapter.py`)

The final merged dict is `runtime.cfg` and is served to the frontend at `GET /api/config`.

## GNU Radio integration

The flowgraph must be running before MAV_WEB starts. Connection uses two ZMQ sockets:

- **RX:** ZMQ SUB at `tcp://127.0.0.1:52001` — receives decoded PDUs from GNU Radio
- **TX:** ZMQ PUB at `tcp://127.0.0.1:52002` — publishes framed uplink payloads

PDUs are serialized using PMT (GNU Radio's polymorphic type system). The `transport.py` module handles PMT encoding/decoding, socket setup, and connection monitoring.

ZMQ addresses are configurable in `gss.yml` under `rx.zmq_addr` and `tx.zmq_addr`.

## Web runtime structure

```
web_runtime/
    state.py         WebRuntime class — owns all mutable backend state, tx_status as AtomicStatus
    app.py           FastAPI factory, lifespan, static file serving, plugin router auto-mount
    shutdown.py      Delayed-shutdown helpers (SHUTDOWN_DELAY = 2, check_shutdown, schedule_shutdown_check)
    tx_context.py    Send-context snapshot helper (build_send_context)
    _atomics.py      AtomicStatus primitive — thread-safe string status holder (.get()/.set(), non-hashable)
    _broadcast.py    broadcast_safe helper — drops dead WS clients
    _task_utils.py   log_task_exception — shared done-callback for background asyncio tasks
    _ws_utils.py     Small helpers shared across WebSocket handlers (send_phase_fail, etc.)
    api/             REST routes package
      config.py      /api/status, /api/config, /api/selfcheck
      schema.py      /api/schema, /api/columns, /api/tx-columns, /api/tx/capabilities
      logs.py        /api/logs, /api/logs/{session_id}
      queue_io.py    /api/import-files, /api/import/*, /api/export-queue
      session.py     /api/session, /api/session/new
    rx.py            /ws/rx WebSocket handler (clients receive live packets)
    tx.py            /ws/tx WebSocket handler (queue mutations, send control)
    rx_service.py    RxService — ZMQ SUB receiver + async broadcast loop
    tx_service.py    TxService — queue + send loop + ZMQ PUB lifetime
    tx_queue.py      Pure queue helpers: make_mission_cmd, make_delay, make_note, validate, persist, import
    tx_actions.py    Queue mutation actions invoked by tx.py
    session_ws.py    /ws/session WebSocket session management
    preflight_ws.py  /ws/preflight + run_preflight_and_broadcast + _broadcast primitive
    update_ws.py     Updater WS plumbing — schedule_update_check, _build_updates_event, _handle_apply_update
    security.py      CORS/CSP middleware
```

### Thread model

- **Main thread:** asyncio event loop (uvicorn + FastAPI)
- **RX receiver thread:** blocking ZMQ SUB recv loop, puts (meta, raw) into a queue
- **Broadcast loop:** async task drains the queue, runs pipeline, broadcasts to WebSocket clients
- **TX send loop:** async task runs during queue send (delay handling, guard confirmation)

Thread safety: `cfg_lock` for config updates, `tx_send_lock` for queue mutations during send.

## Mission adapter contract

A mission package lives under `mav_gss_lib/missions/<name>/`. The full adapter protocol and package-layout walkthrough is covered in [adding-a-mission.md](adding-a-mission.md); the optional standalone-page extension surface is documented in [plugin-system.md](plugin-system.md). What follows is the platform-side summary a maintainer needs before touching `mission_adapter.py` itself.

The mission package `__init__.py` must expose:

- `ADAPTER_API_VERSION = 1` — only `1` is accepted by `validate_adapter` (see `SUPPORTED_API_VERSIONS` in `mission_adapter.py`)
- `ADAPTER_CLASS` — a class satisfying the `MissionAdapter` Protocol
- `init_mission(cfg)` — called by `load_mission_adapter` after metadata merge; returns a dict that may include `cmd_defs`, `cmd_warn`, `nodes`, `image_assembler`, `gnc_store`

At startup, `load_mission_adapter` in `mission_adapter.py` resolves the mission module by convention, merges `mission.yml` / `mission.example.yml` into `cfg`, calls `init_mission`, constructs the adapter with the returned resources, then calls `validate_adapter` to check for the full method set. Adding or renaming a method on the Protocol requires updating both the Protocol declaration and the explicit `missing` list in `validate_adapter` — the `missing` list exists because `@runtime_checkable` Protocol checks do not produce useful diagnostics on failure.

The full `MissionAdapter` method surface (kept in sync with `mission_adapter.py`):

- RX path: `detect_frame_type`, `normalize_frame`, `parse_packet`, `duplicate_fingerprint`, `is_uplink_echo`
- TX path: `cmd_line_to_payload`, `build_tx_command`, `tx_queue_columns`
- Rendering slots: `packet_list_columns`, `packet_list_row`, `packet_detail_blocks`, `protocol_blocks`, `integrity_blocks`
- Logging: `build_log_mission_data`, `format_log_lines`, `is_unknown_packet`
- Resolution: `gs_node` property, `node_name`, `ptype_name`, `resolve_node`, `resolve_ptype`
- Optional hook: `on_packet_received(pkt)` — if present, `RxService` calls it after each parsed packet

The mission owns all command parsing, validation, and encoding inside `build_tx_command`. The platform owns only generic queue admission (MTU/framing checks). See `tests/echo_mission.py` for a minimal mission that satisfies the full protocol and is used by the adapter-boundary tests.

## RX/TX rendering contract

The platform owns WebSocket serialization. Mission adapters provide structured rendering data — the platform renders it generically.

**RX packets:** Platform serializes envelope fields (`num`, `time`, `frame`, `size`, `raw_hex`, `warnings`, `is_echo`, `is_dup`, `is_unknown`) and attaches `_rendering` from the adapter's rendering-slot methods. `_rendering` contains `row` (column-keyed values), `detail_blocks`, `protocol_blocks`, and `integrity_blocks`.

**TX queue/history:** All queue items are `mission_cmd` type. The platform serializes `display` metadata from the adapter's `build_tx_command()`: `display.row` (column-keyed values), `display.detail_blocks` (structured blocks for expanded view), `display.title`, `display.subtitle`. The adapter also provides `tx_queue_columns()` with column definitions and `hide_if_all` auto-hide metadata.

**Queue import/export format:** Import/export files under `generated_commands/` are newline-delimited JSON objects only. Supported records are `{ "type": "mission_cmd", "payload": { ... } }` and `{ "type": "delay", "delay_ms": 500 }`. Legacy list-style command lines are no longer accepted.

**Log viewer:** RX entries pass `_rendering` through from the stored log. TX entries build `_rendering` from persisted `display`. Both use the same column-driven `CellValue` rendering. RX uses `/api/columns`, TX uses `/api/tx-columns`.

### TX command model

The platform owns queue mechanics (persistence, send loop, guard, delay). The mission adapter owns command semantics:

- `cmd_line_to_payload(line)` — converts raw CLI text to a mission payload dict
- `build_tx_command(payload)` — validates, encodes, returns `{raw_cmd, display, guard}`
- `tx_queue_columns()` — column definitions for queue/history rendering

The platform does not assume any universal command field structure. Duplicate/requeue re-submits the original `payload` through `build_tx_command`, preserving all routing context.

## Config sidebar and log viewer

Both are lazy-loaded React components (`React.lazy` + `Suspense`). They fetch data from:

- `GET /api/config` — full merged config dict
- `GET /api/status` — runtime status (version, ZMQ states, log paths)
- `GET /api/logs` — session list from `logs/json/*.jsonl`
- `GET /api/logs/{session_id}` — parsed log entries for replay

### Cache behavior

`index.html` is served with `Cache-Control: no-cache` to prevent stale asset hash references after rebuilds. Hashed `.js`/`.css` files under `/assets/` cache normally.

## Extending for a new mission

See [adding-a-mission.md](adding-a-mission.md) for the full walkthrough and [plugin-system.md](plugin-system.md) for the optional standalone-page plugin surface. In short: create `mav_gss_lib/missions/<name>/` (start from `mav_gss_lib/missions/template/`), implement the adapter, and set `general.mission` in `gss.yml`.

Mission packages are discovered by convention — any importable package at `mav_gss_lib.missions.<name>` is automatically found. No platform core edits are required.

What stays the same: transport, web runtime, logging, UI shell, protocol support modules. What changes: the adapter methods, `mission.example.yml` (plus an optional local `mission.yml`), and the mission's command schema.

## Testing

Tests are `unittest`-style and are run directly under the radioconda env:

```bash
conda activate
cd tests
python3 test_ops_protocol_core.py        # CRC, CSP, AX.25, wire-format roundtrip
python3 test_ops_logging.py              # JSONL + text dual-output logging
python3 test_tx_plugin.py                # TX plugin contract
python3 test_ops_mission_boundary.py     # Adapter protocol on a non-MAVERIC mission
python3 test_ws_endpoints.py             # FastAPI WebSocket endpoints
MAVERIC_FULL_GR=1 python3 test_ops_golay_path.py   # GNU Radio end-to-end (opt-in)
```

The echo mission adapter in `tests/echo_mission.py` validates that a non-MAVERIC adapter can satisfy the full protocol.

## Repo map

```
MAV_WEB.py                          Entry point — FastAPI server
mav_gss_lib/
  config.py                         Config loading + deep merge
  constants.py                      Shared constants (DEFAULT_MISSION, etc.)
  gss.example.yml                   Tracked station-config template (copy to gss.yml)
  logging.py                        Dual-output session logging (JSONL + text)
  mission_adapter.py                MissionAdapter Protocol + loader
  parsing.py                        RxPipeline — frame detect, normalize, dedup
  preflight.py                      Preflight checks (GNU Radio env, ZMQ, etc.)
  textutil.py                       Text/string formatting helpers
  transport.py                      ZMQ PUB/SUB + PMT serialization
  updater.py                        Self-updater + dependency bootstrap
  protocols/                        Reusable protocol toolkit
    crc.py                            CRC-16 / CRC-32C
    csp.py                            CSP v1 header + KISS framing
    ax25.py                           AX.25 HDLC framing
    golay.py                          Golay(24,12) + CCSDS scrambler
    frame_detect.py                   Frame type detection
  missions/
    template/                       Starter kit for new missions (adapter, mission.example.yml, commands.example.yml)
    maveric/                        MAVERIC mission package
      __init__.py                     Package entry + init_mission()
      adapter.py                      MavericMissionAdapter
      nodes.py                        NodeTable — explicit node/ptype state
      wire_format.py                  CommandFrame encode/decode
      schema.py                       Command schema loading + validation
      cmd_parser.py                   TX command line parser
      rx_ops.py                       RX packet parsing
      tx_ops.py                       TX command building
      rendering.py                    RX display rendering
      display_helpers.py              Shared helpers between rendering.py and log_format.py
      log_format.py                   Log record formatting
      imaging.py                      Image chunk reassembler + /api/plugins/imaging router
      telemetry/                      Telemetry decoders (eps.py, types.py, nvg_sensors.py, gnc_router.py, gnc_registers/)
      commands.yml                    Command schema (gitignored)
      commands.example.yml            Public-safe schema template
      mission.yml                     Local mission metadata (gitignored)
      mission.example.yml             Public mission metadata
  web_runtime/                      Backend web services
    state.py                          WebRuntime container
    app.py                            FastAPI factory + lifespan
    api/                              REST endpoints (config, schema, logs, queue_io, session)
    rx.py                             RX WebSocket handler
    tx.py                             TX WebSocket handler
    tx_queue.py                       Queue operations
    tx_actions.py                     Queue mutation actions
    tx_context.py                     Send-context snapshot
    rx_service.py                     RxService
    tx_service.py                     TxService
    shutdown.py                       Delayed-shutdown helpers
    session_ws.py                     /ws/session handler
    preflight_ws.py                   /ws/preflight + broadcast primitive
    update_ws.py                      Updater WS plumbing
    _atomics.py                       AtomicStatus primitive
    _broadcast.py                     broadcast_safe helper
    _task_utils.py                    log_task_exception callback
    _ws_utils.py                      Shared WS send helpers
    security.py                       CORS/CSP middleware
  web/                              Frontend
    src/                              React + Vite + Tailwind source
      components/                     UI components (rx/, tx/, shared/, etc.)
      state/                          Context providers + store modules (RxProvider, TxProvider, SessionProvider and their selectors)
      hooks/                          Pure React hooks (sockets, shortcuts, preflight, etc. — no providers)
      lib/                            Types, colors, utilities
      plugins/                        Mission plugin registry + per-mission UI
        registry.ts                     Convention-based plugin discovery
        maveric/                        MAVERIC TX builder, imaging page, GNC page
          TxBuilder.tsx
          plugins.ts
          ImagingPage.tsx
          imaging/                       Imaging panels (preview, progress, queue, etc.)
          gnc/                           GNC dashboard page + register tables
    dist/                             Production build (committed, see below)
scripts/                            Operator / dev helper scripts (preflight.py, preview_eps_hk.py)
tests/                              Test suite
docs/                               Documentation
```

## Files to ignore for code edits

These paths are generated, local-only, or security-sensitive. Don't read or modify them when making code changes:

| Path | Reason |
|---|---|
| `mav_gss_lib/web/dist/` | Generated build output (~1.3 MB). Rebuilt with `npm run build`. |
| `mav_gss_lib/web/node_modules/` | NPM dependencies. Untracked. |
| `logs/` | Runtime log output. |
| `generated_commands/` | Queue import/export files. |
| `mav_gss_lib/gss.yml` | Local operator config (not tracked). |
| `mav_gss_lib/missions/maveric/mission.yml` | Local mission overrides (not tracked). |
| `mav_gss_lib/missions/maveric/commands.yml` | Command schema — gitignored for security. |
| `.pending_queue.jsonl` | Persisted TX queue state. |
| `<log_dir>/.gnc_snapshot.json` | Persisted GNC register-snapshot sidecar (one latest value per register). Path hard-wired under `general.log_dir` by `missions/maveric/__init__.py`. Gitignored. |

## Sensitive surfaces

These areas affect wire protocol correctness, RF safety, or mission operations. Edit with extra care and verify with tests.

| Surface | Files | Risk |
|---|---|---|
| **Command wire format** | `maveric/wire_format.py` (`CommandFrame.to_bytes`, `from_bytes`) | Byte-level encode/decode — any change can corrupt uplink/downlink frames |
| **Protocol framing** | `protocols/crc.py`, `protocols/csp.py`, `protocols/ax25.py`, `protocols/golay.py` | CRC, KISS, AX.25, ASM+Golay — must match spacecraft radio firmware |
| **TX send loop** | `web_runtime/tx_service.py` (`TxService.run_send`) | Controls actual RF transmission timing, guard confirmation, abort |
| **Command schema** | `maveric/commands.yml`, `maveric/schema.py` | Defines valid commands and argument types — errors can send malformed uplinks |
| **Mission adapter boundary** | `mission_adapter.py` (`MissionAdapter` Protocol) | Contract between platform and mission — breaking changes affect all missions |
| **Frame detection** | `protocols/frame_detect.py`, `parsing.py` (`RxPipeline`) | Misidentifying frames drops or corrupts received packets |

## Supply-chain checks (manual, pre-release)

Run these before cutting a release tag:

```bash
# JS deps — known CVEs in the committed package-lock.json
cd mav_gss_lib/web && npm audit

# Python deps — audit the ACTIVE radioconda environment (not the
# requirements.txt file, which is short and unpinned and would resolve
# to "latest on PyPI" — giving a misleading all-clear).
pip install --upgrade pip-audit
pip-audit   # no -r; audits the active env's installed packages
```

If either reports HIGH or CRITICAL issues, fix before release:
- `npm audit fix` for patch-level JS fixes (stay inside current major).
- For Python, the fix is typically a radioconda upgrade; if a specific
  vulnerable package needs a pin to stay below a broken version, add it
  to `requirements.txt` with a rationale comment.
