"""BitfieldType — first-class bit-slice descriptor.

Walker emits ONE ParamUpdate per bitfield register, with `value` shaped
as `dict[slice_name, decoded_value]` plus auto-synthesized `<slice>_name`
entries for enum slices (§4.4 of the spec).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .types import ByteOrder

BitfieldKind = Literal["bool", "uint", "int", "enum"]


@dataclass(frozen=True, slots=True)
class BitfieldEntry:
    name: str
    bits: tuple[int, int]                 # (lo, hi) inclusive
    kind: BitfieldKind = "bool"
    enum_ref: str | None = None
    unit: str = ""


@dataclass(frozen=True, slots=True)
class BitfieldType:
    name: str
    size_bits: Literal[8, 16, 32, 64]
    byte_order: ByteOrder = "little"
    entry_list: tuple[BitfieldEntry, ...] = ()


__all__ = ["BitfieldEntry", "BitfieldKind", "BitfieldType"]
