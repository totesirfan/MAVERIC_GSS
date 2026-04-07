# Adding a New Mission

This guide covers how to create a new mission package for MAVERIC GSS. A mission package owns all mission-specific semantics: packet parsing, command encoding, operator rendering, and metadata. The platform handles transport, queue mechanics, logging, and generic UI.

## Quick Start

1. Copy the template: `cp -r mav_gss_lib/missions/template mav_gss_lib/missions/mymission`
2. Edit the adapter, metadata, and command schema
3. Set `general.mission: mymission` in `gss.yml`
4. Run `python3 MAV_WEB.py`

No platform code changes needed. Mission packages are discovered by convention.

## Required Files

```
mav_gss_lib/missions/mymission/
    __init__.py              Mission entry point
    adapter.py               MissionAdapter implementation
    mission.example.yml      Public-safe mission metadata (tracked)
    commands.yml             Command schema (gitignored)
```

### `__init__.py`

```python
ADAPTER_API_VERSION = 1
ADAPTER_CLASS = MyMissionAdapter

def init_mission(cfg: dict) -> dict:
    """Called after metadata merge. Return cmd_defs and any warnings."""
    # Load your command schema, populate lookup tables, etc.
    return {"cmd_defs": {}, "cmd_warn": None}
```

### `mission.example.yml`

Tracked public-safe metadata merged into platform config at startup:

```yaml
mission_name: My Mission
nodes:
  0: GS
  1: SAT
ptypes:
  1: CMD
  2: RES
gs_node: GS
command_defs: commands.yml
ax25:
  src_call: MYCALL
  src_ssid: 0
  dest_call: SATCAL
  dest_ssid: 0
csp:
  priority: 2
  source: 0
  destination: 1
  dest_port: 10
  src_port: 0
  flags: 0
  csp_crc: true
```

### Optional `mission.yml`

If present beside `mission.example.yml`, the runtime loads it instead. Use for mission metadata that should not be in the public repo.

## Adapter Methods

Your adapter must satisfy the `MissionAdapter` Protocol in `mission_adapter.py`. See `mav_gss_lib/missions/template/adapter.py` for a documented template.

### Required — RX Path

| Method | Purpose |
|--------|---------|
| `detect_frame_type(meta)` | Classify outer framing from GNU Radio metadata |
| `normalize_frame(frame_type, raw)` | Strip outer framing, return (inner_payload, stripped_hdr, warnings) |
| `parse_packet(inner_payload, warnings)` | Parse into `ParsedPacket(mission_data={...}, warnings=[...])` |
| `duplicate_fingerprint(parsed)` | Return hashable fingerprint for dedup, or None |
| `is_uplink_echo(parsed)` | Classify uplink echoes |

### Required — TX Path

| Method | Purpose |
|--------|---------|
| `build_raw_command(src, dest, echo, ptype, cmd_id, args)` | Encode command to raw bytes |
| `validate_tx_args(cmd_id, args)` | Validate TX args against schema |
| `parse_cmd_line(line)` | Parse CLI text into (src, dest, echo, ptype, cmd, args) |
| `cmd_line_to_payload(line)` | Convert CLI text to payload dict for `build_tx_command` |

### Required — Rendering

| Method | Purpose |
|--------|---------|
| `packet_list_columns()` | RX column definitions |
| `packet_list_row(pkt)` | RX row values keyed by column ID |
| `packet_detail_blocks(pkt)` | Expanded detail blocks |
| `protocol_blocks(pkt)` | Protocol header blocks |
| `integrity_blocks(pkt)` | CRC/integrity check blocks |
| `tx_queue_columns()` | TX column definitions with optional `hide_if_all` |

### Required — Resolution

| Method | Purpose |
|--------|---------|
| `gs_node` (property) | Ground station node ID |
| `node_name(id)`, `ptype_name(id)` | ID → display name |
| `node_label(id)`, `ptype_label(id)` | ID → full label |
| `resolve_node(s)`, `resolve_ptype(s)` | Name/ID string → int |

### Required — Logging

| Method | Purpose |
|--------|---------|
| `build_log_mission_data(pkt)` | Mission-specific JSONL log payload |
| `format_log_lines(pkt)` | Mission-specific text log lines |
| `is_unknown_packet(parsed)` | Classify unknown/unparseable packets |

### Optional — TX Builder

If your mission supports a command builder UI:

| Method | Purpose |
|--------|---------|
| `build_tx_command(payload)` | Build command from structured input → `{raw_cmd, display, guard}` |

The `display` dict should contain:
- `title` — command name
- `subtitle` — routing summary
- `row` — column-keyed values matching `tx_queue_columns()` IDs
- `detail_blocks` — structured blocks for expanded detail view

If `build_tx_command` is not provided, the mission builder UI is hidden and only raw CLI input works.

## ParsedPacket

`ParsedPacket` has two fields:

```python
@dataclass
class ParsedPacket:
    mission_data: dict = field(default_factory=dict)  # your mission's parse results
    warnings: list[str] = field(default_factory=list)
```

Put whatever your mission needs in `mission_data`. The platform never reads it — it passes it through to your adapter's rendering/logging methods via `pkt.mission_data`.

## Optional — Custom TX Builder Component

If you want a React-based command builder (like MAVERIC's picker), register it in `mav_gss_lib/web/src/missions/registry.ts`. This is optional — the default raw CLI input works for any mission.

## Testing

1. Run adapter validation: the platform checks all required methods at startup
2. Use `tests/echo_mission.py` as a reference for a minimal test adapter
3. Write mission-specific tests for your parse/encode/render paths

## Checklist

- [ ] `__init__.py` with `ADAPTER_API_VERSION`, `ADAPTER_CLASS`, `init_mission`
- [ ] `adapter.py` satisfying `MissionAdapter` Protocol
- [ ] `mission.example.yml` with nodes, ptypes, protocol defaults
- [ ] `commands.yml` (gitignored) with command schema
- [ ] `gss.yml` updated: `general.mission: mymission`
- [ ] Tests for parse/encode/render roundtrips
- [ ] `commands.yml` added to `.gitignore` if security-sensitive
- [ ] If UI changes: `npm run build` and commit `dist/`
