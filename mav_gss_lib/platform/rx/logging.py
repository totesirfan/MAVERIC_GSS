"""RX log formatters — JSONL envelope + text lines for inbound packets.

The envelope is a unified shape shared with TX
(see ``mav_gss_lib/platform/tx/logging.py``) so SQL ingest sees one stable
schema across both sides: every record carries `event_id`, `event_kind`,
`ts_ms`, `ts_iso`, `session_id`, `seq`, `v`, `mission_id`, `operator`,
`station`. Mission-owned content sits under a single `mission` sub-dict;
telemetry fragments are emitted as separate `event_kind="telemetry"` records
back-pointing to the parent rx_packet via `rx_event_id`.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from typing import Any, Iterator

from .._log_envelope import new_event_id, ts_iso
from ..contract.mission import MissionSpec
from ..contract.packets import PacketEnvelope
from .rendering import format_text_log_safe, render_log_data_safe


def rx_log_record(
    mission: MissionSpec,
    packet: PacketEnvelope,
    version: str,
    *,
    session_id: str,
    event_id: str | None = None,
    mission_id: str = "",
    operator: str = "",
    station: str = "",
) -> dict[str, Any]:
    """Build the platform-owned RX JSONL envelope for a packet.

    The mission-owned payload lives under the `mission` key (always present,
    `{}` when the mission has nothing to contribute). Nested rendering and
    telemetry arrays that used to live on this record are not written to
    disk anymore — rendering is re-derived from canonical fields at view
    time, and telemetry is emitted as its own event kind.
    """

    event_id = event_id or new_event_id()
    mission_data = render_log_data_safe(mission, packet) or {}
    return {
        "event_id": event_id,
        "event_kind": "rx_packet",
        "session_id": session_id,
        "ts_ms": packet.received_at_ms,
        "ts_iso": ts_iso(packet.received_at_ms),
        "seq": packet.seq,
        "v": version,
        "mission_id": mission_id or mission.id,
        "operator": operator,
        "station": station,
        "frame_type": packet.frame_type,
        "transport_meta": str(packet.transport_meta.get("transmitter", "")),
        "wire_hex": packet.raw.hex(),
        "wire_len": len(packet.raw),
        "inner_hex": packet.payload.hex(),
        "inner_len": len(packet.payload),
        "duplicate": packet.flags.is_duplicate,
        "uplink_echo": packet.flags.is_uplink_echo,
        "unknown": packet.flags.is_unknown,
        "warnings": list(packet.warnings),
        "mission": mission_data,
    }


def rx_telemetry_records(
    packet: PacketEnvelope,
    *,
    session_id: str,
    rx_event_id: str,
    version: str,
    mission_id: str,
    operator: str = "",
    station: str = "",
) -> Iterator[dict[str, Any]]:
    """Yield one JSONL record per TelemetryFragment attached to *packet*.

    Each record shares the packet's envelope (seq, ts_ms, session_id,
    operator, station) and back-points to the parent rx_packet via
    `rx_event_id`, so SQL can JOIN telemetry against events for packet-
    level context without reparsing the packet envelope on every row.
    """
    for fragment in packet.telemetry:
        yield {
            "event_id": new_event_id(),
            "event_kind": "telemetry",
            "session_id": session_id,
            "ts_ms": fragment.ts_ms or packet.received_at_ms,
            "ts_iso": ts_iso(fragment.ts_ms or packet.received_at_ms),
            "seq": packet.seq,
            "v": version,
            "mission_id": mission_id,
            "operator": operator,
            "station": station,
            "rx_event_id": rx_event_id,
            "domain": fragment.domain,
            "key": fragment.key,
            "value": fragment.value,
            "unit": fragment.unit,
            "display_only": fragment.display_only,
        }


def rx_log_text(mission: MissionSpec, packet: PacketEnvelope) -> list[str]:
    """Return mission text-log lines for a packet with failure isolation."""

    return format_text_log_safe(mission, packet)
