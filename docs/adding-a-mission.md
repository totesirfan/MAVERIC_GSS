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
- Raw CLI text input — platform passes the string to the mission, mission interprets it

## What Your Mission Provides

- How to parse received bytes into meaningful data
- How to parse operator commands into transmit bytes
- How to present parsed data and queued commands to operators
- Mission metadata (node names, packet types, protocol defaults — whatever your mission needs)
- How to interpret raw CLI text input from operators

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
    """Called after mission metadata is merged into platform config.
    
    Return a dict with:
      cmd_defs: dict — command schema (can be empty)
      cmd_warn: str | None — warning message if schema loading failed
    """
    return {"cmd_defs": {}, "cmd_warn": None}
```

### `mission.example.yml`

Tracked public-safe mission metadata, merged into platform config at startup. The only required field is `mission_name`:

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

Run `python3 MAV_WEB.py` — the platform discovers your package at `mav_gss_lib.missions.mymission`, validates the adapter, and starts.

---

## Adapter Protocol

Your adapter satisfies the `MissionAdapter` Protocol in `mission_adapter.py`. The platform calls these methods without knowing which mission is active. All methods are required.

### RX — Receive and Parse

| Method | What it does |
|--------|-------------|
| `detect_frame_type(meta)` | Classify outer framing from GNU Radio metadata |
| `normalize_frame(frame_type, raw)` | Strip framing, return `(inner_payload, stripped_hdr, warnings)` |
| `parse_packet(inner_payload, warnings)` | Parse into `ParsedPacket(mission_data={...})` |
| `duplicate_fingerprint(parsed)` | Hashable fingerprint for dedup, or `None` to skip dedup |
| `is_uplink_echo(parsed)` | `True` if this is an echo of an uplink command |
| `is_unknown_packet(parsed)` | `True` if the packet couldn't be parsed |

**`ParsedPacket`** is mission-opaque — put whatever your mission needs in `mission_data`. The platform never reads it. It passes it through to your rendering and logging methods via `pkt.mission_data`.

```python
from mav_gss_lib.mission_adapter import ParsedPacket

def parse_packet(self, inner_payload, warnings=None):
    warnings = warnings or []
    # Your mission's parsing logic here
    header = parse_my_header(inner_payload[:4])
    body = inner_payload[4:]
    return ParsedPacket(
        mission_data={
            "header": header,
            "body": body.hex(),
            "valid": header.checksum_ok,
        },
        warnings=warnings,
    )
```

### RX — Rendering

The platform renders RX packets from structured data you provide. Your mission controls what operators see without writing platform UI code.

**Columns** define the packet list layout:

```python
def packet_list_columns(self):
    return [
        {"id": "num",    "label": "#",      "align": "right", "width": "w-9"},
        {"id": "time",   "label": "time",   "width": "w-[68px]"},
        {"id": "src",    "label": "src",    "width": "w-[52px]"},
        {"id": "type",   "label": "type",   "width": "w-[52px]", "badge": True},
        {"id": "data",   "label": "data",   "flex": True},
        {"id": "size",   "label": "size",   "align": "right", "width": "w-10"},
    ]
```

Column options: `id` (key into row values), `label` (header text), `width` (Tailwind class), `flex` (fill remaining space), `badge` (render as PtypeBadge), `align` (`"right"`), `hide_if_all` (auto-hide when all values match, e.g. `["NONE"]`).

**Row values** are keyed by column ID:

```python
def packet_list_row(self, pkt):
    md = pkt.mission_data
    return {
        "values": {
            "num": pkt.pkt_num,
            "time": pkt.gs_ts_short,
            "src": md.get("header", {}).get("source", ""),
            "type": md.get("header", {}).get("msg_type", ""),
            "data": md.get("body", ""),
            "size": len(pkt.raw),
        },
        "_meta": {"opacity": 0.5 if pkt.is_unknown else 1.0},
    }
```

**Detail blocks** appear when a packet is expanded:

```python
def packet_detail_blocks(self, pkt):
    md = pkt.mission_data
    blocks = []
    if md.get("header"):
        blocks.append({
            "kind": "header",
            "label": "Packet Header",
            "fields": [
                {"name": "Source", "value": str(md["header"].get("source", ""))},
                {"name": "Type", "value": str(md["header"].get("msg_type", ""))},
                {"name": "Valid", "value": "Yes" if md["header"].get("checksum_ok") else "No"},
            ],
        })
    return blocks
```

**Protocol blocks** show protocol wrapper info (CSP headers, AX.25 framing, etc.):

```python
def protocol_blocks(self, pkt):
    # Return ProtocolBlock dataclasses — or [] if your mission has none
    return []
```

**Integrity blocks** show CRC/integrity check results:

```python
def integrity_blocks(self, pkt):
    # Return IntegrityBlock dataclasses — or [] if no integrity checks
    return []
