"""ParameterType dataclasses — XTCE-inspired typed value descriptors.

One dataclass per `kind` (int / float / string / binary / enum /
absolute_time / aggregate / array). `BUILT_IN_PARAMETER_TYPES` is a
flat dict keyed by name (`u8` / `i16_be` / `f32_le` / `bool` /
`ascii_token` / `ascii_blob`) of pre-built primitives that authors
reference but do not redeclare.

Parser-time graph rules (DFS, no cycles; aggregate-of-aggregate OK,
array-of-aggregate not in v1) live in `yaml_parse.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .calibrators import Calibrator
from .types import ByteOrder

ParameterTypeKind = Literal[
    "int", "float", "string", "binary", "enum",
    "absolute_time", "aggregate", "array",
]


@dataclass(frozen=True, slots=True)
class IntegerParameterType:
    name: str
    size_bits: Literal[8, 16, 32, 64]
    signed: bool = False
    byte_order: ByteOrder = "little"
    calibrator: Calibrator = None
    unit: str = ""
    valid_range: tuple[float, float] | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class FloatParameterType:
    name: str
    size_bits: Literal[32, 64] = 32
    byte_order: ByteOrder = "little"
    calibrator: Calibrator = None
    unit: str = ""
    valid_range: tuple[float, float] | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class StringParameterType:
    name: str
    encoding: Literal["fixed", "null_terminated", "to_end", "ascii_token"]
    fixed_size_bytes: int | None = None
    charset: str = "UTF-8"
    description: str = ""


@dataclass(frozen=True, slots=True)
class BinaryParameterType:
    name: str
    size_kind: Literal["fixed", "dynamic_ref"]
    fixed_size_bytes: int | None = None
    size_ref: str | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class EnumValue:
    raw: int
    label: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class EnumeratedParameterType:
    name: str
    size_bits: Literal[8, 16, 32, 64] = 8
    signed: bool = False
    byte_order: ByteOrder = "little"
    values: tuple[EnumValue, ...] = ()
    description: str = ""


@dataclass(frozen=True, slots=True)
class AbsoluteTimeParameterType:
    name: str
    encoding: Literal["millis_u64"]
    epoch: Literal["unix"] = "unix"
    byte_order: ByteOrder = "little"
    description: str = ""


@dataclass(frozen=True, slots=True)
class AggregateMember:
    name: str
    type_ref: str


@dataclass(frozen=True, slots=True)
class AggregateParameterType:
    name: str
    member_list: tuple[AggregateMember, ...]
    unit: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class ArrayParameterType:
    name: str
    array_type_ref: str
    dimension_list: tuple[int, ...]
    unit: str = ""
    description: str = ""


ParameterType = (
    IntegerParameterType
    | FloatParameterType
    | StringParameterType
    | BinaryParameterType
    | EnumeratedParameterType
    | AbsoluteTimeParameterType
    | AggregateParameterType
    | ArrayParameterType
)


def _int(name: str, size: int, signed: bool, byte_order: ByteOrder) -> IntegerParameterType:
    return IntegerParameterType(name=name, size_bits=size, signed=signed, byte_order=byte_order)


def _float(name: str, size: int, byte_order: ByteOrder) -> FloatParameterType:
    return FloatParameterType(name=name, size_bits=size, byte_order=byte_order)


_BOOL = EnumeratedParameterType(
    name="bool",
    size_bits=8,
    values=(EnumValue(raw=0, label="false"), EnumValue(raw=1, label="true")),
)

_ASCII_TOKEN = StringParameterType(name="ascii_token", encoding="ascii_token")
_ASCII_BLOB = StringParameterType(name="ascii_blob", encoding="to_end")


BUILT_IN_PARAMETER_TYPES: dict[str, ParameterType] = {
    # unsigned LE
    "u8":  _int("u8",  8,  False, "little"),
    "u16": _int("u16", 16, False, "little"),
    "u32": _int("u32", 32, False, "little"),
    "u64": _int("u64", 64, False, "little"),
    # signed LE
    "i8":  _int("i8",  8,  True,  "little"),
    "i16": _int("i16", 16, True,  "little"),
    "i32": _int("i32", 32, True,  "little"),
    "i64": _int("i64", 64, True,  "little"),
    # BE variants
    "u16_be": _int("u16_be", 16, False, "big"),
    "u32_be": _int("u32_be", 32, False, "big"),
    "u64_be": _int("u64_be", 64, False, "big"),
    "i16_be": _int("i16_be", 16, True,  "big"),
    "i32_be": _int("i32_be", 32, True,  "big"),
    "i64_be": _int("i64_be", 64, True,  "big"),
    # floats
    "f32_le": _float("f32_le", 32, "little"),
    "f64_le": _float("f64_le", 64, "little"),
    "f32_be": _float("f32_be", 32, "big"),
    "f64_be": _float("f64_be", 64, "big"),
    # other primitives
    "bool":        _BOOL,
    "ascii_token": _ASCII_TOKEN,
    "ascii_blob":  _ASCII_BLOB,
}


__all__ = [
    "ParameterType",
    "ParameterTypeKind",
    "IntegerParameterType",
    "FloatParameterType",
    "StringParameterType",
    "BinaryParameterType",
    "EnumValue",
    "EnumeratedParameterType",
    "AbsoluteTimeParameterType",
    "AggregateMember",
    "AggregateParameterType",
    "ArrayParameterType",
    "BUILT_IN_PARAMETER_TYPES",
]
