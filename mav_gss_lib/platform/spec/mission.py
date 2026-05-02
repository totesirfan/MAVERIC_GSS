"""Mission root dataclass — the parser's output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

from .argument_types import ArgumentType
from .bitfield import BitfieldType
from .commands import MetaCommand
from .containers import SequenceContainer
from .parameters import Parameter
from .parameter_types import ParameterType
from .verifier_decls import VerifierRules, VerifierSpecDecl

if TYPE_CHECKING:
    from .framing import FramingSpec
    from .ui import UiSpec


@dataclass(frozen=True, slots=True)
class MissionHeader:
    version: str
    date: str
    description: str = ""


# ---- Parse warnings (non-fatal; fatal issues raise ParseError) ----


class ParseWarning:
    """Base class for non-fatal mission-author warnings."""


@dataclass(frozen=True, slots=True)
class ContainerShadow(ParseWarning):
    broader: str
    specific: str

    def __str__(self) -> str:
        return (
            f"container {self.broader!r} (broader equality signature) precedes "
            f"{self.specific!r} (more specific) in YAML order; "
            f"{self.specific!r} will never match — reorder if intended"
        )


@dataclass(frozen=True, slots=True)
class EnumSliceTruncation(ParseWarning):
    bitfield: str
    slice_name: str
    slice_width: int
    enum_max_raw: int

    def __str__(self) -> str:
        return (
            f"bitfield {self.bitfield!r} slice {self.slice_name!r} is "
            f"{self.slice_width} bit(s) but referenced enum has max raw value "
            f"{self.enum_max_raw} — truncation hazard"
        )


@dataclass(frozen=True, slots=True)
class Mission:
    """Parser output: the fully-validated mission database.

    `extensions` carries arbitrary mission-specific data. The platform parser
    does not validate its shape; it is an opaque pass-through to the mission's
    PacketCodec.

    `parse_warnings` carries non-fatal authoring warnings. Fatal issues raise
    `ParseError` instead.
    """

    id: str
    name: str
    header: MissionHeader

    parameter_types: Mapping[str, ParameterType]
    argument_types: Mapping[str, ArgumentType]
    parameters: Mapping[str, Parameter]
    bitfield_types: Mapping[str, BitfieldType]
    sequence_containers: Mapping[str, SequenceContainer]
    meta_commands: Mapping[str, MetaCommand]

    extensions: Mapping[str, Any] = field(default_factory=dict)
    parse_warnings: tuple[ParseWarning, ...] = ()
    verifier_specs: Mapping[str, VerifierSpecDecl] = field(default_factory=dict)
    verifier_rules: VerifierRules | None = None
    framing: "FramingSpec | None" = None
    ui: "UiSpec | None" = None


__all__ = [
    "MissionHeader",
    "Mission",
    "ParseWarning",
    "ContainerShadow",
    "EnumSliceTruncation",
    "VerifierSpecDecl",
    "VerifierRules",
]
