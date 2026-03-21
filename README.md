# MAVERIC Ground Station Software

Ground station tools for the MAVERIC CubeSat mission. Receives and displays decoded satellite frames, and provides a command terminal for uplink operations.

## Structure

```
mav_gss_lib/              Shared library
    protocol.py           Nodes, CSP, KISS, CRC, command wire format
    display.py            Theme class, box drawing, terminal formatting
    transport.py          ZMQ PUB/SUB, PMT PDU send/receive

MAV_RX.py                 Downlink packet monitor
MAV_TX.py                 Uplink command terminal
ax100_loopback_test.py    AX100 encoder verification

MAVERIC_TX.grc            GNU Radio TX flowgraph (AX100 ASM+Golay + GFSK)
MAVERIC_DECODER.yml       gr-satellites satellite definition file
Commands.py               Satellite-side command format (reference only)
```

## MAV_RX — Packet Monitor

Subscribes to a ZMQ PUB socket where GNU Radio publishes decoded PDUs and displays packet contents for live debugging. Designed to run continuously — the flowgraph can be started and stopped independently.

For each packet, the monitor shows:

- Packet count, ground station timestamp, and inter-packet timing
- Frame type (AX.25 or AX100), inferred from gr-satellites metadata
- Inner payload after stripping transport framing
- CSP v1 header candidate parse
- Satellite timestamp candidate (epoch-ms detection)
- Parsed command structure with node routing and arguments
- SHA-256 fingerprint for duplicate detection

With `--loud`, hex dump, ASCII, and CRC are also shown in the terminal. These are always written to the log files regardless.

Raw hex is ground truth. All parsed fields are diagnostic until the telemetry map is finalized.

## MAV_TX — Command Terminal

Interactive terminal for sending commands to the satellite. Commands are KISS-wrapped with a configurable CSP v1 header and published as PMT PDUs over ZMQ to a GNU Radio flowgraph that handles AX100 ASM+Golay encoding, GFSK modulation, and transmission.

Features:

- Single commands: `EPS PING`
- Batch mode: queue multiple commands with `+`, send as one AX100 frame
- Runtime CSP config: `csp dest 8`, `csp off`, etc.
- Command history and arrow key navigation (readline)
- JSONL uplink logging

## Usage

All scripts require the radioconda GNU Radio environment. Start your GNU Radio flowgraph first, then:

```bash
conda activate gnuradio

# Downlink monitor
python3 MAV_RX.py
python3 MAV_RX.py --loud       # includes hex, ASCII, CRC, SHA256
python3 MAV_RX.py --nolog      # display only, no log files

# Uplink command terminal
python3 MAV_TX.py

# AX100 encoder loopback test
python3 ax100_loopback_test.py
```

Press `Ctrl+C` to stop.

## Logging

Each monitor session writes two log files to `logs/`:

- `.jsonl` — machine-readable, one JSON object per packet
- `.txt` — human-readable plain text

The command terminal logs uplink transmissions to a separate `.jsonl` file. Logging can be disabled with `--nolog` on the monitor.

## Configuration

| Variable | Default | Where |
|----------|---------|-------|
| `ZMQ_PORT` | `52001` | MAV_RX — downlink subscribe port |
| `ZMQ_ADDR` | `tcp://127.0.0.1:52002` | MAV_TX — uplink publish port |
| `ZMQ_RECV_TIMEOUT_MS` | `200` | MAV_RX — receive timeout (ms) |
| `LOG_DIR` | `logs` | Both — log output directory |

## Theming

All terminal colors are defined in `mav_gss_lib/display.py` in the `Theme` class. Colors are assigned by semantic role (LABEL, VALUE, SUCCESS, WARNING, ERROR), not by raw ANSI code. To retheme both tools, edit `Theme` only.

## Decoder

`MAVERIC_DECODER.yml` is the gr-satellites satellite definition file. It configures three transmitter modes on 437.250 MHz:

- 19k2 FSK AX.25 G3RUH
- 4k8 FSK AX.25 G3RUH
- 4k8 FSK AX100 ASM+Golay

## Dependencies

- [radioconda](https://github.com/ryanvolz/radioconda) (GNU Radio 3.10+, gr-satellites, PyZMQ, pmt)
- `crc` Python package (`pip install crc` in the gnuradio env)

## Status

Early development. Telemetry structure is not yet finalized — the monitor shows raw packet data and diagnostic heuristics. Command definitions are maintained separately.