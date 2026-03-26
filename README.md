# MAVERIC Ground Station Software

Ground station tools for the MAVERIC CubeSat mission. Supports full-duplex operation with a single USRP B210 — simultaneous uplink and downlink using MAV_TX2 and MAV_RX2 with the shared GNU Radio MAV_DUPLEX flowgraph. Uplink echoes received on the downlink are automatically tagged (UL) for easy identification.

## Structure

```
mav_gss_lib/              Shared library
    protocol.py           Nodes, CSP v1, KISS, CRC-16/CRC-32C, command wire format,
                          frame normalization, TX command line parser
    transport.py          ZMQ PUB/SUB, PMT PDU send/receive, socket monitoring,
                          live connection status, send error handling
    config.py             Shared config loader (maveric_gss.yml), AX.25/CSP handlers
    parsing.py            RX packet processing pipeline (RxPipeline class)
    logging.py            Session logging (JSONL + text) for RX and TX
    curses_common.py      Shared curses utilities (colors, drawing, splash screen)
    curses_tx.py          TX dashboard panels and layout
    curses_rx.py          RX monitor panels and layout

MAV_RX2.py                Downlink packet monitor (curses)
MAV_TX2.py                Uplink command dashboard (curses)

maveric_gss.yml           Shared configuration (nodes, ptypes, AX.25, CSP, ZMQ, paths)
maveric_commands.yml      Command schema (arg names, types, validation)
maveric_decoder.yml       gr-satellites satellite definition file

logs/
    text/                 Human-readable text logs (downlink_*.txt, uplink_*.txt)
    json/                 Machine-readable JSONL logs (downlink_*.jsonl, uplink_*.jsonl)

legacy/                   Archived tools (not tracked in git)
    MAV_RX.py             Original terminal-based packet monitor
    MAV_TX_old.py         Original CLI command terminal
    display.py            ANSI terminal theme/box drawing (used by legacy scripts)
```

## MAV_RX2 — Packet Monitor (Curses)

Curses-based downlink packet monitor. Subscribes to a ZMQ PUB socket where GNU Radio publishes decoded PDUs and displays packets in a scrollable, interactive dashboard. A dedicated receiver thread ensures no packets are lost during UI redraws.

Layout:

- **Header** — ZMQ address, frequency (auto-detected from gr-satellites metadata), UTC/local clock, HEX/LOG toggle indicators, live ZMQ connection status (LIVE/DOWN/RETRY), queue depth
- **Packet List** — scrollable list with command src/dest routing, echo, packet type, command ID, arguments, payload size, CRC status, duplicate detection, uplink echo (UL) tagging. A packet is tagged UL when src=GS (our command echoed back) or when neither dest nor echo is GS (spoofed/relayed). Unparseable signals are shown as `UNKNOWN` with separate `U-N` numbering (valid packet count is unaffected). Auto-follows newest packets in `[LIVE]` mode
- **Packet Detail** — expanded view of selected packet (Enter to toggle): uplink echo flag, AX.25 header, CSP fields, satellite timestamp, command fields, hex dump, CRC verification. Unknown packets show only HEX, ASCII, and size
- **Input** — command entry with live status (Receiving/Silence timer, packet count, rate)

Typed commands:

| Command | Action |
|---------|--------|
| `help` | Toggle help panel |
| `cfg` / `config` | Toggle config panel (hex/log toggles) |
| `hex` | Toggle hex/ASCII display |
| `log` | Toggle logging on/off |
| `hclear` | Clear packet history |
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

- **Header** — AX.25 source/destination callsigns, CSP config, UTC and local time, live ZMQ connection status (LIVE/DOWN/BOUND), ZMQ port, frequency (437.25 MHz)
- **TX Queue** — commands waiting to be sent, with src/dest routing, echo, type, command ID, and args. Queue is persisted to disk (`.pending_queue.jsonl`) and restored on startup
- **Sent History** — transmitted commands with src→dest routing, echo, type metadata (scrollable)
- **Input** — command entry with cursor editing, command history recall (Up/Down)

