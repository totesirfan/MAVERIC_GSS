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


def _coerce_token(token: str) -> Any:
    """Best-effort numeric coercion for CLI tokens. Mirrors the inner
    declarative parse_input so positional CLI tokens reach the walker
    typed (int/float) when they look numeric."""
    try:
        return int(token, 0)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    return token


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
    """Operator-surface adapter over the declarative CommandOps.

    Two shape translations:

    * **CLI grammars** (parse_input on a string):
        - shortcut: ``CMD [arg1 arg2 ...]`` — declarative pass-through.
        - full:     ``[SRC] DEST ECHO TYPE CMD [arg1 arg2 ...]`` — legacy
          MAVERIC operator format. SRC/DEST/ECHO accept node names or
          numeric ids; TYPE accepts ptype names or ids. SRC defaults to
          the GS node when 4-token form is detected.

    * **Frontend dict shape** (parse_input on a dict): legacy flat
      ``{cmd_id, args, dest, echo, ptype, src}`` is canonicalized to
      declarative ``{cmd_id, args:dict, packet:dict}``.

    Plus an `rx_only` admission gate, an operator-friendly `schema()`
    reshape (frontend-compatible flat ``{cmd_id: {tx_args, dest, echo,
    ptype, nodes, ...}}``), and a static `tx_columns` providing the
    MAVERIC TX queue/history column list. All other CommandOps methods
    delegate to the inner declarative adapter via ``__getattr__``.
    """

    __slots__ = ("inner", "mission", "_codec")

    def __init__(self, *, inner: CommandOps, mission: Mission, codec: MaverPacketCodec) -> None:
        self.inner = inner
        self.mission = mission
        self._codec = codec

    def parse_input(self, value: str | dict[str, Any]) -> CommandDraft:
        if isinstance(value, dict):
            cmd_id = str(value.get("cmd_id", "")).lower()
            meta = self.mission.meta_commands.get(cmd_id)
            if meta is not None and meta.rx_only:
                raise ValueError(f"'{cmd_id}' is receive-only")
            return self.inner.parse_input(self._canonicalize(value))
        return self._parse_cli(value)

    def schema(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for cmd_id, meta in self.mission.meta_commands.items():
            out[cmd_id] = {
                "tx_args": [
                    {
                        "name": a.name,
                        "type": a.type_ref,
                        "description": a.description,
                        "important": a.important,
                    }
                    for a in meta.argument_list
                ],
                "rx_args": [],
                "dest":  meta.packet.get("dest"),
                "echo":  meta.packet.get("echo"),
                "ptype": meta.packet.get("ptype"),
                "nodes": list(meta.allowed_packet.get("dest", ())),
                "guard": meta.guard,
                "rx_only": meta.rx_only,
                "deprecated": meta.deprecated,
            }
        return out

    def tx_columns(self) -> list[ColumnDef]:
        return [ColumnDef.from_dict(col) for col in _TX_QUEUE_COLUMNS]

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    # -- CLI grammar -----------------------------------------------------

    def _parse_cli(self, line: str) -> CommandDraft:
        parts = line.strip().split()
        if not parts:
            raise ValueError("empty command input")
        first_lower = parts[0].lower()
        if first_lower in self.mission.meta_commands:
            # Shortcut: declarative inner already handles `cmd_id arg1 arg2 ...`.
            meta = self.mission.meta_commands[first_lower]
            if meta.rx_only:
                raise ValueError(f"'{first_lower}' is receive-only")
            return self.inner.parse_input(line)
        return self._parse_full_form(parts)

    def _parse_full_form(self, parts: list[str]) -> CommandDraft:
        if len(parts) < 4:
            raise ValueError(
                "need at least: <dest> <echo> <type> <cmd>  "
                "(or <src> <dest> <echo> <type> <cmd>)"
            )
        # 5+ tokens AND parts[3] resolves as a ptype → form WITH src.
        # Otherwise (4 tokens, OR 5+ where parts[2] is the ptype) → SRC=GS.
        src_name: str | None = None
        if len(parts) >= 5 and self._token_is_ptype(parts[3]):
            src_name = self._resolve_node_name(parts[0], "src")
            dest = self._resolve_node_name(parts[1], "dest")
            echo = self._resolve_node_name(parts[2], "echo")
            ptype = self._resolve_ptype_name(parts[3])
            cmd_idx = 4
        else:
            dest = self._resolve_node_name(parts[0], "dest")
            echo = self._resolve_node_name(parts[1], "echo")
            ptype = self._resolve_ptype_name(parts[2])
            cmd_idx = 3
        if cmd_idx >= len(parts):
            raise ValueError("missing command id after routing tokens")
        cmd_id = parts[cmd_idx].lower()
        meta = self.mission.meta_commands.get(cmd_id)
        if meta is None:
            raise ValueError(f"Unknown command {cmd_id!r} — verify command name in schema")
        if meta.rx_only:
            raise ValueError(f"'{cmd_id}' is receive-only")
        args_dict: dict[str, Any] = {}
        for arg, token in zip(meta.argument_list, parts[cmd_idx + 1:]):
            args_dict[arg.name] = _coerce_token(token)
        payload: dict[str, Any] = {
            "cmd_id": cmd_id, "args": args_dict,
            "dest": dest, "echo": echo, "ptype": ptype,
        }
        if src_name is not None:
            payload["src"] = src_name
        return self.inner.parse_input(self._canonicalize(payload))

    def _resolve_node_name(self, token: str, field: str) -> str:
        s = token.strip()
        if s.lstrip("-").isdigit():
            try:
                return self._codec.node_name_for(int(s))
            except Exception as exc:
                raise ValueError(f"unknown {field} node id {token!r}") from exc
        try:
            self._codec.node_id_for(s)
        except Exception as exc:
            raise ValueError(f"unknown {field} node {token!r}") from exc
        return s

    def _resolve_ptype_name(self, token: str) -> str:
        s = token.strip()
        if s.lstrip("-").isdigit():
            try:
                return self._codec.ptype_name_for(int(s))
            except Exception as exc:
                raise ValueError(f"unknown ptype id {token!r}") from exc
        try:
            self._codec.ptype_id_for(s)
        except Exception as exc:
            raise ValueError(f"unknown ptype {token!r}") from exc
        return s

    def _token_is_ptype(self, token: str) -> bool:
        try:
            self._resolve_ptype_name(token)
            return True
        except ValueError:
            return False

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
    command_ops = _MaverCommandOpsWrapper(
        inner=declarative_ops, mission=mission, codec=codec,
    )
    return DeclarativeCapabilities(
        mission=mission,
        packet_codec=codec,
        telemetry_ops=telemetry_ops,
        command_ops=command_ops,
        parse_warnings=tuple(mission.parse_warnings),
    )
