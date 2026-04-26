"""MAVERIC UiOps implementation — declarative shape.

Reads MaverMissionPayload + envelope.telemetry directly. Carries the
codec (for any future name-resolution renderer needs) and the parsed
Mission so display_kind dispatch can resolve parameter type calibrators.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from mav_gss_lib.missions.maveric.codec import MaverPacketCodec
from mav_gss_lib.missions.maveric.ui import log_format, rendering
from mav_gss_lib.platform import (
    Cell,
    ColumnDef,
    DetailBlock,
    IntegrityBlock,
    PacketEnvelope,
    PacketRendering,
)
from mav_gss_lib.platform.spec import Mission


def _detail(block: dict) -> DetailBlock:
    return DetailBlock(
        kind=str(block.get("kind", "")),
        label=str(block.get("label", "")),
        fields=list(block.get("fields", [])),
    )


@dataclass(frozen=True, slots=True)
class MavericUiOps:
    codec: MaverPacketCodec
    mission: Mission

    def packet_columns(self) -> list[ColumnDef]:
        return [ColumnDef.from_dict(col) for col in rendering.packet_list_columns()]

    def render_packet(self, packet: PacketEnvelope) -> PacketRendering:
        payload = packet.mission_payload
        row = rendering.packet_list_row(payload, packet)
        values = row.get("values", {})
        cells = {
            key: Cell(
                value=value,
                badge=(key == "ptype"),
                monospace=(key in {"time", "frame"}),
            )
            for key, value in values.items()
        }
        return PacketRendering(
            columns=self.packet_columns(),
            row=cells,
            detail_blocks=[
                _detail(block)
                for block in rendering.packet_detail_blocks(payload, packet, self.mission)
            ],
            protocol_blocks=[
                _detail(asdict(block))
                for block in rendering.protocol_blocks(payload, packet)
            ],
            integrity_blocks=[
                IntegrityBlock(**asdict(block))
                for block in rendering.integrity_blocks(payload, packet)
            ],
        )

    def render_log_data(self, packet: PacketEnvelope) -> dict[str, Any]:
        return log_format.build_log_mission_data(packet.mission_payload, packet, self.mission)

    def format_text_log(self, packet: PacketEnvelope) -> list[str]:
        return log_format.format_log_lines(packet.mission_payload, packet, self.mission)
