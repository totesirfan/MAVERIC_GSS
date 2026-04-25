"""Command contracts for the mission boundary.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from .rendering import Cell, ColumnDef, DetailBlock

if TYPE_CHECKING:
    from mav_gss_lib.platform.tx.verifiers import VerifierSet


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    message: str
    field: str | None = None
    severity: str = "error"


@dataclass(frozen=True, slots=True)
class CommandDraft:
    payload: Any


@dataclass(frozen=True, slots=True)
class EncodedCommand:
    raw: bytes
    guard: bool = False
    mission_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FramedCommand:
    """Fully framed TX bytes plus mission-provided log hooks.

    The platform publishes `wire` on ZMQ exactly as returned — it does not
    add, strip, or inspect framing. `frame_label` is a short display tag
    (e.g. "AX.25", "ASM+Golay", "RAW") the platform may surface in the TX
    log envelope; platform logic does not branch on it.

    `max_payload`, when set, is the mission's admission cap for how large
    `EncodedCommand.raw` may be AFTER any mission-owned inner wrapping
    (CSP, framing headers, FEC), expressed as the size ceiling for `wire`.
    The platform enforces this on queue admission.

    `log_fields` are JSONL-safe key/value pairs the TX log merges into the
    per-command record. `log_text` is a list of pre-formatted human-readable
    lines (one per line, no trailing newline) the TX log writes alongside
    the hex dump of `wire`. Both are opaque to the platform.
    """

    wire: bytes
    frame_label: str = ""
    max_payload: int | None = None
    log_fields: dict[str, Any] = field(default_factory=dict)
    log_text: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CommandRendering:
    title: str
    subtitle: str = ""
    row: dict[str, Cell] = field(default_factory=dict)
    detail_blocks: list[DetailBlock] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "row": {k: v.to_json() for k, v in self.row.items()},
            "detail_blocks": [b.to_json() for b in self.detail_blocks],
        }


class CommandOps(Protocol):
    """Optional mission command capability.

    The platform owns queue persistence, ordering, guard confirmation, delays,
    transport send state, and TX logging envelope. Missions own command
    grammar, validation semantics, byte encoding, wire framing (including
    any mission-specific header/FEC/modulation-prep steps), MTU admission,
    and display metadata.
    """

    def parse_input(self, value: str | dict[str, Any]) -> CommandDraft: ...

    def validate(self, draft: CommandDraft) -> list[ValidationIssue]: ...

    def encode(self, draft: CommandDraft) -> EncodedCommand: ...

    def frame(self, encoded: EncodedCommand) -> FramedCommand: ...

    def render(self, encoded: EncodedCommand) -> CommandRendering: ...

    def correlation_key(self, encoded: EncodedCommand) -> tuple: ...
    """Return an opaque, hashable correlation key for this command.

    Used by the admission gate and by match_verifiers to associate inbound
    packets with open command instances. The key is mission-defined. For
    MAVERIC: (cmd_id, dest) — both strings. `args` is intentionally excluded
    because downlink responses carry only cmd_id+src+ptype; admission blocks
    strictly at per-target granularity.
    """

    def verifier_set(self, encoded: EncodedCommand) -> "VerifierSet": ...
    """Return the VerifierSet the platform should track for this command.

    Empty VerifierSet ("verification disabled") is legal — fixture missions
    and MAVERIC's FTDI destination both return empty.
    """

    def schema(self) -> dict[str, Any]: ...

    def tx_columns(self) -> list[ColumnDef]: ...
