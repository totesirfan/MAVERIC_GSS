"""Declarative walker runtime.

Public surface: DeclarativeWalker. Internal classes — TypeCodec,
ContainerMatcher, EntryDecoder, CommandEncoder — each split by
responsibility but tested through the public façade.

This module is mission-agnostic above the WalkerPacket boundary and
contains zero mission package identifiers (enforced by
`tests/test_walker_no_mission_specifics.py`).
"""

from __future__ import annotations

import struct
from typing import Any, Mapping

from .cursor import BitCursor, TokenCursor
from .parameter_types import (
    AbsoluteTimeParameterType,
    AggregateParameterType,
    ArrayParameterType,
    BinaryParameterType,
    EnumeratedParameterType,
    FloatParameterType,
    IntegerParameterType,
    ParameterType,
    StringParameterType,
)


_FLOAT_STRUCT = {
    (32, "little"): "<f",
    (32, "big"): ">f",
    (64, "little"): "<d",
    (64, "big"): ">d",
}


class TypeCodec:
    """Per-kind ASCII / binary encode/decode dispatch table.

    Decoders consume from a cursor and return a Python value (raw — pre
    calibrator). Encoders take a value and return either an ASCII string
    (joined later by the caller) or bytes.
    """

    __slots__ = ("_types",)

    def __init__(self, *, types: Mapping[str, ParameterType]) -> None:
        self._types = types

    # ---- ASCII path ----

    def decode_ascii(self, type_ref: str, cursor: TokenCursor) -> Any:
        t = self._types[type_ref]
        if isinstance(t, IntegerParameterType):
            return int(cursor.read_token(), 10)
        if isinstance(t, FloatParameterType):
            return float(cursor.read_token())
        if isinstance(t, EnumeratedParameterType):
            return int(cursor.read_token(), 10)
        if isinstance(t, StringParameterType):
            if t.encoding == "ascii_token":
                return cursor.read_token()
            if t.encoding == "to_end":
                return cursor.read_remaining_bytes().decode(t.charset, errors="replace")
            if t.encoding == "fixed":
                assert t.fixed_size_bytes is not None, f"fixed string {t.name!r} missing fixed_size_bytes"
                return cursor.read_remaining_bytes()[: t.fixed_size_bytes].decode(t.charset, errors="replace")
            if t.encoding == "null_terminated":
                blob = cursor.read_remaining_bytes()
                idx = blob.find(b"\x00")
                if idx < 0:
                    return blob.decode(t.charset, errors="replace")
                return blob[:idx].decode(t.charset, errors="replace")
        if isinstance(t, BinaryParameterType):
            blob = cursor.read_remaining_bytes()
            return bytes(blob)
        if isinstance(t, ArrayParameterType):
            count = t.dimension_list[0]
            return [self.decode_ascii(t.array_type_ref, cursor) for _ in range(count)]
        if isinstance(t, AggregateParameterType):
            return {m.name: self.decode_ascii(m.type_ref, cursor) for m in t.member_list}
        raise TypeError(
            f"TypeCodec.decode_ascii: type {type_ref!r} of kind {type(t).__name__} "
            "is not valid in ascii_tokens layout"
        )

    def encode_ascii(self, type_ref: str, value: Any) -> str:
        t = self._types[type_ref]
        if isinstance(t, IntegerParameterType):
            return str(int(value))
        if isinstance(t, FloatParameterType):
            return repr(float(value))
        if isinstance(t, EnumeratedParameterType):
            if isinstance(value, str):
                for ev in t.values:
                    if ev.label == value:
                        return str(ev.raw)
                raise ValueError(f"enum label {value!r} not in {type_ref!r}")
            return str(int(value))
        if isinstance(t, StringParameterType):
            return str(value)
        if isinstance(t, ArrayParameterType):
            return " ".join(self.encode_ascii(t.array_type_ref, elem) for elem in value)
        if isinstance(t, AggregateParameterType):
            return " ".join(self.encode_ascii(m.type_ref, value[m.name]) for m in t.member_list)
        raise TypeError(
            f"TypeCodec.encode_ascii: type {type_ref!r} of kind {type(t).__name__} "
            "is not valid in ascii_tokens layout"
        )

    # ---- Binary path ----

    def decode_binary(self, type_ref: str, cursor: BitCursor) -> Any:
        t = self._types[type_ref]
        if isinstance(t, IntegerParameterType):
            buf = cursor.read_bytes(t.size_bits // 8)
            return int.from_bytes(buf, t.byte_order, signed=t.signed)
        if isinstance(t, FloatParameterType):
            buf = cursor.read_bytes(t.size_bits // 8)
            return struct.unpack(_FLOAT_STRUCT[(t.size_bits, t.byte_order)], buf)[0]
        if isinstance(t, EnumeratedParameterType):
            buf = cursor.read_bytes(t.size_bits // 8)
            return int.from_bytes(buf, t.byte_order, signed=t.signed)
        if isinstance(t, StringParameterType):
            if t.encoding == "fixed":
                assert t.fixed_size_bytes is not None
                buf = cursor.read_bytes(t.fixed_size_bytes)
                # Fixed-width ASCII fields are null-padded (C `strncpy` into a
                # fixed buffer): take everything up to the first null byte.
                nul = buf.find(b"\x00")
                if nul >= 0:
                    buf = buf[:nul]
                return buf.decode(t.charset, errors="replace")
            if t.encoding == "null_terminated":
                acc = bytearray()
                while True:
                    one = cursor.read_bytes(1)
                    if one == b"\x00":
                        break
                    acc += one
                return acc.decode(t.charset, errors="replace")
            raise TypeError(
                f"string encoding {t.encoding!r} not valid in binary layout"
            )
        if isinstance(t, BinaryParameterType):
            if t.size_kind == "fixed":
                assert t.fixed_size_bytes is not None
                return bytes(cursor.read_bytes(t.fixed_size_bytes))
            raise TypeError(
                "BinaryParameterType with dynamic_ref must be resolved by EntryDecoder, not TypeCodec"
            )
        if isinstance(t, AbsoluteTimeParameterType):
            from .time_codec import decode_millis_u64
            assert t.encoding == "millis_u64"
            return decode_millis_u64(cursor.read_bytes(8))
        if isinstance(t, ArrayParameterType):
            count = t.dimension_list[0]
            return [self.decode_binary(t.array_type_ref, cursor) for _ in range(count)]
        if isinstance(t, AggregateParameterType):
            return {m.name: self.decode_binary(m.type_ref, cursor) for m in t.member_list}
        raise TypeError(
            f"TypeCodec.decode_binary: type {type_ref!r} of kind "
            f"{type(t).__name__} unsupported"
        )

    def encode_binary(self, type_ref: str, value: Any) -> bytes:
        t = self._types[type_ref]
        if isinstance(t, IntegerParameterType):
            return int(value).to_bytes(t.size_bits // 8, t.byte_order, signed=t.signed)
        if isinstance(t, FloatParameterType):
            return struct.pack(_FLOAT_STRUCT[(t.size_bits, t.byte_order)], float(value))
        if isinstance(t, EnumeratedParameterType):
            return int(value).to_bytes(t.size_bits // 8, t.byte_order, signed=t.signed)
        if isinstance(t, AbsoluteTimeParameterType):
            from .time_codec import encode_millis_u64
            assert t.encoding == "millis_u64"
            return encode_millis_u64(value)
        if isinstance(t, BinaryParameterType):
            return bytes(value)
        if isinstance(t, StringParameterType):
            raw = str(value).encode(t.charset)
            if t.encoding == "fixed":
                assert t.fixed_size_bytes is not None
                return raw[: t.fixed_size_bytes].ljust(t.fixed_size_bytes, b"\x00")
            return raw
        if isinstance(t, ArrayParameterType):
            return b"".join(self.encode_binary(t.array_type_ref, elem) for elem in value)
        if isinstance(t, AggregateParameterType):
            return b"".join(self.encode_binary(m.type_ref, value[m.name]) for m in t.member_list)
        raise TypeError(
            f"TypeCodec.encode_binary: type {type_ref!r} of kind "
            f"{type(t).__name__} unsupported"
        )


from .containers import Comparison, RestrictionCriteria, SequenceContainer
from .walker_packet import WalkerPacket


_OP_TABLE = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">":  lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}


def _check(comparison: Comparison, source: Mapping[str, Any]) -> bool:
    if comparison.parameter_ref not in source:
        return False
    return _OP_TABLE[comparison.operator](
        source[comparison.parameter_ref], comparison.value,
    )


class ContainerMatcher:
    """Resolve top-level containers via packet predicates and concrete
    children via parent-decoded predicates.

    Two iteration buckets pre-built at construction:
      - top_level: containers whose `base_container_ref` is None.
      - children_by_parent: dict[parent_name -> tuple of children].

    Both preserve the YAML insertion order from the input dict, so
    first-match-wins matches the spec's resolution rule.
    """

    __slots__ = ("_top_level", "_children_by_parent")

    def __init__(self, *, containers: Mapping[str, SequenceContainer]) -> None:
        top_level: list[SequenceContainer] = []
        children: dict[str, list[SequenceContainer]] = {}
        for name, c in containers.items():
            if c.base_container_ref is None:
                top_level.append(c)
            else:
                children.setdefault(c.base_container_ref, []).append(c)
        self._top_level = tuple(top_level)
        self._children_by_parent = {k: tuple(v) for k, v in children.items()}

    def match_parents(self, pkt: WalkerPacket) -> tuple[SequenceContainer, ...]:
        """All top-level containers matching this packet, in YAML order.

        Multiple containers may legally share a packet predicate when fanning
        out to different domains; the walker invokes each match independently
        with its own cursor.
        """
        matches: list[SequenceContainer] = []
        for c in self._top_level:
            rc = c.restriction_criteria
            if rc is None or not rc.packet:
                continue
            if all(_check(p, pkt.header) for p in rc.packet):
                matches.append(c)
        return tuple(matches)

    def match_parent(self, pkt: WalkerPacket) -> SequenceContainer | None:
        """First matching top-level container, preserving the historic API."""
        matches = self.match_parents(pkt)
        return matches[0] if matches else None

    def resolve_concrete(
        self, parent_name: str, parent_decoded: Mapping[str, Any],
    ) -> SequenceContainer | None:
        for child in self._children_by_parent.get(parent_name, ()):
            rc = child.restriction_criteria
            if rc is None:
                continue
            if all(_check(c, parent_decoded) for c in rc.parent_args):
                return child
        return None

    def has_concrete_children(self, parent_name: str) -> bool:
        return bool(self._children_by_parent.get(parent_name))


from typing import Iterator

from mav_gss_lib.platform.contract.parameters import ParamUpdate

from .bitfield import BitfieldType
from .calibrator_runtime import CalibratorRuntime
from .containers import ParameterRefEntry, PagedFrameEntry, RepeatEntry
from .parameters import Parameter


class BitfieldDecoder:
    """Decodes one BitfieldType from a BitCursor.

    Reads `size_bits` bits as one unsigned int (LSB-first relative to the
    underlying byte stream), then masks each slice. Emits a dict shaped
    `{slice_name: decoded, slice_name + '_name': label}` (the `_name`
    companion is added only for `kind: enum` slices).
    """

    __slots__ = ("_types",)

    def __init__(self, *, types: Mapping[str, ParameterType]) -> None:
        self._types = types

    def decode(self, bf: BitfieldType, cursor: BitCursor) -> dict[str, Any]:
        register = cursor.read_bits(bf.size_bits)
        out: dict[str, Any] = {}
        for entry in bf.entry_list:
            lo, hi = entry.bits
            width = hi - lo + 1
            mask = (1 << width) - 1
            raw = (register >> lo) & mask
            if entry.kind == "bool":
                out[entry.name] = bool(raw)
            elif entry.kind == "uint":
                out[entry.name] = raw
            elif entry.kind == "int":
                # Sign-extend
                if raw & (1 << (width - 1)):
                    raw -= 1 << width
                out[entry.name] = raw
            elif entry.kind == "enum":
                assert entry.enum_ref is not None
                out[entry.name] = raw
                enum_t = self._types[entry.enum_ref]
                assert isinstance(enum_t, EnumeratedParameterType)
                label = next((v.label for v in enum_t.values if v.raw == raw), None)
                out[f"{entry.name}_name"] = label or f"UNKNOWN_{raw}"
            else:
                raise TypeError(f"Unknown bitfield slice kind {entry.kind!r}")
        return out


def _u8_from_token(token: str, bf_name: str) -> int:
    """Parse one ascii_tokens decimal token as a u8 byte for bitfield packing.

    Out-of-range values are spacecraft-side bugs that should surface loudly,
    not silently truncate to a low byte and corrupt the decoded register.
    """
    value = int(token, 10)
    if not 0 <= value <= 0xFF:
        raise ValueError(
            f"BitfieldType {bf_name!r}: ascii token {token!r} out of u8 range [0, 255]"
        )
    return value


class EntryDecoder:
    """Walks a container's entry_list, emitting ParamUpdate per
    ParameterRefEntry (when emit=True), per RepeatEntry iteration, or per
    PagedFrameEntry marker block. Populates `decoded_into` with raw
    decoded values for downstream dispatch (`parent_args`, dynamic_ref).
    """

    __slots__ = ("_types", "_codec", "_calibrators", "_bitfields", "_parameters")

    def __init__(
        self,
        *,
        types: Mapping[str, ParameterType],
        codec: TypeCodec,
        calibrators: CalibratorRuntime,
        bitfields: Mapping[str, BitfieldType],
        parameters: Mapping[str, "Parameter"] | None = None,
    ) -> None:
        self._types = types
        self._codec = codec
        self._calibrators = calibrators
        self._bitfields = bitfields
        self._parameters = parameters or {}

    def _domain_for(self, container: SequenceContainer, entry_name: str) -> str:
        """XTCE-lite: parameter.domain wins; container.domain is fallback."""
        param = self._parameters.get(entry_name)
        if param is not None and param.domain:
            return param.domain
        return container.domain

    def walk(
        self,
        container: SequenceContainer,
        cursor: BitCursor | TokenCursor,
        *,
        now_ms: int,
        decoded_into: dict[str, Any],
        matcher: ContainerMatcher | None = None,
    ) -> Iterator[ParamUpdate]:
        for entry in container.entry_list:
            if isinstance(entry, ParameterRefEntry):
                yield from self._walk_ref(container, entry, cursor, now_ms, decoded_into)
            elif isinstance(entry, RepeatEntry):
                yield from self._walk_repeat(container, entry, cursor, now_ms, decoded_into)
            elif isinstance(entry, PagedFrameEntry):
                if matcher is None:
                    raise RuntimeError(
                        "EntryDecoder.walk: PagedFrameEntry requires a ContainerMatcher"
                    )
                yield from self._walk_paged(container, entry, cursor, now_ms, decoded_into, matcher)
            else:
                raise TypeError(f"Unknown entry kind: {type(entry).__name__}")

    def _walk_ref(
        self,
        container: SequenceContainer,
        entry: ParameterRefEntry,
        cursor: BitCursor | TokenCursor,
        now_ms: int,
        decoded_into: dict[str, Any],
    ) -> Iterator[ParamUpdate]:
        if entry.type_ref in self._bitfields:
            bf = self._bitfields[entry.type_ref]
            if isinstance(cursor, BitCursor):
                bit_cursor = cursor
            else:
                # ascii_tokens layout: the wire carries the register's bytes
                # as whitespace-delimited u8 decimal tokens in document order.
                # Pack them into a buffer and run the existing bitfield decode
                # — bitfield interpretation is layout-agnostic.
                n = bf.size_bits // 8
                buf = bytes(_u8_from_token(cursor.read_token(), bf.name) for _ in range(n))
                bit_cursor = BitCursor(buf)
            value: Any = BitfieldDecoder(types=self._types).decode(bf, bit_cursor)
            unit = ""
        else:
            t = self._types[entry.type_ref]
            if container.layout == "binary":
                assert isinstance(cursor, BitCursor)
                if isinstance(t, BinaryParameterType) and t.size_kind == "dynamic_ref":
                    assert t.size_ref is not None
                    n = decoded_into[t.size_ref]
                    raw = bytes(cursor.read_bytes(n))
                    value, unit = raw, ""
                else:
                    raw = self._codec.decode_binary(entry.type_ref, cursor)
                    value, unit = self._calibrators.apply(entry.type_ref, raw)
            else:
                assert isinstance(cursor, TokenCursor)
                if isinstance(t, BinaryParameterType) and t.size_kind == "dynamic_ref":
                    assert t.size_ref is not None
                    blob = cursor.read_remaining_bytes()
                    n = decoded_into[t.size_ref]
                    raw = bytes(blob[:n])
                    value, unit = raw, ""
                else:
                    raw = self._codec.decode_ascii(entry.type_ref, cursor)
                    value, unit = self._calibrators.apply(entry.type_ref, raw)
            decoded_into[entry.name] = value if entry.type_ref in self._bitfields else raw
        if entry.emit:
            group = self._domain_for(container, entry.name)
            yield ParamUpdate(
                name=f"{group}.{entry.name}" if group else entry.name,
                value=value,
                ts_ms=now_ms,
                unit=unit,
            )

    def _walk_repeat(
        self,
        container: SequenceContainer,
        entry: RepeatEntry,
        cursor: BitCursor | TokenCursor,
        now_ms: int,
        decoded_into: dict[str, Any],
    ) -> Iterator[ParamUpdate]:
        if entry.count_kind == "fixed":
            assert entry.count_fixed is not None
            count = entry.count_fixed
        elif entry.count_kind == "dynamic_ref":
            assert entry.count_ref is not None
            count = int(decoded_into[entry.count_ref])
        else:  # to_end
            count = -1
        i = 0
        while True:
            if count >= 0 and i >= count:
                break
            remaining = (
                cursor.remaining_tokens() if isinstance(cursor, TokenCursor)
                else cursor.remaining_bytes()
            )
            if remaining <= 0:
                break
            if isinstance(cursor, TokenCursor):
                raw = self._codec.decode_ascii(entry.entry.type_ref, cursor)
            else:
                raw = self._codec.decode_binary(entry.entry.type_ref, cursor)
            value, unit = self._calibrators.apply(entry.entry.type_ref, raw)
            if entry.entry.emit:
                group = self._domain_for(container, entry.entry.name)
                yield ParamUpdate(
                    name=f"{group}.{entry.entry.name}" if group else entry.entry.name,
                    value=value,
                    ts_ms=now_ms,
                    unit=unit,
                )
            i += 1

    def _walk_paged(
        self,
        container: SequenceContainer,
        entry: PagedFrameEntry,
        cursor: BitCursor | TokenCursor,
        now_ms: int,
        decoded_into: dict[str, Any],
        matcher: ContainerMatcher,
    ) -> Iterator[ParamUpdate]:
        # Markers are tokens that contain `marker_separator`. Walk the
        # remaining cursor block-by-block.
        assert isinstance(cursor, TokenCursor), "paged_frame_entry requires ascii_tokens layout"
        while cursor.remaining_tokens() > 0:
            token = cursor.read_token()
            if entry.marker_separator not in token:
                continue
            parts = token.split(entry.marker_separator)
            synthesized: dict[str, Any] = {}
            for k, raw in zip(entry.dispatch_keys, parts):
                # dispatch_keys are usually ints — try parsing
                try:
                    synthesized[k] = int(raw)
                except ValueError:
                    synthesized[k] = raw
            child = matcher.resolve_concrete(entry.base_container_ref, synthesized)
            if child is None:
                if entry.on_unknown_register == "raise":
                    raise ValueError(
                        f"paged_frame_entry on {container.name!r}: no concrete child "
                        f"for {synthesized!r} (parent={entry.base_container_ref!r})"
                    )
                # 'skip' or 'emit_unknown' — both consume nothing further
                if entry.on_unknown_register == "emit_unknown":
                    suffix = "UNKNOWN_REG_" + "_".join(str(v) for v in synthesized.values())
                    name = f"{container.domain}.{suffix}" if container.domain else suffix
                    yield ParamUpdate(
                        name=name,
                        value=None,
                        ts_ms=now_ms,
                    )
                continue
            yield from self.walk(child, cursor, now_ms=now_ms, decoded_into={}, matcher=matcher)


import logging

from .commands import MetaCommand
from .mission import Mission


class CommandEncoder:
    """Walks a MetaCommand's argument_list and produces the args byte run.

    No envelope, no CRC, no length headers. The mission's PacketCodec
    wraps this output with whatever envelope its wire format requires.
    """

    __slots__ = ("_meta", "_codec", "_types")

    def __init__(
        self,
        *,
        meta_commands: Mapping[str, MetaCommand],
        codec: TypeCodec,
        types: Mapping[str, ParameterType],
    ) -> None:
        self._meta = meta_commands
        self._codec = codec
        self._types = types

    def encode_args(self, cmd_id: str, args: Mapping[str, Any]) -> bytes:
        meta = self._meta[cmd_id]
        if not meta.argument_list:
            return b""
        # ASCII tokens by default. Mission codecs are responsible for
        # binary-args commands.
        tokens: list[str] = []
        for arg in meta.argument_list:
            value = args.get(arg.name)
            tokens.append(self._codec.encode_ascii(arg.type_ref, value))
        return " ".join(tokens).encode("ascii")

    def arg_run_size(self, cmd_id: str) -> int | None:
        meta = self._meta[cmd_id]
        if not meta.argument_list:
            return 0
        total = 0
        for arg in meta.argument_list:
            t = self._types[arg.type_ref]
            if isinstance(t, IntegerParameterType) or isinstance(t, FloatParameterType):
                # ASCII width is dynamic
                return None
            if isinstance(t, EnumeratedParameterType):
                return None
            if isinstance(t, StringParameterType):
                if t.encoding == "fixed" and t.fixed_size_bytes is not None:
                    total += t.fixed_size_bytes
                else:
                    return None
            elif isinstance(t, BinaryParameterType):
                if t.size_kind == "fixed" and t.fixed_size_bytes is not None:
                    total += t.fixed_size_bytes
                else:
                    return None
            else:
                return None
        # N-1 single-space separators
        total += max(0, len(meta.argument_list) - 1)
        return total


class DeclarativeWalker:
    """Public façade. Decodes packets via parent + concrete dispatch and
    encodes outbound command args. Stateless except for caches keyed by
    Mission identity. Mission-agnostic above the WalkerPacket layer.
    """

    __slots__ = ("_mission", "_codec", "_calibrators", "_matcher", "_entries", "_cmd_encoder", "log")

    def __init__(self, mission: Mission, plugins: Mapping[str, Any]) -> None:
        self._mission = mission
        self._codec = TypeCodec(types=mission.parameter_types)
        self._calibrators = CalibratorRuntime(types=mission.parameter_types, plugins=plugins)
        self._matcher = ContainerMatcher(containers=mission.sequence_containers)
        self._entries = EntryDecoder(
            types=mission.parameter_types,
            codec=self._codec,
            calibrators=self._calibrators,
            bitfields=mission.bitfield_types,
            parameters=mission.parameters,
        )
        self._cmd_encoder = CommandEncoder(
            meta_commands=mission.meta_commands,
            codec=self._codec,
            types=mission.parameter_types,
        )
        self.log = logging.getLogger("mav_gss_lib.platform.spec.runtime")

    def match_parent(self, pkt: WalkerPacket) -> SequenceContainer | None:
        return self._matcher.match_parent(pkt)

    def extract(self, pkt: WalkerPacket, now_ms: int) -> Iterator[ParamUpdate]:
        parents = self._matcher.match_parents(pkt)
        if not parents:
            return
        for parent in parents:
            cursor = (
                BitCursor(pkt.args_raw) if parent.layout == "binary"
                else TokenCursor(pkt.args_raw)
            )
            parent_decoded: dict[str, Any] = {}
            try:
                yield from self._entries.walk(
                    parent, cursor, now_ms=now_ms,
                    decoded_into=parent_decoded, matcher=self._matcher,
                )
            except IndexError:
                self._handle_short(parent)
                continue
            if not self._matcher.has_concrete_children(parent.name):
                continue
            concrete = self._matcher.resolve_concrete(parent.name, parent_decoded)
            if concrete is None:
                if parent.abstract:
                    self.log.warning(
                        "no concrete child for abstract parent %s; decoded=%r",
                        parent.name, parent_decoded,
                    )
                continue
            try:
                yield from self._entries.walk(
                    concrete, cursor, now_ms=now_ms,
                    decoded_into={}, matcher=self._matcher,
                )
            except IndexError:
                self._handle_short(concrete)

    def encode_args(self, cmd_id: str, args: Mapping[str, Any]) -> bytes:
        return self._cmd_encoder.encode_args(cmd_id, args)

    def arg_run_size(self, cmd_id: str) -> int | None:
        return self._cmd_encoder.arg_run_size(cmd_id)

    def _handle_short(self, container: SequenceContainer) -> None:
        if container.on_short_payload == "raise":
            raise
        # 'skip' or 'emit_partial' — fragments already yielded before underrun
        self.log.warning(
            "container %s: short payload (on_short_payload=%s)",
            container.name, container.on_short_payload,
        )


__all__ = [
    "TypeCodec",
    "ContainerMatcher",
    "BitfieldDecoder",
    "EntryDecoder",
    "CommandEncoder",
    "DeclarativeWalker",
]
