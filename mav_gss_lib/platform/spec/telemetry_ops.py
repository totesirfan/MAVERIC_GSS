"""build_declarative_telemetry_ops factory + DeclarativeWalkerExtractor.

The extractor reads the already-unwrapped MaverPacket off
PacketEnvelope.mission_payload.maver_packet — does NOT call
packet_codec.unwrap. The mission's PacketOps.parse owns that single
unwrap call (parse-once contract from spec §5.1).
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

from mav_gss_lib.platform.contract.packets import PacketEnvelope
from mav_gss_lib.platform.contract.telemetry import (
    TelemetryDomainSpec,
    TelemetryExtractor,
    TelemetryOps,
)
from mav_gss_lib.platform.telemetry import TelemetryFragment

from .catalog import CatalogBuilder
from .mission import Mission
from .runtime import DeclarativeWalker


class DeclarativeWalkerExtractor:
    """Adapter — wraps DeclarativeWalker into the platform
    TelemetryExtractor protocol. Reads the already-unwrapped MaverPacket
    directly off PacketEnvelope.mission_payload; does NOT re-parse or
    re-CRC the envelope on every packet.
    """

    __slots__ = ("_walker",)

    def __init__(self, walker: DeclarativeWalker) -> None:
        self._walker = walker

    def extract(self, packet: PacketEnvelope) -> Iterable[TelemetryFragment]:
        wp = packet.mission_payload.maver_packet
        return self._walker.extract(wp, packet.received_at_ms)


def build_declarative_telemetry_ops(
    mission: Mission, plugins: Mapping[str, Callable],
) -> TelemetryOps:
    walker = DeclarativeWalker(mission, plugins)
    extractor = DeclarativeWalkerExtractor(walker)
    catalog_builder = CatalogBuilder(mission)

    domains: dict[str, TelemetryDomainSpec] = {}
    for domain in mission.declared_domains():
        domains[domain] = TelemetryDomainSpec(
            catalog=lambda d=domain: catalog_builder.for_domain(d),
        )

    return TelemetryOps(domains=domains, extractors=[extractor])


__all__ = [
    "DeclarativeWalkerExtractor",
    "build_declarative_telemetry_ops",
]
