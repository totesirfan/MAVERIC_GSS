# MAVERIC Ground Station Software

Ground station tools for the MAVERIC CubeSat mission. Receives and displays decoded satellite frames, and provides a command terminal for uplink operations.

## Structure

```
mav_gss_lib/              Shared library
    protocol.py           Nodes, CSP v1, KISS, CRC-16/CRC-32C, command wire format
    transport.py          ZMQ PUB/SUB, PMT PDU send/receive
    config.py             Shared config loader (maveric_gss.yml)
    curses_common.py      Shared curses utilities (colors, drawing, splash screen)
    curses_tx.py          TX dashboard panels and layout
    curses_rx.py          RX monitor panels and layout

MAV_RX2.py                Downlink packet monitor (curses)
MAV_TX2.py                Uplink command dashboard (curses)

maveric_gss.yml           Shared configuration (AX.25, CSP, ZMQ, paths, version)
maveric_commands.yml      Command schema (arg names, types, validation)
maveric_decoder.yml       gr-satellites satellite definition file

legacy/                   Archived tools (not tracked in git)
    MAV_RX.py             Original terminal-based packet monitor
    MAV_TX_old.py         Original CLI command terminal
    display.py            ANSI terminal theme/box drawing (used by legacy scripts)
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

All scripts require the radioconda GNU Radio environment. **Start your GNU Radio flowgraph first** — the splash screen will remind you to confirm it is running before continuing.

```bash
conda activate gnuradio

# Downlink monitor (curses)
python3 MAV_RX2.py
python3 MAV_RX2.py --nosplash   # skip startup splash screen

# Uplink command dashboard (curses)
python3 MAV_TX2.py
python3 MAV_TX2.py --nosplash
```

The splash screen displays the current configuration (ZMQ address, frequency, AX.25/CSP settings, version) and waits for a keypress before entering the dashboard.

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

All startup defaults live in `maveric_gss.yml`, shared by both TX and RX scripts. Values can be changed at runtime via each TUI's config panel. Any changes that affect GNURadio (e.g. ZMQ addresses, baud rate, modulation) require a restart of the flowgraph. Note that the frequency field is for display only — it does not control the radio. If the config file is missing, hardcoded defaults in `mav_gss_lib/config.py` are used.

```yaml
general:
  version: "2.2.1"          # displayed on splash screen
  log_dir: "logs"
  command_defs: "maveric_commands.yml"
  decoder_yml: "maveric_decoder.yml"

ax25:                        # TX only
  src_call: "WM2XBB"        # ground station callsign
  dest_call: "WS9XSW"       # satellite callsign
  src_ssid / dest_ssid: 0

csp:                         # TX only
  priority: 2
  source: 0                  # ground station address
  destination: 8             # satellite address
  dest_port: 0 / src_port: 24
  flags: 0x00

tx:
  zmq_addr: "tcp://127.0.0.1:52002"
  frequency: "437.25 MHz"
  delay_ms: 500

rx:
  zmq_port: 52001
  zmq_addr: "tcp://127.0.0.1:52001"
```

## Decoder

`maveric_decoder.yml` is the gr-satellites satellite definition file. It configures three transmitter modes on 437.250 MHz:

- 19k2 FSK AX.25 G3RUH
- 4k8 FSK AX.25 G3RUH
- 4k8 FSK AX100 ASM+Golay

## Dependencies

- [radioconda](https://github.com/ryanvolz/radioconda) (GNU Radio 3.10+, gr-satellites, PyZMQ, pmt)
- `crc` Python package (`pip install crc` in the gnuradio env)
- `pyyaml` Python package (`pip install pyyaml` — needed for config and command schema)

## Status

Early development (v2.2.2). Packet structure is finalized but telemetry arguments are not yet defined. Command definitions are maintained separately.
