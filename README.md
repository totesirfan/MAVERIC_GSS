# MAVERIC Ground Station Software

Ground station tools for the MAVERIC CubeSat mission. Receives and displays decoded satellite frames, and provides a command terminal for uplink operations.

## Structure

```
mav_gss_lib/              Shared library
    protocol.py           Nodes, CSP v1, KISS, CRC-16/CRC-32C, command wire format
    transport.py          ZMQ PUB/SUB, PMT PDU send/receive
    curses_common.py      Shared curses utilities (colors, drawing, splash screen)
    curses_tx.py          TX dashboard panels and layout
    curses_rx.py          RX monitor panels and layout

MAV_RX2.py                Downlink packet monitor (curses)
MAV_TX2.py                Uplink command dashboard (curses)

legacy/                   Archived tools (not tracked in git)
    MAV_RX.py             Original terminal-based packet monitor
    MAV_TX_old.py         Original CLI command terminal
    display.py            ANSI terminal theme/box drawing (used by legacy scripts)

maveric_commands.yml      Command schema (arg names, types, validation)
maveric_decoder.yml       gr-satellites satellite definition file
```

## MAV_RX2 — Packet Monitor (Curses)

Curses-based downlink packet monitor. Subscribes to a ZMQ PUB socket where GNU Radio publishes decoded PDUs and displays packets in a scrollable, interactive dashboard. A dedicated receiver thread ensures no packets are lost during UI redraws.

Layout:

- **Header** — ZMQ address, frequency (auto-detected from gr-satellites metadata), UTC/local clock, HEX/LOG toggle indicators
- **Packet List** — scrollable list with command src/dest routing, command ID, arguments, payload size, CRC status, duplicate detection. Auto-follows newest packets in `[LIVE]` mode
- **Packet Detail** — expanded view of selected packet (Enter to toggle): AX.25 header, CSP fields, satellite timestamp, command fields, hex dump, CRC verification
- **Input** — command entry with live status (Receiving/Silence timer, packet count, rate)

Typed commands:

| Command | Action |
|---------|--------|
| `help` | Toggle help panel |
| `cfg` / `config` | Toggle config panel (hex/log toggles) |
| `hex` | Toggle hex/ASCII display |
| `log` | Toggle logging on/off |
| `q` / `quit` | Exit |

Keyboard:

| Key | Action |
|-----|--------|
| `Up / Down` | Select packet (Down on last → LIVE) |
| `PgUp / PgDn` | Scroll by page |
| `Home / End` | First / last packet |
| `Enter` | Toggle detail panel (or execute typed command) |
| `Ctrl+C` | Quit |

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

# Downlink monitor (curses)
python3 MAV_RX2.py
python3 MAV_RX2.py --nosplash   # skip startup splash screen

# Uplink command dashboard (curses)
python3 MAV_TX2.py
python3 MAV_TX2.py --nosplash
```

Press `Ctrl+C` to stop.

## Logging

Each monitor session writes two log files to `logs/`:

- `.jsonl` — machine-readable, one JSON object per packet
- `.txt` — human-readable plain text

RX logs are named `downlink_YYYYMMDD_HHMMSS.*`, TX logs are named `uplink_YYYYMMDD_HHMMSS.*`. Logging can be toggled at runtime in the RX monitor via the `log` command or config panel.

## Command Schema

`maveric_commands.yml` defines the argument schema for each known command. When present:

- **RX** parses known commands deterministically by position and type (skips regex/heuristic scanning)
- **TX** validates arguments and rejects invalid commands — they are not added to the queue
- Unknown commands fall back to heuristic parsing automatically

Supported arg types: `str`, `int`, `float`, `epoch_ms`, `bool`. See the file header for full documentation.

## Configuration

| Variable | Default | Where |
|----------|---------|-------|
| `ZMQ_PORT` | `52001` | MAV_RX2 — downlink subscribe port |
| `ZMQ_ADDR` | `tcp://127.0.0.1:52002` | MAV_TX2 — uplink publish port |
| `ZMQ_RECV_TIMEOUT_MS` | `200` | MAV_RX2 — receive timeout (ms) |
| `LOG_DIR` | `logs` | Both — log output directory |
| `CMD_DEFS_PATH` | `maveric_commands.yml` | Both — command schema file |

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
