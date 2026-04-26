"""MAVERIC PacketCodec implementation.

Implements the ``mav_gss_lib.platform.spec.PacketCodec`` Protocol for
MAVERIC's inner command wire format:

    [src][dest][echo][ptype][id_len][args_len]
    [id\\x00][args\\x00][CRC-16 LE]

Outer CSP / AX.25 / ASM+Golay framing remains the responsibility of
``mav_gss_lib.missions.maveric.framing.MavericFramer``.
The codec is wired into the declarative command-ops adapter alongside
the framer; the adapter calls ``complete_header`` -> ``wrap`` to encode
and ``unwrap`` to decode inbound CSP payloads.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from mav_gss_lib.platform.framing.crc import crc16
from mav_gss_lib.platform.spec import CommandHeader, WalkerPacket

from .errors import (
    DuplicateNodeId,
    DuplicatePtypeId,
    NodeIdOutOfRange,
    PtypeIdOutOfRange,
    UnknownNodeId,
    UnknownPtypeId,
)


_INNER_HDR_LEN = 6


@dataclass(frozen=True, slots=True)
class _MaverWalkerPacket:
    """Concrete WalkerPacket implementation returned by ``unwrap``."""

    args_raw: bytes
    header: Mapping[str, Any]


class MaverPacketCodec:
    """MAVERIC inner-command codec (wire format above)."""

    REQUIRED_HEADER_FIELDS: tuple[str, ...] = ("src", "dest", "echo", "ptype")

    def __init__(self, *, extensions: Mapping[str, Any]) -> None:
        nodes_raw = dict(extensions.get("nodes") or {})
        ptypes_raw = dict(extensions.get("ptypes") or {})
        gs_node_name = extensions.get("gs_node")

        self._nodes_by_name: dict[str, int] = {}
        self._nodes_by_id: dict[int, str] = {}
        for name, value in nodes_raw.items():
            if not (0 <= int(value) <= 0xFF):
                raise NodeIdOutOfRange(name=name, value=int(value))
            if value in self._nodes_by_id:
                raise DuplicateNodeId(
                    name_a=self._nodes_by_id[int(value)],
                    name_b=name,
                    value=int(value),
                )
            self._nodes_by_name[name] = int(value)
            self._nodes_by_id[int(value)] = name

        self._ptypes_by_name: dict[str, int] = {}
        self._ptypes_by_id: dict[int, str] = {}
        for name, value in ptypes_raw.items():
            if not (0 <= int(value) <= 0xFF):
                raise PtypeIdOutOfRange(name=name, value=int(value))
            if value in self._ptypes_by_id:
                raise DuplicatePtypeId(
                    name_a=self._ptypes_by_id[int(value)],
                    name_b=name,
                    value=int(value),
                )
            self._ptypes_by_name[name] = int(value)
            self._ptypes_by_id[int(value)] = name

        if gs_node_name is None:
            self.gs_node_id: int | None = None
        else:
            if gs_node_name not in self._nodes_by_name:
                raise UnknownNodeId(field="gs_node", value=gs_node_name)
            self.gs_node_id = self._nodes_by_name[str(gs_node_name)]

        self._gs_node_name = gs_node_name

    @property
    def gs_node_name(self) -> str | None:
        return self._gs_node_name

    def node_id_for(self, name: str) -> int:
        if name not in self._nodes_by_name:
            raise UnknownNodeId(field="node", value=name)
        return self._nodes_by_name[name]

    def node_name_for(self, value: int) -> str:
        if value not in self._nodes_by_id:
            raise UnknownNodeId(field="node", value=value)
        return self._nodes_by_id[int(value)]

    def ptype_id_for(self, name: str) -> int:
        if name not in self._ptypes_by_name:
            raise UnknownPtypeId(value=name)
        return self._ptypes_by_name[name]

    def ptype_name_for(self, value: int) -> str:
        if value not in self._ptypes_by_id:
            raise UnknownPtypeId(value=value)
        return self._ptypes_by_id[int(value)]

    def complete_header(self, cmd_header: "CommandHeader") -> "CommandHeader":
        from mav_gss_lib.platform.spec.errors import MissingRequiredHeaderField

        fields = dict(cmd_header.fields)
        if "src" not in fields and self._gs_node_name is not None:
            fields["src"] = self._gs_node_name
        for name in self.REQUIRED_HEADER_FIELDS:
            if name not in fields:
                raise MissingRequiredHeaderField(cmd_id=cmd_header.id, field=name)
        return CommandHeader(id=cmd_header.id, fields=fields)

    def wrap(self, cmd_header: "CommandHeader", args_bytes: bytes) -> bytes:
        from mav_gss_lib.platform.spec.errors import (
            ArgsTooLong,
            CmdIdTooLong,
            MissingRequiredHeaderField,
        )

        fields = cmd_header.fields
        for name in self.REQUIRED_HEADER_FIELDS:
            if name not in fields:
                raise MissingRequiredHeaderField(
                    cmd_id=cmd_header.id, field=name
                )

        src = self._resolve_node(fields["src"], "src")
        dest = self._resolve_node(fields["dest"], "dest")
        echo = self._resolve_node(fields["echo"], "echo")
        ptype = self._resolve_ptype(fields["ptype"])

        cmd_id = cmd_header.id
        if len(cmd_id) > 0xFF:
            raise CmdIdTooLong(cmd_id=cmd_id, length=len(cmd_id))
        if len(args_bytes) > 0xFF:
            raise ArgsTooLong(cmd_id=cmd_id, length=len(args_bytes))

        header = bytes([src, dest, echo, ptype, len(cmd_id), len(args_bytes)])
        body = bytearray(header)
        body.extend(cmd_id.encode("ascii"))
        body.append(0x00)
        body.extend(args_bytes)
        body.append(0x00)
        crc = crc16(body)
        body.extend(crc.to_bytes(2, byteorder="little"))
        return bytes(body)

    def unwrap(self, raw: bytes) -> WalkerPacket:
        from mav_gss_lib.platform.spec.errors import CrcMismatch

        if len(raw) < _INNER_HDR_LEN:
            raise CrcMismatch(expected=0, actual=0)

        src_b, dest_b, echo_b, ptype_b = raw[0], raw[1], raw[2], raw[3]
        id_len, args_len = raw[4], raw[5]
        body_end = _INNER_HDR_LEN + id_len + 1 + args_len + 1
        if body_end + 2 > len(raw):
            raise CrcMismatch(expected=0, actual=0)

        cmd_id = raw[_INNER_HDR_LEN:_INNER_HDR_LEN + id_len].decode(
            "ascii", errors="replace"
        ).lower()
        args_start = _INNER_HDR_LEN + id_len + 1
        args_raw = bytes(raw[args_start:args_start + args_len])

        rx_crc = raw[body_end] | (raw[body_end + 1] << 8)
        comp = crc16(raw[:body_end])
        if rx_crc != comp:
            raise CrcMismatch(expected=comp, actual=rx_crc)

        tail = raw[body_end + 2:]
        csp_crc32: int | None = None
        if len(tail) == 4:
            csp_crc32 = int.from_bytes(tail, "big")

        header: dict[str, Any] = {
            "cmd_id": cmd_id,
            "src": self._lookup_node_or_pass(src_b),
            "dest": self._lookup_node_or_pass(dest_b),
            "echo": self._lookup_node_or_pass(echo_b),
            "ptype": self._lookup_ptype_or_pass(ptype_b),
        }
        if csp_crc32 is not None:
            header["csp_crc32"] = csp_crc32

        return _MaverWalkerPacket(args_raw=args_raw, header=header)

    def _resolve_node(self, value: Any, field: str) -> int:
        if isinstance(value, str):
            if value not in self._nodes_by_name:
                raise UnknownNodeId(field=field, value=value)
            return self._nodes_by_name[value]
        ival = int(value)
        if not (0 <= ival <= 0xFF):
            raise UnknownNodeId(field=field, value=value)
        return ival

    def _resolve_ptype(self, value: Any) -> int:
        if isinstance(value, str):
            if value not in self._ptypes_by_name:
                raise UnknownPtypeId(value=value)
            return self._ptypes_by_name[value]
        ival = int(value)
        if not (0 <= ival <= 0xFF):
            raise UnknownPtypeId(value=value)
        return ival

    def _lookup_node_or_pass(self, value: int) -> str | int:
        return self._nodes_by_id.get(int(value), int(value))

    def _lookup_ptype_or_pass(self, value: int) -> str | int:
        return self._ptypes_by_id.get(int(value), int(value))