```

### TX — Command Input and Encoding

The mission owns all command parsing, validation, and TX Parsing. The platform passes raw operator input through and renders the result.

| Method | What it does |
|--------|-------------|
| `cmd_line_to_payload(line)` | Wrap raw CLI text for `build_tx_command` — typically `{"line": line}` |
| `build_tx_command(payload)` | Parse, validate, encode → `{raw_cmd, display, guard}` |
| `tx_queue_columns()` | Column definitions for TX queue/history rendering |

**`cmd_line_to_payload`** is a thin wrapper. The platform calls it with the operator's raw text string. Return a payload dict that `build_tx_command` understands:

```python
def cmd_line_to_payload(self, line):
    line = line.strip()
    if not line:
        raise ValueError("empty command input")
    return {"line": line}
```

**`build_tx_command`** does the real work — parsing, validating, encoding, and producing display metadata:

```python
def build_tx_command(self, payload):
    line = payload.get("line", "")
    parts = line.split()
    if not parts:
        raise ValueError("empty command")
    
    cmd_name = parts[0]
    args = parts[1:]
    raw = encode_my_command(cmd_name, args)  # your mission's encoding
    
    return {
        "raw_cmd": raw,
        "display": {
            "title": cmd_name,
            "subtitle": f"{len(raw)}B",
            "row": {"cmd": line},                    # matches tx_queue_columns
            "detail_blocks": [{"kind": "command", "label": "Command", "fields": [
                {"name": "Command", "value": cmd_name},
            ] + [{"name": f"arg{i}", "value": a} for i, a in enumerate(args)]}],
        },
        "guard": cmd_name in self.dangerous_commands,  # require confirmation
    }
```

The `display` dict controls how the command appears in the queue and history:
- `title` — primary label (rendered as a pill in the queue row)
- `subtitle` — secondary label
- `row` — column-keyed values matching `tx_queue_columns()` IDs
- `detail_blocks` — expanded detail view (same shape as RX detail blocks)

**`tx_queue_columns`** defines how the TX queue and history render:

```python
def tx_queue_columns(self):
    return [
        {"id": "cmd", "label": "command", "flex": True},
    ]
```

Column options are the same as RX columns, including `hide_if_all` for auto-hide.

### Resolution

These methods translate between internal IDs and operator-facing names. They're used by the platform for node tooltips and config display.

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

`build_log_mission_data` returns a dict that gets stored under the `"mission"` key in the JSONL log record. Put whatever your mission needs for post-session analysis:

```python
def build_log_mission_data(self, pkt):
    md = pkt.mission_data
    return {"header": md.get("header"), "body": md.get("body")}
```

`format_log_lines` returns lines for the human-readable text log:

```python
def format_log_lines(self, pkt):
    md = pkt.mission_data
    return [f"  {'TYPE':<12}{md.get('header', {}).get('msg_type', '?')}"]
```

---

## TX Command Flow — End to End

Here's how a command goes from operator input to transmission:

```
1. Operator types "ping 42" in the CLI input
2. Platform calls adapter.cmd_line_to_payload("ping 42")
   → returns {"line": "ping 42"}
3. Platform calls adapter.build_tx_command({"line": "ping 42"})
   → mission parses, validates, encodes
   → returns {raw_cmd: b"\x01\x02...", display: {...}, guard: False}
