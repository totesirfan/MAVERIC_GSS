"""MAVERIC-specific runtime errors raised by MaverPacketCodec.

These previously lived in ``mav_gss_lib.platform.spec.errors`` but were
dropped during the Plan A platform/mission boundary cleanup because they
encode MAVERIC routing-table semantics. They live mission-side so the
platform spec runtime stays generic.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass


class MavericCodecError(Exception):
    """Root for MAVERIC packet-codec errors."""


@dataclass
class UnknownNodeId(MavericCodecError):
    """Raw byte at a node-id field has no entry in mission.extensions['nodes']."""

    field: str
    value: int

    def __str__(self) -> str:
        return f"unknown node id {self.value!r} in field {self.field!r}"


@dataclass
class UnknownPtypeId(MavericCodecError):
    """Raw byte at the ptype field has no entry in mission.extensions['ptypes']."""

    value: int

    def __str__(self) -> str:
        return f"unknown ptype id {self.value!r}"


@dataclass
class DuplicateNodeId(MavericCodecError):
    """mission.extensions['nodes'] maps two names to the same int."""

    name_a: str
    name_b: str
    value: int

    def __str__(self) -> str:
        return f"node id {self.value} declared for both {self.name_a!r} and {self.name_b!r}"


@dataclass
class DuplicatePtypeId(MavericCodecError):
    """mission.extensions['ptypes'] maps two names to the same int."""

    name_a: str
    name_b: str
    value: int

    def __str__(self) -> str:
        return f"ptype id {self.value} declared for both {self.name_a!r} and {self.name_b!r}"


@dataclass
class NodeIdOutOfRange(MavericCodecError):
    """Node id is outside the u8 range [0, 255]."""

    name: str
    value: int

    def __str__(self) -> str:
        return f"node id {self.value} for {self.name!r} is out of u8 range [0, 255]"


@dataclass
class PtypeIdOutOfRange(MavericCodecError):
    """Ptype id is outside the u8 range [0, 255]."""

    name: str
    value: int

    def __str__(self) -> str:
        return f"ptype id {self.value} for {self.name!r} is out of u8 range [0, 255]"
