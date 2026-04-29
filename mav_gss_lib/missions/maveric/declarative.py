"""Build MAVERIC's declarative telemetry + command capabilities.

Reads ``mission.yml`` via ``platform.spec.parse_yaml`` (with CALIBRATORS
bound), constructs a ``MaverPacketCodec`` from the parsed extensions,
and a platform ``DeclarativeFramer`` from ``mission.framing``.

Wraps the declarative command_ops with MAVERIC's operator grammar:
shortcut CLI commands, full routing-form CLI commands, and canonical
declarative dict payloads (``{cmd_id, args:dict, packet:dict}``).

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from mav_gss_lib.platform.contract import CommandOps
from mav_gss_lib.platform.contract.commands import CommandDraft
from mav_gss_lib.platform.framing import DeclarativeFramer
from mav_gss_lib.platform.spec import (
    Mission,
    ParseWarning,
    StringParameterType,
    build_declarative_command_ops,
    parse_yaml,
)

from mav_gss_lib.missions.maveric.codec import MaverPacketCodec
from mav_gss_lib.missions.maveric.calibrators import CALIBRATORS


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


@dataclass(frozen=True, slots=True)
class DeclarativeCapabilities:
    mission: Mission
    plugins: Mapping[str, Any]
    packet_codec: MaverPacketCodec
    command_ops: CommandOps
    parse_warnings: tuple[ParseWarning, ...]


class _MaverCommandOpsWrapper:
    """Operator-surface adapter over the declarative CommandOps.

    Two shape translations:

    * **CLI grammars** (parse_input on a string):
        - shortcut: ``CMD [arg1 arg2 ...]`` — declarative pass-through.
        - full:     ``[SRC] DEST ECHO TYPE CMD [arg1 arg2 ...]`` — routed
          MAVERIC operator form. SRC/DEST/ECHO accept node names or
          numeric ids; TYPE accepts ptype names or ids. SRC defaults to
          the GS node when 4-token form is detected.

    * **Frontend dict shape** (parse_input on a dict): canonical declarative
      ``{cmd_id, args:dict, packet:dict}``; packet header fields must live
      under ``packet``.

    Plus an `rx_only` admission gate and an operator-friendly `schema()`
    shape (``{cmd_id: {tx_args, dest, echo, ptype, nodes, ...}}``). All
    other CommandOps methods delegate to the
    inner declarative adapter via ``__getattr__``. TX columns are read
    from ``mission.yml::ui.tx_columns`` by the platform.
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
            allowed_dest = meta.allowed_packet.get("dest")
            fixed_dest = meta.packet.get("dest")
            if allowed_dest:
                nodes = list(allowed_dest)
            elif fixed_dest:
                nodes = [fixed_dest]
            else:
                nodes = []
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
                "dest":  fixed_dest,
                "echo":  meta.packet.get("echo"),
                "ptype": meta.packet.get("ptype"),
                "nodes": nodes,
                "guard": meta.guard,
                "rx_only": meta.rx_only,
                "deprecated": meta.deprecated,
            }
        return out

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    # -- CLI grammar -----------------------------------------------------

    def _parse_cli(self, line: str) -> CommandDraft:
        parts = line.strip().split()
        if not parts:
            raise ValueError("empty command input")
        first_lower = parts[0].lower()
        if first_lower in self.mission.meta_commands:
            meta = self.mission.meta_commands[first_lower]
            if meta.rx_only:
                raise ValueError(f"'{first_lower}' is receive-only")
            payload: dict[str, Any] = {
                "cmd_id": first_lower,
                "args": self._parse_arg_tokens(meta.argument_list, parts[1:]),
                "packet": {},
            }
            return self.inner.parse_input(self._canonicalize(payload))
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
        args_dict = self._parse_arg_tokens(meta.argument_list, parts[cmd_idx + 1:])
        meta_packet = meta.packet
        allowed = meta.allowed_packet
        parsed_packet = {
            "dest": dest,
            "echo": echo,
            "ptype": ptype,
            **({"src": src_name} if src_name is not None else {}),
        }
        packet = {
            field: value
            for field, value in parsed_packet.items()
            if field in allowed or (field in meta_packet and meta_packet[field] != value)
        }
        payload: dict[str, Any] = {"cmd_id": cmd_id, "args": args_dict, "packet": packet}
        return self.inner.parse_input(self._canonicalize(payload))

    def _parse_arg_tokens(self, argument_list: tuple[Any, ...], tokens: list[str]) -> dict[str, Any]:
        args: dict[str, Any] = {}
        token_idx = 0
        for arg_idx, arg in enumerate(argument_list):
            if token_idx >= len(tokens):
                break
            if arg_idx == len(argument_list) - 1 and self._arg_consumes_to_end(arg.type_ref):
                args[arg.name] = " ".join(tokens[token_idx:])
                break
            args[arg.name] = _coerce_token(tokens[token_idx])
            token_idx += 1
        return args

    def _arg_consumes_to_end(self, type_ref: str) -> bool:
        param_type = self.mission.parameter_types.get(type_ref)
        return isinstance(param_type, StringParameterType) and param_type.encoding == "to_end"

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
        """Validate and normalize MAVERIC's canonical declarative dict shape."""
        leaked = [field for field in _HEADER_FIELDS if field in payload]
        if leaked:
            fields = ", ".join(leaked)
            raise ValueError(f"header field(s) must be under 'packet': {fields}")
        canonical: dict[str, Any] = {"cmd_id": payload.get("cmd_id", "")}
        args = payload.get("args", {})
        if not isinstance(args, dict):
            raise ValueError("'args' must be an object")
        canonical["args"] = args
        packet = payload.get("packet")
        canonical["packet"] = dict(packet) if isinstance(packet, dict) else {}
        return canonical


def build_declarative_capabilities(
    *,
    mission_yml_path: str | Path,
    mission_cfg: Mapping[str, Any],
) -> DeclarativeCapabilities:
    """Construct MAVERIC's declarative capabilities from mission.yml.

    `mission_cfg` is captured by reference; the DeclarativeFramer reads
    its current state per send so /api/config edits to bound sections
    (csp.*) propagate without a MissionSpec rebuild.
    """
    mission = parse_yaml(Path(mission_yml_path), plugins=CALIBRATORS)
    if mission.framing is None:
        raise ValueError(
            f"mission.yml at {mission_yml_path} is missing the 'framing:' "
            "block — required for the declarative pipeline. See "
            "mav_gss_lib/missions/maveric/mission.example.yml for the schema."
        )
    codec = MaverPacketCodec(extensions=mission.extensions)
    framer = DeclarativeFramer(mission.framing, mission_cfg)
    declarative_ops = build_declarative_command_ops(
        mission, CALIBRATORS, packet_codec=codec, framer=framer,
    )
    command_ops = _MaverCommandOpsWrapper(
        inner=declarative_ops, mission=mission, codec=codec,
    )
    return DeclarativeCapabilities(
        mission=mission,
        plugins=CALIBRATORS,
        packet_codec=codec,
        command_ops=command_ops,
        parse_warnings=tuple(mission.parse_warnings),
    )