4. Platform checks MTU/framing limits
5. Platform wraps as queue item: {type: "mission_cmd", raw_cmd, display, payload, guard}
6. Queue item rendered in TX queue using display.row + tx_queue_columns()
7. On send: raw_cmd is wrapped in CSP/AX.25/Golay and published via ZMQ
8. History entry stored with display metadata + original payload
9. Duplicate/requeue re-submits the original payload through build_tx_command
```

For the custom builder UI path (if registered), step 1-2 are replaced by the frontend component collecting a structured payload dict and sending it directly to `build_tx_command` via `queue_mission_cmd`.

Queue import/export files use the same payload contract. Each JSONL line must be either `{ "type": "mission_cmd", "payload": { ... } }` or `{ "type": "delay", "delay_ms": ... }`. The platform no longer accepts legacy list-style command records.

---

## Optional: Custom TX Input UI

The platform always provides raw CLI input. If your mission wants a visual command picker or form-based input, register a React component as a separate frontend concern.

**This is distinct from `build_tx_command`**:
- `build_tx_command(payload)` — **required backend hook**. Parses, validates, encodes. Part of the mission TX contract.
- Custom TX input UI — **optional frontend component**. Collects structured input from the operator and sends it as a payload to `build_tx_command` via the `queue_mission_cmd` WebSocket action.

To add a custom TX input UI:

1. Create `mav_gss_lib/web/src/plugins/<name>/TxBuilder.tsx`
2. Export a default component satisfying `MissionBuilderProps`
3. Run `npm run build` and commit `dist/`

The frontend auto-discovers builder components by convention — any file at
`plugins/<name>/TxBuilder.tsx` is automatically registered. No manual
registry edit, no backend attribute, no separate configuration step.
The directory name must match the `general.mission` value in `gss.yml`.

See `plugins/maveric/TxBuilder.tsx` for an example implementation.

### Optional: Mission-Owned Command Help

If your mission uses command-entry syntax that differs from MAVERIC, do not
hardcode that syntax into shared web UI. Keep the shared Help modal, but make
the command-entry rows mission-owned.

This keeps the operator help aligned with the mission's actual parser and avoids
teaching future missions MAVERIC-specific command grammar by accident.

See [mission-help-contract.md](mission-help-contract.md) for the proposed contract and placement.

### Optional: Plugin Pages

Missions can provide standalone tool pages (imaging, telemetry viewers, etc.) beyond the core RX/TX dashboard. These are discovered by convention and lazy-loaded.

1. Create `mav_gss_lib/web/src/plugins/<name>/plugins.ts` exporting a `PluginPageDef[]`
2. Create corresponding page components in the same directory
3. Run `npm run build` and commit `dist/`

See [plugin-system.md](plugin-system.md) for the full plugin contract and architecture.

---

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

If your mission uses node/ptype ID tables:

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

---

## Optional: Command Schema

If your mission has a structured command schema, provide it as `commands.yml` alongside the adapter. The `init_mission()` function loads it and returns `cmd_defs`. Add `commands.yml` to `.gitignore` if it contains operationally sensitive information.

The command schema is mission-defined — the platform stores it but doesn't interpret it. Your adapter's `build_tx_command` uses it for validation and encoding.

Example files are provided as a starting point and reference:

- `mav_gss_lib/missions/maveric/commands.example.yml` — fully annotated MAVERIC example with all field types, routing fields, guard, nodes constraint, rx_only, and argument types documented
- `mav_gss_lib/missions/template/commands.example.yml` — minimal starter with `ping` and `set_value`

Copy workflow:

```bash
cp mav_gss_lib/missions/<name>/commands.example.yml mav_gss_lib/missions/<name>/commands.yml
# then edit commands.yml with real command IDs and routing
```

---

## Optional: Local Mission Override

If present beside `mission.example.yml`, a `mission.yml` file is loaded instead of the tracked example. Use for mission metadata that should not be in the public repo. Add to `.gitignore`:

```
mav_gss_lib/missions/mymission/mission.yml
```

---

## Testing

1. **Startup validation** — the platform checks all required adapter methods at startup and rejects missing ones with clear error messages. Just run `python3 MAV_WEB.py` to verify.

2. **Echo mission reference** — `tests/echo_mission.py` is a minimal non-MAVERIC adapter that passes all validation. Use it as a sanity check template.

3. **Write mission-specific tests** for your parse → render → encode roundtrips:

```python
class TestMyMission(unittest.TestCase):
    def setUp(self):
        from mav_gss_lib.missions.mymission.adapter import MyAdapter
        self.adapter = MyAdapter(cmd_defs={})

    def test_parse_known_packet(self):
        parsed = self.adapter.parse_packet(b"\x01\x02\x03\x04")
        self.assertIn("header", parsed.mission_data)

    def test_build_tx_roundtrip(self):
        payload = self.adapter.cmd_line_to_payload("ping 42")
        result = self.adapter.build_tx_command(payload)
        self.assertIsInstance(result["raw_cmd"], bytes)
        self.assertIn("title", result["display"])

    def test_rendering_produces_valid_columns(self):
        cols = self.adapter.packet_list_columns()
        for col in cols:
            self.assertIn("id", col)
            self.assertIn("label", col)

    def test_tx_columns_have_ids(self):
        cols = self.adapter.tx_queue_columns()
        for col in cols:
            self.assertIn("id", col)
```

4. **Adapter conformance** — the `validate_adapter()` function in `mission_adapter.py` checks all required methods. You can call it directly in tests:

```python
from mav_gss_lib.mission_adapter import validate_adapter
validate_adapter(self.adapter, 1, "mymission")  # raises on missing methods
```

---

## Checklist

**Required:**
- [ ] `__init__.py` with `ADAPTER_API_VERSION`, `ADAPTER_CLASS`, `init_mission`
- [ ] `adapter.py` satisfying `MissionAdapter` Protocol
- [ ] `mission.example.yml` with at minimum `mission_name`
- [ ] `general.mission` set in `gss.yml`
- [ ] `build_tx_command` parses, validates, and encodes operator commands
- [ ] `cmd_line_to_payload` wraps raw CLI text for `build_tx_command`
- [ ] `tx_queue_columns` defines TX queue/history column layout
- [ ] Tests for parse/encode/render roundtrips

**Optional:**
- [ ] `commands.yml` + gitignore entry if security-sensitive
- [ ] Protocol metadata in `mission.example.yml` (AX.25, CSP, nodes, ptypes)
- [ ] Local `mission.yml` override + gitignore entry
- [ ] Custom TX input UI component (`missions/<name>/TxBuilder.tsx` — auto-discovered)
- [ ] If frontend changes: `npm run build` and commit `dist/`
