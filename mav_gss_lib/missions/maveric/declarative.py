"""Build the declarative MAVERIC telemetry + command capabilities.

Reads ``mission.yml`` via ``platform.spec.parse_yaml`` (with PLUGINS
bound), constructs a ``MaverPacketCodec`` from the parsed extensions,
constructs a ``MavericFramer`` from the live operator configs, then
hands both to Plan A's two factory functions.

Wraps the declarative command_ops with a frontend-compat translator
that accepts both the legacy MAVERIC flat shape
(``{cmd_id, args, dest, echo, ptype, guard}``) and the canonical
declarative shape (``{cmd_id, args:dict, packet:dict}``). The frontend
TX builder + queue.py admission test fixtures emit the flat shape; the
walker requires header fields under ``packet``. Wrapping at the mission
boundary keeps the declarative adapter pristine and keeps the operator
surface stable across the cut-over.

Wraps the framer with a live-config rebinder so AX.25 callsign / CSP
header changes through ``/api/config`` take effect on the next send
without a MissionSpec rebuild.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from mav_gss_lib.platform.contract import CommandOps
from mav_gss_lib.platform.contract.commands import (
    CommandDraft,
    EncodedCommand,
    FramedCommand,
)
from mav_gss_lib.platform.contract.rendering import ColumnDef
from mav_gss_lib.platform.contract.telemetry import TelemetryOps
from mav_gss_lib.platform.spec import (
    Mission,
    ParseWarning,
    build_declarative_command_ops,
    build_declarative_telemetry_ops,
    parse_yaml,
)

from mav_gss_lib.missions.maveric.codec import MaverPacketCodec
from mav_gss_lib.missions.maveric.framing import MavericFramer
from mav_gss_lib.missions.maveric.plugins import PLUGINS


_HEADER_FIELDS = ("dest", "echo", "ptype", "src")


# Column definitions for the TX queue/history list. The `verifiers` column
# is rendered client-side from the verification WS stream — its row value
# stays empty, so it's declared without `hide_if_all` so the tick strip is
# visible on every row whether or not a registered instance currently maps.
_TX_QUEUE_COLUMNS: tuple[dict, ...] = (
    {"id": "dest",      "label": "dest",      "width": "w-[52px]"},
    {"id": "echo",      "label": "echo",      "width": "w-[52px]", "hide_if_all": ["NONE"]},
    {"id": "ptype",     "label": "type",      "width": "w-[52px]", "badge": True},
    {"id": "cmd",       "label": "id / args", "flex": True},
    {"id": "verifiers", "label": "verify",    "width": "w-[78px]", "align": "right"},
)


@dataclass(frozen=True, slots=True)
class DeclarativeCapabilities:
    mission: Mission
    packet_codec: MaverPacketCodec
    telemetry_ops: TelemetryOps
    command_ops: CommandOps
    parse_warnings: tuple[ParseWarning, ...]


class _LiveFramer:
    """Framer wrapper that rebuilds the MavericFramer per-send so live
    operator-config edits to ax25.* / csp.* / tx.uplink_mode propagate
    without a MissionSpec rebuild."""

    def __init__(self, platform_cfg: Mapping[str, Any], mission_cfg: Mapping[str, Any]) -> None:
        self._platform_cfg = platform_cfg
        self._mission_cfg = mission_cfg

    def frame(self, encoded: EncodedCommand) -> FramedCommand:
        uplink_mode = (self._platform_cfg.get("tx") or {}).get("uplink_mode", "ASM+Golay")
        framer = MavericFramer.from_mission_config(
            dict(self._mission_cfg),
            uplink_mode=uplink_mode,
        )
        return framer.frame(encoded)


class _MaverCommandOpsWrapper:
    """Translates legacy flat MAVERIC payloads into the canonical
    declarative ``{cmd_id, args:dict, packet:dict}`` shape on
    parse_input, then delegates everything else (validate, encode,
    frame, render, verifier_set, correlation_key, schema, tx_columns,
    …) to the inner declarative ops via ``__getattr__``."""

    __slots__ = ("inner", "mission")

    def __init__(self, *, inner: CommandOps, mission: Mission) -> None:
        self.inner = inner
        self.mission = mission

    def parse_input(self, value: str | dict[str, Any]) -> CommandDraft:
        if isinstance(value, dict):
            cmd_id = str(value.get("cmd_id", "")).lower()
            meta = self.mission.meta_commands.get(cmd_id)
            if meta is not None and meta.rx_only:
                raise ValueError(f"'{cmd_id}' is receive-only")
            return self.inner.parse_input(self._canonicalize(value))
        return self.inner.parse_input(value)

    def tx_columns(self) -> list[ColumnDef]:
        return [ColumnDef.from_dict(col) for col in _TX_QUEUE_COLUMNS]

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def _canonicalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Convert legacy MAVERIC flat shape into the declarative shape.

        Lifts top-level ``dest`` / ``echo`` / ``ptype`` / ``src`` into
        ``packet``, but only when the meta_command actually allows the
        override (and the operator's value differs from the default).
        Overriding a field with its own meta_command default would raise
        ``HeaderFieldNotOverridable`` unnecessarily."""
        canonical: dict[str, Any] = {"cmd_id": payload.get("cmd_id", "")}
        args = payload.get("args", {})
        canonical["args"] = args if isinstance(args, dict) else {}
        packet = payload.get("packet")
        canonical["packet"] = dict(packet) if isinstance(packet, dict) else {}

        meta = self.mission.meta_commands.get(canonical["cmd_id"])
        if meta is None:
            # Walker will reject the unknown cmd_id with a clear validation
            # error. Lift everything in case downstream cares.
            for field in _HEADER_FIELDS:
                if field in payload and field not in canonical["packet"]:
                    canonical["packet"][field] = payload[field]
            return canonical

        meta_packet = meta.packet
        allowed = meta.allowed_packet
        for field in _HEADER_FIELDS:
            if field not in payload or field in canonical["packet"]:
                continue
            value = payload[field]
            # Skip lifting fields that already match the meta_command's
            # default — overriding with the same value triggers
            # HeaderFieldNotOverridable when the field isn't in
            # allowed_packet. The walker uses meta_packet[field] anyway.
            if field in meta_packet and meta_packet[field] == value:
                continue
            # Lift only fields the meta_command exposes as overridable.
            if field in allowed:
                canonical["packet"][field] = value
        return canonical


def build_declarative_capabilities(
    *,
    mission_yml_path: str | Path,
    platform_cfg: Mapping[str, Any],
    mission_cfg: Mapping[str, Any],
) -> DeclarativeCapabilities:
    mission = parse_yaml(Path(mission_yml_path), plugins=PLUGINS)
    codec = MaverPacketCodec(extensions=mission.extensions)
    framer = _LiveFramer(platform_cfg=platform_cfg, mission_cfg=mission_cfg)
    telemetry_ops = build_declarative_telemetry_ops(
        mission, PLUGINS, packet_attr="walker_packet",
    )
    declarative_ops = build_declarative_command_ops(
        mission, PLUGINS, packet_codec=codec, framer=framer,
    )
    command_ops = _MaverCommandOpsWrapper(inner=declarative_ops, mission=mission)
    return DeclarativeCapabilities(
        mission=mission,
        packet_codec=codec,
        telemetry_ops=telemetry_ops,
        command_ops=command_ops,
        parse_warnings=tuple(mission.parse_warnings),
    )
