"""Build the declarative MAVERIC telemetry + command capabilities.

Reads ``mission.yml`` via ``platform.spec.parse_yaml`` (with PLUGINS
bound), constructs a ``MaverPacketCodec`` from the parsed extensions,
constructs a ``MavericFramer`` from the live operator configs, then
hands both to Plan A's two factory functions.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from mav_gss_lib.platform.contract import CommandOps
from mav_gss_lib.platform.contract.telemetry import TelemetryOps
from mav_gss_lib.platform.spec import (
    Mission,
    ParseWarning,
    build_declarative_command_ops,
    build_declarative_telemetry_ops,
    parse_yaml,
)

from mav_gss_lib.missions.maveric.codec import MaverPacketCodec
from mav_gss_lib.missions.maveric.commands.framing import MavericFramer
from mav_gss_lib.missions.maveric.plugins import PLUGINS


@dataclass(frozen=True, slots=True)
class DeclarativeCapabilities:
    mission: Mission
    packet_codec: MaverPacketCodec
    telemetry_ops: TelemetryOps
    command_ops: CommandOps
    parse_warnings: tuple[ParseWarning, ...]


def build_declarative_capabilities(
    *,
    mission_yml_path: str | Path,
    platform_cfg: Mapping[str, Any],
    mission_cfg: Mapping[str, Any],
) -> DeclarativeCapabilities:
    mission = parse_yaml(Path(mission_yml_path), plugins=PLUGINS)
    codec = MaverPacketCodec(extensions=mission.extensions)
    uplink_mode = (platform_cfg.get("tx") or {}).get("uplink_mode", "ASM+Golay")
    framer = MavericFramer.from_mission_config(
        dict(mission_cfg),
        uplink_mode=uplink_mode,
    )
    telemetry_ops = build_declarative_telemetry_ops(
        mission, PLUGINS, packet_attr="walker_packet",
    )
    command_ops = build_declarative_command_ops(
        mission, PLUGINS, packet_codec=codec, framer=framer,
    )
    return DeclarativeCapabilities(
        mission=mission,
        packet_codec=codec,
        telemetry_ops=telemetry_ops,
        command_ops=command_ops,
        parse_warnings=tuple(mission.parse_warnings),
    )
