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
