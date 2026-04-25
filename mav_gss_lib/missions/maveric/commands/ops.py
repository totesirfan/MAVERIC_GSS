"""MAVERIC CommandOps implementation.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mav_gss_lib.missions.maveric.commands import builder as tx_ops
from mav_gss_lib.missions.maveric.ui import rendering
from mav_gss_lib.missions.maveric.commands.parser import cmd_line_to_payload
from mav_gss_lib.missions.maveric.commands.framing import MavericFramer
from mav_gss_lib.missions.maveric.nodes import NodeTable
from mav_gss_lib.platform import (
    Cell,
    ColumnDef,
    CommandDraft,
    CommandOps,
    CommandRendering,
    DetailBlock,
    EncodedCommand,
    FramedCommand,
    ValidationIssue,
)


@dataclass(frozen=True, slots=True)
class MavericCommandOps(CommandOps):
    cmd_defs: dict
    nodes: NodeTable
    # Live references (stable identity). MAVERIC mutates through these on
    # every send/admission so runtime config updates take effect without a
    # MissionSpec rebuild.
    mission_config: dict[str, Any] = field(default_factory=dict)
    platform_config: dict[str, Any] = field(default_factory=dict)

    def parse_input(self, value: str | dict[str, Any]) -> CommandDraft:
        if isinstance(value, str):
            return CommandDraft(cmd_line_to_payload(value, self.cmd_defs, self.nodes))
        if isinstance(value, dict):
            return CommandDraft(dict(value))
        raise ValueError("command input must be a string or dict")

    def validate(self, draft: CommandDraft) -> list[ValidationIssue]:
        try:
            tx_ops.build_tx_command(draft.payload, self.cmd_defs, self.nodes)
        except ValueError as exc:
            return [ValidationIssue(str(exc))]
        return []

    def encode(self, draft: CommandDraft) -> EncodedCommand:
        result = tx_ops.build_tx_command(draft.payload, self.cmd_defs, self.nodes)
        return EncodedCommand(
            raw=result["raw_cmd"],
            guard=bool(result.get("guard", False)),
            mission_payload={
                "payload": dict(draft.payload),
                "display": result.get("display", {}),
            },
        )

    def frame(self, encoded: EncodedCommand) -> FramedCommand:
        tx_section = self.platform_config.get("tx") or {}
        uplink_mode = str(tx_section.get("uplink_mode", "AX.25"))
        framer = MavericFramer.from_mission_config(self.mission_config, uplink_mode=uplink_mode)
        return framer.frame(encoded)

    def render(self, encoded: EncodedCommand) -> CommandRendering:
        display = encoded.mission_payload.get("display", {})
        row = {
            key: Cell(value, badge=(key == "ptype"))
            for key, value in (display.get("row") or {}).items()
        }
        detail_blocks = [
            DetailBlock(
                kind=str(block.get("kind", "")),
                label=str(block.get("label", "")),
                fields=list(block.get("fields", [])),
            )
            for block in display.get("detail_blocks", [])
        ]
        return CommandRendering(
            title=str(display.get("title", "")),
            subtitle=str(display.get("subtitle", "")),
            row=row,
            detail_blocks=detail_blocks,
        )

    def schema(self) -> dict[str, Any]:
        return self.cmd_defs

    def tx_columns(self) -> list[ColumnDef]:
        return [ColumnDef.from_dict(col) for col in rendering.tx_queue_columns()]

    def correlation_key(self, encoded: EncodedCommand) -> tuple:
        # encoded.mission_payload shape from `encode()`:
        #   {"payload": dict(draft.payload), "display": {...}}
        # Correlation is at (cmd_id, dest) granularity. `args` is intentionally
        # NOT part of the key: downlink responses carry only cmd_id+src+ptype,
        # so they cannot be disambiguated by args anyway. Admission blocks all
        # repeat sends of the same cmd_id→dest until the prior CheckWindow
        # closes (i.e., instance reaches a terminal stage).
        payload = {}
        if isinstance(encoded.mission_payload, dict):
            payload = encoded.mission_payload.get("payload") or {}
        cmd_id = payload.get("cmd_id", "")
        dest = payload.get("dest", "")
        return (cmd_id, dest)

    def verifier_set(self, encoded: EncodedCommand):
        from .verifiers import derive_verifier_set, apply_override
        from mav_gss_lib.platform.tx.verifiers import VerifierSet
        payload = {}
        if isinstance(encoded.mission_payload, dict):
            payload = encoded.mission_payload.get("payload") or {}
        cmd_id = payload.get("cmd_id", "")
        dest = payload.get("dest", "")
        # Deprecated commands (ping, pang) skip verification entirely —
        # an empty VerifierSet, which Task 16 detects and skips register()
        # for. No parallel-instance confusion vs com_ping.
        if (self.cmd_defs.get(cmd_id) or {}).get("deprecated"):
            return VerifierSet(verifiers=())
        base = derive_verifier_set(cmd_id=cmd_id, dest=dest)
        override = (self.cmd_defs.get(cmd_id) or {}).get("verifiers")
        if override:
            return apply_override(base, override=override)
        return base
