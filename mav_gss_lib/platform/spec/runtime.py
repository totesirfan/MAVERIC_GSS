"""Declarative walker runtime.

Public surface: DeclarativeWalker. Internal classes — TypeCodec,
ContainerMatcher, EntryDecoder, CommandEncoder — each split by
responsibility but tested through the public façade.

This module is mission-agnostic above the WalkerPacket boundary and
contains zero MAVERIC identifiers (enforced by
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
                return cursor.read_bytes(t.fixed_size_bytes).decode(t.charset, errors="replace")
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
            return str(value).encode(t.charset)
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

    def match_parent(self, pkt: WalkerPacket) -> SequenceContainer | None:
        for c in self._top_level:
            rc = c.restriction_criteria
            if rc is None or not rc.packet:
                continue
            if all(_check(p, pkt.header) for p in rc.packet):
                return c
        return None

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

from mav_gss_lib.platform.telemetry import TelemetryFragment

from .bitfield import BitfieldType
from .calibrator_runtime import CalibratorRuntime
from .containers import ParameterRefEntry, PagedFrameEntry, RepeatEntry


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


class EntryDecoder:
    """Walks a container's entry_list, emitting TelemetryFragment per
    ParameterRefEntry (when emit=True), per RepeatEntry iteration, or per
    PagedFrameEntry marker block. Populates `decoded_into` with raw
    decoded values for downstream dispatch (`parent_args`, dynamic_ref).
    """

    __slots__ = ("_types", "_codec", "_calibrators", "_bitfields")

    def __init__(
        self,
        *,
        types: Mapping[str, ParameterType],
        codec: TypeCodec,
        calibrators: CalibratorRuntime,
        bitfields: Mapping[str, BitfieldType],
    ) -> None:
        self._types = types
        self._codec = codec
        self._calibrators = calibrators
        self._bitfields = bitfields

    def walk(
        self,
        container: SequenceContainer,
        cursor: BitCursor | TokenCursor,
        *,
        now_ms: int,
        decoded_into: dict[str, Any],
        matcher: ContainerMatcher | None = None,
    ) -> Iterator[TelemetryFragment]:
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
    ) -> Iterator[TelemetryFragment]:
        if entry.type_ref in self._bitfields:
            assert isinstance(cursor, BitCursor), "bitfield decode requires binary layout"
            bf = self._bitfields[entry.type_ref]
            value: Any = BitfieldDecoder(types=self._types).decode(bf, cursor)
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
                    value, unit = bytes(blob[:n]), ""
                else:
                    raw = self._codec.decode_ascii(entry.type_ref, cursor)
                    value, unit = self._calibrators.apply(entry.type_ref, raw)
            decoded_into[entry.name] = raw if entry.type_ref not in self._bitfields else value
        if entry.emit:
            yield TelemetryFragment(
                domain=container.domain,
                key=entry.name,
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
    ) -> Iterator[TelemetryFragment]:
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
                yield TelemetryFragment(
                    domain=container.domain,
                    key=entry.entry.name,
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
    ) -> Iterator[TelemetryFragment]:
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
                    yield TelemetryFragment(
                        domain=container.domain,
                        key=f"UNKNOWN_REG_{'_'.join(str(v) for v in synthesized.values())}",
                        value=None,
                        ts_ms=now_ms,
                        unit="",
                    )
                continue
            yield from self.walk(child, cursor, now_ms=now_ms, decoded_into={}, matcher=matcher)
