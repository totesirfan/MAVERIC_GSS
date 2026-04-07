# Adding a New Mission

The ground station platform separates reusable mechanics from mission-specific semantics. The platform owns transport, queue execution, logging, and generic UI containers. A mission package owns how packets are parsed, how commands are built, and how data is presented to operators.

To add a mission: create a package under `mav_gss_lib/missions/<name>/`, implement the adapter protocol, and set `general.mission` in `gss.yml`. No platform code changes needed — packages are discovered by convention.

## What the Platform Provides

- ZMQ transport (receive PDUs, send framed payloads)
- RX pipeline: frame detection → adapter parse → dedup/echo classification → log → broadcast
- TX pipeline: queue persistence, send loop, guard confirmations, delay scheduling
- Generic column-driven UI for RX packets, TX queue, TX history, log viewer
- Session logging (JSONL + formatted text)
- Reusable protocol toolkit: AX.25, CSP, CRC, Golay, KISS (use what you need)

## What Your Mission Provides

- How to parse received bytes into meaningful data
- How to encode operator commands into transmit bytes
- How to present parsed data and queued commands to operators
- Mission metadata (node names, packet types, protocol defaults — whatever your mission needs)

## Smallest Possible Mission

A minimal mission needs three files. See `tests/echo_mission.py` for a working example that passes all adapter validation.

```
mav_gss_lib/missions/mymission/
    __init__.py
    adapter.py
    mission.example.yml
```

### `__init__.py`

```python
from .adapter import MyAdapter

ADAPTER_API_VERSION = 1
ADAPTER_CLASS = MyAdapter

def init_mission(cfg: dict) -> dict:
    return {"cmd_defs": {}, "cmd_warn": None}
```

### `mission.example.yml`

The only required field is `mission_name`. Everything else depends on what your mission needs:

```yaml
mission_name: My Mission
```

### `adapter.py`

Copy from `mav_gss_lib/missions/template/adapter.py`. Every method has a docstring explaining what to implement. A bare-minimum adapter that echoes raw bytes needs only trivial implementations — see `tests/echo_mission.py`.

### Activate it

```yaml
# gss.yml
general:
  mission: mymission
```

## Adapter Protocol

Your adapter satisfies the `MissionAdapter` Protocol in `mission_adapter.py`. The platform calls these methods without knowing which mission is active.

### RX — Receive and Parse

| Method | What it does |
|--------|-------------|
| `detect_frame_type(meta)` | Classify outer framing from GNU Radio metadata |
| `normalize_frame(frame_type, raw)` | Strip framing, return inner payload + any stripped header |
| `parse_packet(inner_payload, warnings)` | Parse into `ParsedPacket(mission_data={...})` |
| `duplicate_fingerprint(parsed)` | Hashable fingerprint for dedup, or None |
| `is_uplink_echo(parsed)` | True if this is an echo of an uplink command |
| `is_unknown_packet(parsed)` | True if the packet couldn't be parsed |

`ParsedPacket` is mission-opaque — put whatever your mission needs in `mission_data`:

```python
return ParsedPacket(
    mission_data={"my_header": header, "my_payload": payload},
    warnings=warnings,
)
```

The platform never reads `mission_data`. It passes it through to your rendering/logging methods.

### RX — Rendering

The platform renders RX packets from structured data you provide. This is how your mission controls what operators see without writing platform UI code.

| Method | What it returns |
|--------|----------------|
| `packet_list_columns()` | Column definitions: `[{id, label, width?, badge?, flex?}]` |
| `packet_list_row(pkt)` | Row values: `{values: {col_id: value}, _meta: {opacity?}}` |
| `packet_detail_blocks(pkt)` | Detail blocks: `[{kind, label, fields: [{name, value}]}]` |
| `protocol_blocks(pkt)` | Protocol header blocks (same shape as detail) |
| `integrity_blocks(pkt)` | CRC/integrity blocks: `[{kind, label, scope, ok, received?, computed?}]` |

### TX — Command Encoding

These methods let operators type commands and have them encoded for transmission. The signatures use `src/dest/echo/ptype/cmd/args` because that's the current protocol interface, but your mission decides what those parameters mean internally.

| Method | What it does |
|--------|-------------|
| `build_raw_command(src, dest, echo, ptype, cmd_id, args)` | Encode to raw bytes |
| `validate_tx_args(cmd_id, args)` | Validate args → (ok, error_list) |
| `parse_cmd_line(line)` | Parse operator CLI text → (src, dest, echo, ptype, cmd, args) |
| `cmd_line_to_payload(line)` | Convert CLI text to a payload dict for `build_tx_command` |

