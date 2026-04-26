# MAVERIC Mission Package

The MAVERIC mission implementation — one pluggable mission package within the
broader ground station platform. The platform loads it by convention at startup
when mission id `maveric` is active and calls `mission.py::build(ctx)` to obtain
a `MissionSpec`.

MAVERIC runs on the platform's declarative XTCE-lite pipeline. `mission.yml` is
the single source of truth for parameter types, parameters, sequence
containers, meta-commands, and verifier rules. Mission Python is a thin
authoring surface around that database.

## Layout

```
maveric/
├── __init__.py
├── mission.py             MissionSpec assembler (build(ctx) entry point)
├── mission.yml            XTCE-lite mission database (gitignored)
├── declarative.py         build_declarative_capabilities — Plan A/B wire-up
├── codec.py               MaverPacketCodec (PacketCodec) — owns node/ptype tables
├── packets.py             DeclarativePacketsAdapter + MaverMissionPayload
├── framing.py             MavericFramer — composes platform/framing/ primitives
├── plugins.py             Calibrator plugin registry (PLUGINS)
├── errors.py              Declarative-pipeline error types
├── preflight.py           Mission preflight-check factory (mission.yml + libfec)
│
├── ui/                    Presentation — boundary: MavericUiOps
│   ├── ops.py             UiOps implementation (codec + Mission fields)
│   ├── rendering.py       row / detail_blocks / protocol_blocks / integrity_blocks
│   ├── formatters.py      calibrator-plugin dispatch (display_kind / render_value)
│   └── log_format.py      JSONL mission-data + text log lines
│
└── imaging/               Imaging plugin
    ├── assembler.py       ImageAssembler (chunk reassembly, restart recovery)
    ├── router.py          /api/plugins/imaging FastAPI router
    └── events.py          MavericImagingEvents (EventOps source)
```

## What this package owns

- **mission.yml** — parameter types (with calibrators), parameters,
  sequence containers, meta-commands, verifier specs and rules. The platform
  walker decodes telemetry and encodes commands directly from this file.
- **`MaverPacketCodec`** (`codec.py`) — owns node + ptype lookup tables, the
  command wire format (`[src][dest][echo][ptype][id_len][args_len][id][args][CRC-16]`),
  and CSP CRC32 trailer logic. Implements the platform `PacketCodec` Protocol.
- **`DeclarativePacketsAdapter`** (`packets.py`) — wraps the codec into platform
  `PacketOps` (normalize → parse → classify → match_verifiers). Owns CSP V1
  4-byte strip, body CRC and CSP CRC32 verification, duplicate fingerprinting,
  and uplink-echo detection. Returns `MaverMissionPayload` instances.
- **`MavericFramer`** (`framing.py`) — composes a `FramerChain` from the
  platform `FRAMERS` registry: `csp_v1` + (`asm_golay` | `ax25`) per
  `tx.uplink_mode`. Mission code chooses the chain; bytes-on-wire logic lives
  in `mav_gss_lib/platform/framing/`.
- **Calibrator plugins** (`plugins.py`) — Python implementations of
  parameter-type calibrators referenced by name in `mission.yml`
  (`maveric.bcd_time`, `maveric.adcs_tmp`, `maveric.gnc_planner_mode`, …).
- **Operator rendering** (`ui/`) — packet list row, detail blocks, protocol
  blocks, integrity blocks. Reads `MaverMissionPayload` attributes +
  `envelope.telemetry` directly. Dispatches value formatting on parameter-type
  calibrator (`PythonCalibrator.callable_ref` / `EnumeratedParameterType` /
  `absolute_time`).
- **Log formatting** (`ui/log_format.py`) — mission-specific JSONL `mission`
  sub-block and the multi-line text log entry.
- **Imaging plugin** (`imaging/`) — chunk reassembly, REST endpoints, the
  packet event source that drives the assembler from inbound imaging commands.
- **Frontend plugin surface** — TX builder + imaging page + GNC page under
  `mav_gss_lib/web/src/plugins/maveric/`.

## MAVERIC-specific behavior (not platform-level)

- **AX.25 + CSP v1 + Command Wire Format** — MAVERIC's three-layer framing.
  The chain is composed in `framing.py` from generic platform primitives.
- **CRC-16 per command + CRC-32C over CSP** — dual integrity scheme is
  MAVERIC's wire format, not a platform requirement. Verified in
  `packets.py::parse`.
- **Node / ptype integer IDs** — MAVERIC maps integers (LPPM=1, EPS=2, …) to
  names. The codec is the runtime owner of these tables.
- **Uplink modes — Mode 5 (ASM+Golay) and Mode 6 (AX.25)** — MAVERIC radio
  parameters. The platform surfaces `tx.uplink_mode`; the modes themselves
  are mission-specific framers.
- **Satellite time decoding** — beacons emit a `time` fragment from a BCD-time
  parameter; commands with a `sat_time` arg emit a `sat_time` fragment. The
  renderer derives `ts_result` on demand from `envelope.telemetry`.

## Config shape

At runtime MAVERIC's `mission_cfg` carries these operator-editable keys under
`mission.config` in the native split-state shape:

| Key | Source | Operator-editable? |
|-----|--------|---------------------|
| `ax25.*`, `csp.*`, `imaging.thumb_prefix` | `mission.py::_seed()` placeholders overlaid by `gss.yml:mission.config.*` | Yes — `MissionConfigSpec.editable_paths` |

Identity-shape keys (mission name, nodes, ptypes, …) live in `mission.yml`
extensions. The codec is the runtime protection — there is no separate
`MissionConfigSpec.protected_paths` set.

Mission-declared TX defaults (`tx.frequency`, `tx.uplink_mode`) are seeded on
`platform_cfg["tx"]` at build time and can be overridden in `gss.yml`.

## Warning: do not copy as-is

The MAVERIC MissionSpec implementation is tailored to MAVERIC's wire format,
node topology, and command schema. New missions should author their own
`mission.yml` plus a small Python wiring layer using
`mav_gss_lib.platform.spec` (declarative walker, codec contract, command-ops
factory). See `mav_gss_lib/missions/echo_v2/` and
`mav_gss_lib/missions/balloon_v2/` for minimal reference implementations.
