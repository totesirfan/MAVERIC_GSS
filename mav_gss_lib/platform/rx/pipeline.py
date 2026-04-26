"""End-to-end RX orchestration: packet → walker → parameter cache → render.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..contract.mission import MissionSpec
from ..contract.packets import PacketEnvelope
from ..parameters import ParameterCache
from ..spec.runtime import DeclarativeWalker
from .events import collect_packet_events
from .packets import PacketPipeline
from .rendering import render_packet


@dataclass(slots=True)
class RxResult:
    packet: PacketEnvelope
    packet_message: dict[str, Any]
    parameters_message: dict[str, Any] | None = None
    event_messages: list[dict[str, Any]] = field(default_factory=list)
    container_id: str | None = None


class RxPipeline:
    """Platform RX flow, independent of the web runtime.

    Ordering:
      1. packet normalize/parse/classify
      2. walker.extract → ParamUpdate stream
      3. ParameterCache.apply (LWW persistence + change detection)
      4. packet render
      5. produce websocket-ready messages
    """

    def __init__(
        self,
        mission: MissionSpec,
        walker: DeclarativeWalker | None,
        parameter_cache: ParameterCache,
    ) -> None:
        self.mission = mission
        self.packet_pipeline = PacketPipeline(mission)
        self.walker = walker
        self.cache = parameter_cache

    def process(self, meta: dict[str, Any], raw: bytes) -> RxResult:
        packet = self.packet_pipeline.process(meta, raw)
        wp = getattr(packet.mission_payload, "walker_packet", None)
        matched_container_id: str | None = None
        if self.walker is not None and wp is not None:
            parent = self.walker.match_parent(wp)
            matched_container_id = parent.name if parent is not None else None
            try:
                packet.parameters = tuple(self.walker.extract(wp, packet.received_at_ms))
            except Exception:
                logging.exception(
                    "walker.extract raised; dropping parameters for this packet"
                )
                packet.parameters = ()
        else:
            packet.parameters = ()

        changes = self.cache.apply(packet.parameters)
        parameters_message = (
            {"type": "parameters", "updates": changes} if changes else None
        )
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
            parameters_message=parameters_message,
            event_messages=event_messages,
            container_id=matched_container_id,
        )
