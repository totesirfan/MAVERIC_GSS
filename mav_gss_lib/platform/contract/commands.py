"""Command contracts for the mission boundary.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, NotRequired, Protocol, Required, TypedDict

from .parameters import ParamUpdate


class TxArgSchema(TypedDict):
    """Single TX argument as exposed by /api/schema. Mirrored on the TS
    side as `lib/types.ts::TxArgSchema`.

    `name` and `type` are unconditionally required by the runtime;
    everything else is type-driven metadata that may be absent for
    primitive ArgumentTypes. Required/NotRequired makes that invariant
    enforceable by mypy — `total=False` would let typecheckers accept
    a value with no `name`, which contradicts what Task 8's
    `inline_argument_metadata` actually emits.
    """
    name: Required[str]
    type: Required[str]
    description: NotRequired[str]
    important: NotRequired[bool]
    optional: NotRequired[bool]
    valid_range: NotRequired[list[float] | None]
    valid_values: NotRequired[list[float | int | str] | None]


class CommandSchemaItem(TypedDict):
    """Mission-agnostic /api/schema item. Carries ONLY platform-level
    fields — no routing/transport concepts. Missions extend this for
    their own routing surfaces (see e.g.
    `missions/maveric/schema_types.py::MavericCommandSchemaItem`,
    which adds `dest`/`echo`/`ptype`/`nodes`).

    Why not put MAVERIC routing here: per the Mission/Platform
    boundary (CLAUDE.md), command grammar/routing is mission-owned.
    The platform contract advertises only the universal TX surface;
    routing concepts that are mission-specific (CSP-style dest/echo
    /ptype, node directories) belong to that mission's TypedDict
    extension. Adding them to the platform contract would couple
    every future deployment-target mission to MAVERIC's transport
    shape.

    `tx_args` is required (Task 8 always emits it, possibly empty).
    Everything else is optional UX/contract metadata.
    """
    tx_args: Required[list[TxArgSchema]]
    description: NotRequired[str]
    title: NotRequired[str]
    label: NotRequired[str]
    variadic: NotRequired[bool]
    guard: NotRequired[bool]
    rx_only: NotRequired[bool]
    deprecated: NotRequired[bool]
    verifiers: NotRequired[dict[str, object]]


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
    """Fully encoded mission command + display payload.

    `raw` is the mission-built inner PDU. `cmd_id` is an optional opaque
    command label for operator-facing logs/UI. `mission_facts` is the
    opaque display dict consumed by declarative TX columns and the detail
    panel — mirrors the RX `MissionFacts.facts` shape (`{header, protocol,
    ...}`). `parameters` carries typed arguments for the detail panel,
    paralleling RX `parameters`.
    """

    raw: bytes
    cmd_id: str = ""
    src: str = ""
    guard: bool = False
    mission_facts: dict[str, Any] = field(default_factory=dict)
    parameters: tuple[ParamUpdate, ...] = ()


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


class CommandOps(Protocol):
    """Optional mission command capability.

    The platform owns queue persistence, ordering, guard confirmation, delays,
    transport send state, TX logging envelope, verifier derivation from
    declarative spec rules, and column definitions (read from
    `mission.yml::ui.tx_columns`). Missions own command grammar, validation
    semantics, byte encoding, wire framing (including any mission-specific
    header/FEC/modulation-prep steps), correlation-key shape, and MTU
    admission. Display fields populate `EncodedCommand.mission_facts` /
    `parameters` for declarative rendering.
    """

    def parse_input(self, value: str | dict[str, Any]) -> CommandDraft: ...

    def validate(self, draft: CommandDraft) -> list[ValidationIssue]: ...

    def encode(self, draft: CommandDraft) -> EncodedCommand: ...

    def frame(self, encoded: EncodedCommand) -> FramedCommand: ...

    def correlation_key(self, encoded: EncodedCommand) -> tuple: ...
    """Return an opaque, hashable correlation key for this command.

    Used by the admission gate and by match_verifiers to associate inbound
    packets with open command instances. The key is mission-defined; arguments
    are commonly excluded so admission can block at per-target granularity.
    """

    def schema(self) -> Mapping[str, CommandSchemaItem]: ...
