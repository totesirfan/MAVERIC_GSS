"""Packet contract — normalized/mission/envelope types plus mission PacketOps.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Hashable, Protocol

from ..telemetry import TelemetryFragment
from .rendering import PacketRendering

if TYPE_CHECKING:
    from mav_gss_lib.platform.tx.verifiers import CommandInstance, VerifierOutcome


@dataclass(frozen=True, slots=True)
class NormalizedPacket:
    raw: bytes
    payload: bytes
    frame_type: str
    stripped_header: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MissionPacket:
    payload: Any
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PacketFlags:
    duplicate_key: Hashable | None = None
    is_duplicate: bool = False
    is_unknown: bool = False
    is_uplink_echo: bool = False


@dataclass(slots=True)
class PacketEnvelope:
    seq: int
    received_at_ms: int
    received_at_text: str
    received_at_short: str
    raw: bytes
    payload: bytes
    frame_type: str
    transport_meta: dict[str, Any]
    warnings: list[str]
    mission_payload: Any
    flags: PacketFlags
    telemetry: list[TelemetryFragment] = field(default_factory=list)
    rendering: PacketRendering | None = None


class PacketOps(Protocol):
    """Mission packet capability.

    Missions own protocol/frame semantics. The platform owns sequencing,
    timestamps, duplicate-window state, rates, logging envelope, and fallback
    behavior.
    """

    def normalize(self, meta: dict[str, Any], raw: bytes) -> NormalizedPacket: ...

    def parse(self, normalized: NormalizedPacket) -> MissionPacket: ...

    def classify(self, packet: MissionPacket) -> PacketFlags: ...

    def match_verifiers(
        self,
        envelope: "PacketEnvelope",
        open_instances: list["CommandInstance"],
        *,
        now_ms: int,
        rx_event_id: str = "",
    ) -> list[tuple[str, str, "VerifierOutcome"]]: ...
    """Match this inbound packet envelope against open instances.

    Takes the full PacketEnvelope because:
      - `envelope.mission_payload` holds the mission-parsed dict (what the
        MAVERIC rx/parser emits: {"cmd": {...}, "ptype": ..., ...}).
      - `rx_event_id` (passed in by the server before log write) goes
        onto `VerifierOutcome.match_event_id` so verifier outcomes can
        back-point to the matched rx_packet log entry.

    Returns a list of (instance_id, verifier_id, outcome) transitions to apply.
    Empty list when the packet doesn't match any open verifier. Mission-private
    logic handles newest-instance-wins, ptype/src → verifier_id mapping, and
    pass/fail discrimination.
    """
