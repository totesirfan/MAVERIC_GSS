# MAVERIC Mission Package

This directory contains the MAVERIC-specific mission implementation. It is one
pluggable mission package within the broader ground station platform. The platform
loads it by convention at startup when `general.mission: maveric` is set in `gss.yml`.

## What this package owns

- **Packet parsing** — MAVERIC command wire format decoding, CSP v1 header extraction,
  CRC-16 and CRC-32C integrity checks (`adapter.py` → `rx_ops.py`, `wire_format.py`)
- **Command building** — TX command construction from operator input, argument validation,
  AX.25/CSP routing field assembly (`adapter.py` → `tx_ops.py`, `cmd_parser.py`)
- **Operator rendering** — structured data (column values, detail blocks, protocol blocks)
  for the platform's generic UI containers (`rendering.py`)
- **Log formatting** — mission-specific log record shaping for JSONL + text output (`log_format.py`)
- **Wire format** — `CommandFrame` encode/decode, schema-based argument parsing (`wire_format.py`)
- **Node/ptype tables** — ID↔name resolution and gs_node resolution (`nodes.py` + definitions in `mission.example.yml`)
- **Command schema** — schema loading, validation, resolution (`schema.py`, `commands.yml`)
- **Imaging plugin** — `ImageAssembler` chunk reassembly and FastAPI plugin router (`imaging.py`)
- **Telemetry decoders** — per-command decoders for structured telemetry (EPS housekeeping
  in `eps.py`, NaviGuider sensors in `nvg_sensors.py`, GNC registers in `gnc_registers/`)
  with shared dataclasses/enums in `types.py`, a `GncRegisterStore` persisted across
  sessions, and the `gnc_router` exposing `/api/plugins/gnc/*` (`telemetry/`)
- **Frontend plugin surface** — MAVERIC command picker, imaging page, GNC page, and
  plugin page registration (`mav_gss_lib/web/src/plugins/maveric/TxBuilder.tsx`,
  `ImagingPage.tsx`, `gnc/`, `plugins.ts`)
- **Mission metadata** — node names, ptypes, AX.25/CSP defaults (`mission.example.yml`)

## Files

| File | Tracked | Purpose |
|------|---------|---------|
| `__init__.py` | Yes | Package entry: `ADAPTER_API_VERSION`, `ADAPTER_CLASS`, `init_mission`, `get_plugin_routers` |
| `adapter.py` | Yes | `MavericMissionAdapter` — implements the `MissionAdapter` protocol, delegates to sub-modules |
| `nodes.py` | Yes | `NodeTable` dataclass + `init_nodes()` — node/ptype ID↔name resolution |
| `wire_format.py` | Yes | `CommandFrame` encode/decode, argument type parsing |
| `schema.py` | Yes | `load_command_defs()` — reads and validates `commands.yml` |
| `cmd_parser.py` | Yes | TX command-line parser (`cmd_line_to_payload`) |
| `rx_ops.py` | Yes | RX parsing operations — frame decode, CSP/CRC extraction |
| `tx_ops.py` | Yes | TX building operations — encode, routing resolution, validation |
| `rendering.py` | Yes | RX display rendering — row, detail_blocks, protocol_blocks, integrity_blocks |
| `display_helpers.py` | Yes | Shared helpers used by both `rendering.py` and `log_format.py` — packet mission-data access, typed-arg unwrappers, register-shape predicates |
| `log_format.py` | Yes | Mission-specific log record formatting |
| `imaging.py` | Yes | `ImageAssembler` + `get_imaging_router()` plugin REST endpoints |
| `telemetry/` | Yes | Telemetry decoders package — EPS (`eps.py`), NaviGuider sensors (`nvg_sensors.py`), GNC registers (`gnc_registers/`), shared types/enums (`types.py`), and `gnc_router.py` exposing `/api/plugins/gnc/*` |
| `mission.example.yml` | Yes | Public-safe mission metadata (nodes, ptypes, AX.25/CSP defaults) |
| `commands.example.yml` | Yes | Annotated command schema example — safe structure, redacted content |
| `mission.yml` | No | Local private mission metadata override (gitignored) |
| `commands.yml` | No | Operational command schema (gitignored for security) |

## MAVERIC-specific behavior

The following behaviors are specific to MAVERIC and should not be mistaken
for platform-level behavior:

- **AX.25 + CSP v1 framing** — MAVERIC uses AX.25 outer framing and CSP v1 headers.
  Other missions may use different or no protocol wrappers.
- **CRC-16 per command + CRC-32C over CSP** — dual integrity check scheme is
  MAVERIC's wire format, not a platform requirement.
- **Node/ptype integer IDs** — MAVERIC maps integer IDs (LPPM=1, EPS=2, etc.) to
  names. The platform has no opinion on how missions resolve nodes.
- **`GS_NODE` constant** — MAVERIC's ground station node ID. Platform only knows
  about it via `adapter.gs_node`.
- **Golay and AX.25 uplink modes** — MAVERIC supports Mode 5 (ASM+Golay) and
  Mode 6 (AX.25). Uplink mode selection is in `gss.yml`, applied by the platform
  protocol framing — but the modes themselves are MAVERIC radio hardware parameters.
- **Satellite time decoding** — MAVERIC commands embed `epoch_ms` timestamps
  decoded from the wire format. Other missions may not have embedded timestamps.

## Warning: do not copy as-is

The MAVERIC adapter is tailored to MAVERIC's specific wire format, node topology,
and command schema. Do not copy `adapter.py` wholesale for a new mission —
start from `mav_gss_lib/missions/template/adapter.py` instead, which contains
stub implementations and docstrings explaining each method's contract.

See `docs/adding-a-mission.md` for the full mission authoring guide.
