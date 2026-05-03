"""ArgumentType — TC-side type system, parallel to ParameterType.

XTCE 1.3 distinguishes ArgumentType (command-side) from ParameterType
(telemetry-side). They share encoding semantics but diverge on what
metadata they carry: TM types have calibrators and engineering units,
TC types have valid_range / valid_values for input validation.

We model the same split. ArgumentType variants are NOT subclasses of
ParameterType variants — they are formally distinct types living in a
separate registry (`Mission.argument_types`). The codecs are split too:
`TypeCodec` stays TM-only (encode + decode over ParameterType);
`AsciiArgumentEncoder` is its TC-side encode-only peer. Validation
reads from `argument_types` only.

Built-in primitives (u8/u16/i8/.../ascii_token) exist in BOTH
BUILT_IN_PARAMETER_TYPES and BUILT_IN_ARGUMENT_TYPES — small, deliberate
duplication so each registry is self-contained.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ByteOrder = Literal["little", "big"]


@dataclass(frozen=True, slots=True)
class IntegerArgumentType:
    name: str
    size_bits: Literal[8, 16, 32, 64]
    signed: bool = False
    byte_order: ByteOrder = "little"
    description: str = ""
    valid_range: tuple[int, int] | None = None
    valid_values: tuple[int, ...] | None = None


@dataclass(frozen=True, slots=True)
class FloatArgumentType:
    name: str
    size_bits: Literal[32, 64] = 32
    byte_order: ByteOrder = "little"
    description: str = ""
    valid_range: tuple[float, float] | None = None
    valid_values: tuple[float, ...] | None = None


@dataclass(frozen=True, slots=True)
class StringArgumentType:
    """Wire encoding for a string-typed command argument.

    Only two encodings exist by design — they're the only ones
    `AsciiArgumentEncoder.encode_ascii()` actually honors. `ascii_token`
    is a whitespace-delimited single token; `to_end` consumes the entire
    remainder of the operator-typed line and MUST be the last argument
    of its command (enforced at YAML-parse time by Task 2 Step 5a).

    Earlier drafts of this design exposed `null_terminated` and `fixed`
    as encoding values, but the encoder had no branch for them — both
    would have silently degraded to `str(value)`, making the
    distinction metadata-only and misleading. If the FSW ever needs a
    binary or fixed-width string arg, add the encoding here AND a
    matching branch in `AsciiArgumentEncoder.encode_ascii()` in the
    same change.
    """

    name: str
    encoding: Literal["ascii_token", "to_end"] = "ascii_token"
    description: str = ""


ArgumentType = (
    IntegerArgumentType
    | FloatArgumentType
    | StringArgumentType
)


# Note: BinaryArgumentType is intentionally NOT defined.
# AsciiArgumentEncoder.encode_ascii has no branch for binary command args;
# advertising a type that parses but can't encode would be a foot-gun. If a
# future command needs binary args (e.g., flash_write's [BYTES] payload),
# add BinaryArgumentType AND a binary encoding path in the same change
# (likely as a new sibling encoder, not by polluting AsciiArgumentEncoder).


def _int(name: str, size: int, signed: bool, byte_order: ByteOrder) -> IntegerArgumentType:
    return IntegerArgumentType(name=name, size_bits=size, signed=signed, byte_order=byte_order)


def _float(name: str, size: int, byte_order: ByteOrder) -> FloatArgumentType:
    return FloatArgumentType(name=name, size_bits=size, byte_order=byte_order)


BUILT_IN_ARGUMENT_TYPES: dict[str, ArgumentType] = {
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
    # floats
    "f32_le": _float("f32_le", 32, "little"),
    "f64_le": _float("f64_le", 64, "little"),
    # strings — both ascii_token (whitespace-delimited) and ascii_blob
    # (rest-of-cursor) are mirrors of the corresponding parameter-side
    # built-ins so command args declared as ascii_blob continue to work.
    "ascii_token": StringArgumentType(name="ascii_token", encoding="ascii_token"),
    "ascii_blob":  StringArgumentType(name="ascii_blob", encoding="to_end"),
}


from collections.abc import Mapping


def is_to_end_argument(
    argument_types: Mapping[str, ArgumentType], type_ref: str,
) -> bool:
    """True iff `type_ref` resolves to a `StringArgumentType` with
    `encoding="to_end"` in the given argument-type registry.

    Public helper so every parser layer (platform `parse_input`,
    MAVERIC's routing-prefix wrapper, future mission wrappers, the
    UI-side TxBuilder if it ever needs to gate a multi-line input) can
    consult one source of truth. Don't duplicate the isinstance check
    elsewhere — call this and let the type registry decide.

    Takes the registry directly, NOT a `Mission`, so the type module
    stays at the bottom of the dependency stack (no upward import on
    the mission aggregate). Callers pass `self._mission.argument_types`
    or `self.mission.argument_types` at the call site.
    """
    t = argument_types.get(type_ref)
    return isinstance(t, StringArgumentType) and t.encoding == "to_end"


__all__ = [
    "ArgumentType",
    "IntegerArgumentType",
    "FloatArgumentType",
    "StringArgumentType",
    "BUILT_IN_ARGUMENT_TYPES",
    "is_to_end_argument",
]
