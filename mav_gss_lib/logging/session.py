"""RX session log — JSONL + text entries for inbound platform packets.

Author:  Irfan Annuar - USC ISI SERC
"""

from typing import Iterable

from mav_gss_lib.constants import DEFAULT_MISSION_NAME

from ._base import _BaseLog


class SessionLog(_BaseLog):
    """RX session log — JSONL (rx_packet + telemetry events) + text."""

    def __init__(self, log_dir, zmq_addr, version="", mission_name=DEFAULT_MISSION_NAME,
                 *, mission_id: str = "", station: str = "", operator: str = "", host: str = ""):
        super().__init__(log_dir, "downlink", version, "RX Monitor", zmq_addr,
                         mission_name=mission_name, mission_id=mission_id,
                         station=station, operator=operator, host=host)

    def write_packet(self, record, packet, *,
                     telemetry_records: Iterable[dict] | None = None,
                     text_lines=None):
        """Write one rx_packet record + any telemetry-event rows + text entry.

        *record* is the pre-built JSONL envelope from
        ``mav_gss_lib.platform.rx.logging.rx_log_record``. *telemetry_records*
        is the iterable of flat telemetry events (one per
        ``TelemetryFragment``) from ``rx_telemetry_records``. Both land in
        the same JSONL file; the packet record goes first so an ingest
        streaming through the file sees the parent before its children.
        The text log keeps its existing per-packet layout.
        """
        self.write_jsonl(record)
        if telemetry_records:
            for tel in telemetry_records:
                self.write_jsonl(tel)

        lines = []
        label = f"#{packet.seq}"
        extras = f"{packet.frame_type}  {len(packet.raw)}B -> {len(packet.payload)}B"
        if packet.flags.is_duplicate:
            extras += "  [DUP]"
        if packet.flags.is_uplink_echo:
            extras += "  [UL]"
        lines.append(self._separator(label, extras, ts_ms=packet.received_at_ms))
        if packet.flags.is_uplink_echo:
            lines.append("  UPLINK ECHO")

        for warning in packet.warnings:
            lines.append(self._field("WARNING", warning))

        lines.extend(text_lines or [])
        lines.extend(self._hex_lines(packet.raw, "HEX"))

        try:
            text = packet.raw.decode("utf-8", errors="ignore").strip()
        except Exception:
            text = ""
        if text:
            lines.append(self._field("ASCII", text))

        self._write_entry(lines)