### TX — Rendering

| Method | What it returns |
|--------|----------------|
| `tx_queue_columns()` | Column definitions for TX queue/history, with optional `hide_if_all` for auto-hide |

### Resolution

These methods translate between internal IDs and operator-facing names:

| Method | Purpose |
|--------|---------|
| `gs_node` (property) | Ground station node ID |
| `node_name(id)` / `ptype_name(id)` | Short display name |
| `node_label(id)` / `ptype_label(id)` | Full descriptive label |
| `resolve_node(s)` / `resolve_ptype(s)` | Name string → integer ID |

### Logging

| Method | Purpose |
|--------|---------|
| `build_log_mission_data(pkt)` | Mission-specific data for the JSONL log record |
| `format_log_lines(pkt)` | Mission-specific lines for the text log |

## Optional: TX Command Builder

If your mission provides `build_tx_command(payload)`, the platform enables richer TX behavior:

- The mission builder UI appears (if a frontend component is registered)
- `cmd_line_to_payload()` can route CLI input through `build_tx_command()`
- Queue items carry structured `display` metadata for column-driven rendering
- Duplicate/requeue faithfully re-submits the original payload

`build_tx_command(payload)` receives a mission-defined payload dict and returns:

```python
{
    "raw_cmd": encoded_bytes,
    "display": {
        "title": "command_name",
        "subtitle": "routing summary",
        "row": {"col_id": "value", ...},       # matches tx_queue_columns() IDs
        "detail_blocks": [{kind, label, fields}], # for expanded detail view
    },
    "guard": False,
}
```

Without `build_tx_command`, the mission builder is hidden and only raw CLI works.

### Optional: Custom React Builder Component

The backend `build_tx_command` hook is what enables mission-built commands. The frontend component that collects the payload input is a separate, optional layer.

By default, the platform provides raw CLI input. If your mission wants a visual command picker or form-based builder, register a React component in `mav_gss_lib/web/src/missions/registry.ts`. This component calls `build_tx_command` via the `queue_mission_cmd` WebSocket action. See `missions/maveric/TxBuilder.tsx` for an example.

The relationship:
- **Backend hook** (`build_tx_command`) — required for mission-built commands
- **Frontend component** (registry) — optional UI for collecting payload input

## Optional: Protocol Metadata

If your mission uses AX.25, CSP, or other reusable protocols from the platform toolkit, provide their defaults in `mission.example.yml`:

```yaml
# Only include what your mission actually uses
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

These are merged into the runtime config at startup. The platform applies them to protocol objects via `apply_ax25()` / `apply_csp()`. If your mission doesn't use AX.25 or CSP, omit these sections entirely.

Similarly, if your mission uses node/ptype ID tables:

```yaml
nodes:
  0: GS
  1: SAT
ptypes:
  1: CMD
  2: RES
gs_node: GS
```

These are optional — your adapter's `node_name()` / `resolve_node()` methods can use any lookup mechanism.

## Optional: Command Schema

If your mission has a structured command schema, provide it as `commands.yml` alongside the adapter. The `init_mission()` function loads it and returns `cmd_defs`. Add `commands.yml` to `.gitignore` if it contains operationally sensitive information.

## Testing

1. **Startup validation** — the platform checks all required adapter methods at startup and rejects missing ones with clear error messages
2. **Echo mission reference** — `tests/echo_mission.py` is a minimal non-MAVERIC adapter that passes all validation
3. **Write mission-specific tests** for your parse → render → encode roundtrips

## Checklist

- [ ] `__init__.py` with `ADAPTER_API_VERSION`, `ADAPTER_CLASS`, `init_mission`
- [ ] `adapter.py` satisfying `MissionAdapter` Protocol
- [ ] `mission.example.yml` with at minimum `mission_name`
- [ ] `general.mission` set in `gss.yml`
- [ ] Tests for parse/encode/render paths
- [ ] Optional: `commands.yml` + gitignore entry if security-sensitive
- [ ] Optional: protocol metadata in `mission.example.yml` if using AX.25/CSP
- [ ] Optional: TX builder backend hook (`build_tx_command`)
- [ ] Optional: TX builder frontend component (registry)
- [ ] If frontend changes: `npm run build` and commit `dist/`
