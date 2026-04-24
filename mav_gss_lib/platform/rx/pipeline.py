"""End-to-end RX orchestration: packet → telemetry → render → events.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..contract.mission import MissionSpec
from ..contract.packets import PacketEnvelope
from ..telemetry import TelemetryRouter
from .events import collect_packet_events
from .packets import PacketPipeline
from .rendering import render_packet
from .telemetry import extract_telemetry_fragments, ingest_packet_telemetry


@dataclass(slots=True)
class RxResult:
    packet: PacketEnvelope
    packet_message: dict[str, Any]
    telemetry_messages: list[dict[str, Any]] = field(default_factory=list)
    event_messages: list[dict[str, Any]] = field(default_factory=list)


class RxPipeline:
    """Platform RX flow, independent of the web runtime.

    Ordering:
      1. packet normalize/parse/classify
      2. telemetry extract
      3. telemetry ingest
      4. packet render
      5. produce websocket-ready messages
    """

    def __init__(self, mission: MissionSpec, telemetry_router: TelemetryRouter) -> None:
        self.mission = mission
        self.packet_pipeline = PacketPipeline(mission)
        self.telemetry_router = telemetry_router

    def process(self, meta: dict[str, Any], raw: bytes) -> RxResult:
        packet = self.packet_pipeline.process(meta, raw)
        extract_telemetry_fragments(self.mission, packet)
        telemetry_messages = ingest_packet_telemetry(self.telemetry_router, packet)
        rendering = render_packet(self.mission, packet)
        event_messages = collect_packet_events(self.mission, packet)
        packet_message = {
            "type": "packet",
            "data": {
                "num": packet.seq,
                "time": packet.received_at_short,
                "time_utc": packet.received_at_text,
                "frame": packet.frame_type,
                "size": len(packet.raw),
                "raw_hex": packet.raw.hex(),
                "warnings": list(packet.warnings),
                "is_echo": packet.flags.is_uplink_echo,
                "is_dup": packet.flags.is_duplicate,
                "is_unknown": packet.flags.is_unknown,
                "_rendering": rendering.to_json(),
            },
        }
        return RxResult(
            packet=packet,
            packet_message=packet_message,
            telemetry_messages=telemetry_messages,
            event_messages=event_messages,
        )
