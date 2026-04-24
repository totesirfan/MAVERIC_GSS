"""Minimal non-MAVERIC fixture mission.

Echo proves a mission can run without nodes, ptypes, routing, CSP/AX.25,
telemetry domains, custom routers, or mission-specific frontend pages —
commands are free-form ASCII lines.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mav_gss_lib.platform import (
    Cell,
    ColumnDef,
    CommandDraft,
    CommandOps,
    CommandRendering,
    DetailBlock,
    EncodedCommand,
    FramedCommand,
    MissionConfigSpec,
    MissionContext,
    MissionPacket,
    MissionSpec,
    NormalizedPacket,
    PacketEnvelope,
    PacketFlags,
    PacketOps,
    PacketRendering,
    ValidationIssue,
)


@dataclass(frozen=True, slots=True)
class EchoPacketOps(PacketOps):
    def normalize(self, meta: dict[str, Any], raw: bytes) -> NormalizedPacket:
        return NormalizedPacket(raw=raw, payload=raw, frame_type="RAW")

    def parse(self, normalized: NormalizedPacket) -> MissionPacket:
        return MissionPacket(payload={"hex": normalized.payload.hex()})

    def classify(self, packet: MissionPacket) -> PacketFlags:
        return PacketFlags(is_unknown=False)


@dataclass(frozen=True, slots=True)
class EchoCommandOps(CommandOps):
    def parse_input(self, value: str | dict[str, Any]) -> CommandDraft:
        if isinstance(value, dict):
            line = str(value.get("line", ""))
        else:
            line = value
        line = line.strip()
        if not line:
            raise ValueError("empty command input")
        return CommandDraft({"line": line})

    def validate(self, draft: CommandDraft) -> list[ValidationIssue]:
        return []

    def encode(self, draft: CommandDraft) -> EncodedCommand:
        line = str(draft.payload["line"])
        return EncodedCommand(raw=line.encode("ascii"), mission_payload={"line": line})

    def frame(self, encoded: EncodedCommand) -> FramedCommand:
        return FramedCommand(wire=encoded.raw, frame_label="RAW")

    def render(self, encoded: EncodedCommand) -> CommandRendering:
        line = str(encoded.mission_payload.get("line", ""))
        return CommandRendering(
            title=line.split()[0] if line else "echo",
            row={"cmd": Cell(line, monospace=True)},
            detail_blocks=[
                DetailBlock(
                    kind="command",
                    label="Echo Command",
                    fields=[{"name": "Input", "value": line}],
                )
            ],
        )

    def schema(self) -> dict[str, Any]:
        return {}

    def tx_columns(self) -> list[ColumnDef]:
        return [ColumnDef("cmd", "command", flex=True)]


@dataclass(frozen=True, slots=True)
class EchoUiOps:
    def packet_columns(self) -> list[ColumnDef]:
        return [
            ColumnDef("num", "#", width="w-10", align="right"),
            ColumnDef("time", "time", width="w-[72px]"),
            ColumnDef("size", "size", width="w-12", align="right"),
            ColumnDef("hex", "hex", flex=True),
        ]

    def tx_columns(self) -> list[ColumnDef]:
        return [ColumnDef("cmd", "command", flex=True)]

    def render_packet(self, packet: PacketEnvelope) -> PacketRendering:
        hex_value = packet.mission_payload.get("hex", "") if isinstance(packet.mission_payload, dict) else ""
        return PacketRendering(
            columns=self.packet_columns(),
            row={
                "num": Cell(packet.seq),
                "time": Cell(packet.received_at_short, monospace=True),
                "size": Cell(len(packet.raw)),
                "hex": Cell(hex_value, monospace=True),
            },
            detail_blocks=[
                DetailBlock(
                    kind="raw",
                    label="Raw Data",
                    fields=[
                        {"name": "Size", "value": str(len(packet.raw))},
                        {"name": "Hex", "value": packet.raw.hex()},
                    ],
                )
            ],
        )

    def render_log_data(self, packet: PacketEnvelope) -> dict[str, Any]:
        return {"hex": packet.raw.hex()}

    def format_text_log(self, packet: PacketEnvelope) -> list[str]:
        return [f"  RAW         {packet.raw.hex()}"]


def build(ctx: MissionContext) -> MissionSpec:
    return MissionSpec(
        id="echo_v2",
        name="Echo V2",
        packets=EchoPacketOps(),
        commands=EchoCommandOps(),
        ui=EchoUiOps(),
        config=MissionConfigSpec(),
    )
