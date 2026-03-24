# MAVERIC Ground Station Software

Ground station tools for the MAVERIC CubeSat mission. Receives and displays decoded satellite frames, and provides a command terminal for uplink operations.

## Structure

```
mav_gss_lib/              Shared library
    protocol.py           Nodes, CSP v1, KISS, CRC-16/CRC-32C, command wire format
    display.py            Theme class, box drawing, terminal formatting
    transport.py          ZMQ PUB/SUB, PMT PDU send/receive
    curses_ui.py          Curses dashboard panels, layout, color pairs

MAV_RX.py                 Downlink packet monitor
MAV_TX2.py                Uplink command dashboard (curses)

legacy/                   Archived tools
    MAV_TX_old.py         Original CLI command terminal

maveric_commands.yml      Command schema (arg names, types, validation)
maveric_decoder.yml       gr-satellites satellite definition file
```

## MAV_RX — Packet Monitor

Subscribes to a ZMQ PUB socket where GNU Radio publishes decoded PDUs and displays packet contents for live debugging. Designed to run continuously — the flowgraph can be started and stopped independently.

For each packet, the monitor shows:

- Packet count, ground station timestamp, and inter-packet timing
- Frame type (AX.25 or AX100), inferred from gr-satellites metadata
- Inner payload after stripping transport framing
- CSP v1 header parse with plausibility check
- CRC-32C (Castagnoli) verification over the full CSP packet
- CRC-16 XMODEM verification on the command payload
- Satellite timestamp (schema-resolved or heuristic epoch-ms detection)
- Parsed command structure with node routing and typed arguments
- SHA-256 fingerprint for duplicate detection

When `maveric_commands.yml` is present, known commands are parsed deterministically by the schema — no regex scanning or per-arg guessing. Unknown commands fall back to the heuristic path automatically.

With `--loud`, hex dump, ASCII, CRC values, and SHA-256 are also shown in the terminal. These are always written to the log files regardless.

Raw hex is ground truth. All parsed fields are diagnostic until the telemetry map is finalized.

## MAV_TX2 — Command Dashboard (Curses)

Persistent curses-based dashboard for uplink operations (CSP v1 + CRC-32C + AX.25 + ZMQ) with a live multi-panel interface.

Layout:

- **Header** — AX.25 source/destination callsigns, CSP config, UTC and local time, ZMQ status and port, frequency (437.25 MHz)
- **TX Queue** — commands waiting to be sent, with destination, command ID, and args
- **Sent History** — transmitted commands with payload src/dest, echo, type metadata (scrollable)
- **Input** — command entry with cursor editing, command history recall (Up/Down)

Commands are validated against `maveric_commands.yml` and rejected if invalid. All commands go to the queue on Enter, then `Ctrl+S` sends the queue.

Keyboard shortcuts:

| Key | Action |
|-----|--------|
| `Ctrl+S` | Send all queued commands |
| `Ctrl+X` | Clear the queue |
| `Up / Down` | Recall command history |
| `PgUp / PgDn` | Scroll sent history |
| `Ctrl+A / Ctrl+E` | Jump to start / end of input |
| `Ctrl+W / Ctrl+U` | Delete word / clear line |
| `Esc` | Close side panel |

Side panels (appear to the right of sent history):

- **`config` / `cfg`** — editable configuration for AX.25 callsigns, CSP parameters, frequency, ZMQ address. Tab to focus, Up/Down to select, Enter to edit. Also shows the log file path.
- **`help`** — command format reference, keyboard shortcuts, schema info

## Usage

All scripts require the radioconda GNU Radio environment. Start your GNU Radio flowgraph first, then:

```bash
conda activate gnuradio

# Downlink monitor
python3 MAV_RX.py
python3 MAV_RX.py --loud       # includes hex, ASCII, CRC, SHA256
python3 MAV_RX.py --nolog      # display only, no log files

# Uplink command dashboard (curses)
python3 MAV_TX2.py
```

Press `Ctrl+C` to stop.

## Logging

Each monitor session writes two log files to `logs/`:

- `.jsonl` — machine-readable, one JSON object per packet
- `.txt` — human-readable plain text

The command terminal logs uplink transmissions to a separate `.jsonl` file. Logging can be disabled with `--nolog` on the monitor.

## Command Schema

`maveric_commands.yml` defines the argument schema for each known command. When present:

- **RX** parses known commands deterministically by position and type (skips regex/heuristic scanning)
- **TX2** validates arguments and rejects invalid commands — they are not added to the queue
- Unknown commands fall back to heuristic parsing automatically

Supported arg types: `str`, `int`, `float`, `epoch_ms`, `bool`. See the file header for full documentation.

## Configuration

| Variable | Default | Where |
|----------|---------|-------|
| `ZMQ_PORT` | `52001` | MAV_RX — downlink subscribe port |
| `ZMQ_ADDR` | `tcp://127.0.0.1:52002` | MAV_TX2 — uplink publish port |
| `ZMQ_RECV_TIMEOUT_MS` | `200` | MAV_RX — receive timeout (ms) |
| `LOG_DIR` | `logs` | Both — log output directory |
| `CMD_DEFS_PATH` | `maveric_commands.yml` | Both — command schema file |

## Theming

ANSI colors for MAV_RX are defined in `mav_gss_lib/display.py` in the `Theme` class. Curses color pairs for MAV_TX2 are defined in `mav_gss_lib/curses_ui.py`. Both use the same semantic roles (LABEL, VALUE, SUCCESS, WARNING, ERROR).

## Decoder

`maveric_decoder.yml` is the gr-satellites satellite definition file. It configures three transmitter modes on 437.250 MHz:

- 19k2 FSK AX.25 G3RUH
- 4k8 FSK AX.25 G3RUH
- 4k8 FSK AX100 ASM+Golay

## Dependencies

- [radioconda](https://github.com/ryanvolz/radioconda) (GNU Radio 3.10+, gr-satellites, PyZMQ, pmt)
- `crc` Python package (`pip install crc` in the gnuradio env)
- `pyyaml` Python package (`pip install pyyaml` — optional, needed for command schema validation)

## Status

Early development. Telemetry structure is not yet finalized — the monitor shows raw packet data and diagnostic heuristics. Command definitions are maintained separately.