Command format: `[SRC] DEST ECHO TYPE CMD [ARGS]` — SRC is optional (defaults to GS). Input is case-insensitive; command IDs are normalized to lowercase. Commands are validated against `maveric_commands.yml` and rejected with specific error messages (e.g. `unknown destination node 'CAM'`, `unknown packet type 'FOO'`). All commands go to the queue on Enter, then `Ctrl+S` sends the queue. Use `undo`/`pop` (or `Ctrl+Z`) to remove the last queued command, or `clear` (or `Ctrl+X`) to clear the entire queue.

Keyboard shortcuts:

| Key | Action |
|-----|--------|
| `Ctrl+S` | Send all queued commands (async — UI stays responsive) |
| `Ctrl+Z` | Remove last queued command |
| `Ctrl+X` | Clear the entire queue |
| `Up / Down` | Recall command history |
| `PgUp / PgDn` | Scroll sent history |
| `Ctrl+A / Ctrl+E` | Jump to start / end of input |
| `Ctrl+W / Ctrl+U` | Delete word / clear line |
| `Ctrl+C / Esc` | Abort send in progress (otherwise quit / close side panel) |

Side panels (appear to the right of sent history):

- **`config` / `cfg`** — editable configuration for AX.25 callsigns, CSP parameters, frequency, ZMQ address. Tab to focus, Up/Down to select, Enter to edit. Also shows the log file path.
- **`help`** — command format reference, keyboard shortcuts, schema info

## Usage

All scripts require the radioconda GNU Radio environment. **Start the GNU Radio MAV_DUPLEX flowgraph first** — the splash screen will remind you to confirm it is running before continuing.

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

Both RX and TX sessions produce paired log files in `logs/text/` (human-readable) and `logs/json/` (machine-readable JSONL):

- `downlink_YYYYMMDD_HHMMSS.txt` / `.jsonl` — RX packet log
- `uplink_YYYYMMDD_HHMMSS.txt` / `.jsonl` — TX command log

Both text logs share the same visual format:

- Thin `────` separator with packet/command number, timestamp, and flags inline
- Fixed 12-char label column for all fields
- Hex dumps wrapped at 16 bytes per line
- Session header with version, mode, and ZMQ address
- Session summary with counts and duration

**RX text log** includes: CSP header, satellite timestamp, command routing (short node names), schema-matched args, CRC-16/CRC-32C verification, hex+ASCII dump, and flags (DUP, UL, UNKNOWN).

**TX text log** includes: command routing and args, AX.25 callsigns + header hex, CSP config + header hex (captured at time of send — reflects runtime changes), CRC-16/CRC-32C computed values, size breakdown, raw command hex, full wrapped payload hex, and ASCII.

**TX JSONL** includes all routing fields (src/dest/echo/ptype with labels), AX.25 and CSP state, raw and wrapped hex, and CRC values.

RX logging can be toggled at runtime via the `log` command or config panel.

## Command Schema

`maveric_commands.yml` defines the argument schema for each known command. When present:

- **RX** parses known commands deterministically by position and type (skips regex/heuristic scanning)
- **TX** validates arguments and rejects invalid commands — they are not added to the queue
- Unknown commands fall back to heuristic parsing automatically

Supported arg types: `str`, `int`, `float`, `epoch_ms`, `bool`. See the file header for full documentation.

## Configuration

All startup defaults live in `maveric_gss.yml`, shared by both TX and RX scripts. Values can be changed at runtime via each TUI's config panel. Any changes that affect GNU Radio (e.g. ZMQ addresses, baud rate, modulation) require a restart of the MAV_DUPLEX flowgraph. Note that the frequency field is for display only — it does not control the radio. If the config file is missing, hardcoded defaults in `mav_gss_lib/config.py` are used.

```yaml
general:
  version: "2.4.0"          # displayed on splash screen
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

Early development (v2.4.0). Packet structure is finalized but telemetry arguments are not yet defined. Command definitions are maintained separately.
