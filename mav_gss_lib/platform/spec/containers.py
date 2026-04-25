"""Container dataclasses — XTCE SequenceContainer + entry types.

Two container shapes:
  - Standalone — matched by `restriction_criteria.packet:` predicates;
    walks its full payload itself.
  - Parent + concrete (BaseContainer pattern) — abstract parent decodes
    a header section; concrete children extend via `base_container_ref`
    and predicate against parent-decoded fields via
    `restriction_criteria.parent_args:`.

Three entry kinds: ParameterRefEntry (named field), RepeatEntry
(count-driven repetition), PagedFrameEntry (marker-stream dispatch).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True, slots=True)
class Comparison:
    parameter_ref: str
    value: str | int | bool | float
    operator: Literal["==", "!=", "<", "<=", ">", ">="] = "=="


@dataclass(frozen=True, slots=True)
class RestrictionCriteria:
    packet: tuple[Comparison, ...] = ()
    parent_args: tuple[Comparison, ...] = ()


@dataclass(frozen=True, slots=True)
class ParameterRefEntry:
    name: str
    type_ref: str
    parameter_ref: str | None = None
    emit: bool = True


@dataclass(frozen=True, slots=True)
class RepeatEntry:
    entry: ParameterRefEntry
    count_kind: Literal["fixed", "dynamic_ref", "to_end"]
    count_fixed: int | None = None
    count_ref: str | None = None


@dataclass(frozen=True, slots=True)
class PagedFrameEntry:
    base_container_ref: str
    marker_separator: str = ","
    dispatch_keys: tuple[str, ...] = ("module", "register")
    on_unknown_register: Literal["skip", "raise", "emit_unknown"] = "skip"


Entry = ParameterRefEntry | RepeatEntry | PagedFrameEntry


@dataclass(frozen=True, slots=True)
class SequenceContainer:
    name: str
    entry_list: tuple[Entry, ...]
    restriction_criteria: RestrictionCriteria | None = None
    abstract: bool = False
    base_container_ref: str | None = None
    domain: str = ""
    layout: Literal["binary", "ascii_tokens"] = "ascii_tokens"
    on_short_payload: Literal["skip", "raise", "emit_partial"] = "skip"
    on_decode_error: Literal["skip", "raise", "emit_partial"] = "raise"
    description: str = ""


__all__ = [
    "Comparison",
    "RestrictionCriteria",
    "ParameterRefEntry",
    "RepeatEntry",
    "PagedFrameEntry",
    "Entry",
    "SequenceContainer",
]
