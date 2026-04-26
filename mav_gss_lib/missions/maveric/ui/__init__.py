"""MAVERIC operator-facing presentation — rows, details, logs.

The platform holds generic UI containers (packet list, detail pane, TX
queue, RX/TX log viewer) and calls `MavericUiOps` to fill them with
mission-specific content. This subpackage does not render pixels — it
returns structured `Cell` / `DetailBlock` / `IntegrityBlock` /
`PacketRendering` values that the frontend and the log formatters
consume.

Modules
-------
- `ops.py`        — `MavericUiOps`, the platform boundary. Exposes
  `packet_columns`, `render_packet`, `render_log_data`, and
  `format_text_log`. (TX-queue columns live with command-ops in
  `../declarative.py` — `CommandOps.tx_columns()`.)
- `rendering.py`  — per-packet layout: `packet_list_columns`,
  `packet_list_row`, `packet_detail_blocks`, `protocol_blocks` (CSP /
  AX.25 header views), `integrity_blocks` (CRC-16 / CRC-32C /
  Golay/RS status), and the shared `ts_result` time helper.
- `formatters.py` — atom-level formatting helpers shared by both
  `rendering.py` and `log_format.py` (ptype resolution, hex dumps,
  argument formatters, timestamp shaping).
- `log_format.py` — JSONL mission-data record shaping and human-
  readable text lines for the session log, used by `SessionLog` and
  the log viewer.
"""

from mav_gss_lib.missions.maveric.ui.ops import MavericUiOps

__all__ = ["MavericUiOps"]
