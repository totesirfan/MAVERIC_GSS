"""RX session log — JSONL + text entries for inbound platform packets.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from typing import Any, Iterable

from mav_gss_lib.constants import DEFAULT_MISSION_NAME

from ._base import _BaseLog


class SessionLog(_BaseLog):
    """RX session log — JSONL (rx_packet + parameter events) + text."""

    def __init__(
        self,
        log_dir: str,
        zmq_addr: str,
        version: str = "",
        mission_name: str = DEFAULT_MISSION_NAME,
        *,
        mission_id: str = "",
        station: str = "",
        operator: str = "",
        host: str = "",
    ) -> None:
        super().__init__(log_dir, "downlink", version, "RX Monitor", zmq_addr,
                         mission_name=mission_name, mission_id=mission_id,
                         station=station, operator=operator, host=host)

    def write_packet(
        self,
        record: dict[str, Any],
        packet: Any,
        *,
        parameter_records: Iterable[dict[str, Any]] | None = None,
        text_lines: list[str] | None = None,
    ) -> None:
        """Write one rx_packet record + any parameter-event rows + text entry.

        *record* is the pre-built JSONL envelope from
        ``mav_gss_lib.platform.rx.logging.rx_log_record``. *parameter_records*
        is the iterable of flat parameter events (one per ``ParamUpdate``)
        from ``parameter_log_records``. Both land in the same JSONL file;
        the packet record goes first so an ingest streaming through the
        file sees the parent before its children. The text log keeps its
        existing per-packet layout.
        """
        self.write_jsonl(record)
        if parameter_records:
            for p in parameter_records:
                self.write_jsonl(p)

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

    def write_alarm(self, change: Any, ts_ms: int) -> None:
        """Append one alarm-transition record using the unified envelope.

        Alarm events are out-of-band with respect to the RX packet stream, so
        ``seq`` is 0 by convention.  SQL ingest must not join on
        ``(session_id, seq)`` for ``event_kind="alarm"``; use
        ``(session_id, alarm.id, ts_ms)`` instead.
        """
        from mav_gss_lib.platform._log_envelope import new_event_id, ts_iso
        ev = change.event
        record = {
            "event_id": new_event_id(),
            "event_kind": "alarm",
            "session_id": self.session_id,
            "ts_ms": ts_ms,
            "ts_iso": ts_iso(ts_ms),
            "seq": 0,
            "v": self._version,
            "mission_id": self._mission_id,
            "operator": self._operator,
            "station": self._station,
            "alarm": {
                "id": ev.id,
                "source": str(ev.source),
                "label": ev.label,
                "detail": ev.detail,
                "severity": ev.severity.name.lower(),
                "state": str(ev.state),
                "prev_state": (
                    str(change.prev_state) if change.prev_state is not None else None
                ),
                "prev_severity": (
                    change.prev_severity.name.lower()
                    if change.prev_severity is not None else None
                ),
                "removed": change.removed,
                "first_seen_ms": ev.first_seen_ms,
                "last_transition_ms": ev.last_transition_ms,
                "context": ev.context,
                "operator": change.operator,
            },
        }
        self.write_jsonl(record)
