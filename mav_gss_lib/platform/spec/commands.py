"""MetaCommand + Argument dataclasses.

`packet` and `allowed_packet` model the wire-envelope header in a
codec-agnostic way. The §3.6 encode pipeline composes
`meta_cmd.packet` defaults with operator overrides, allowlist-checks
against `meta_cmd.allowed_packet`, then the codec's
`complete_header` injects codec-side defaults (e.g. MAVERIC's `src`
from `gs_node`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .types import HeaderValue


@dataclass(frozen=True, slots=True)
class Argument:
    name: str
    type_ref: str
    description: str = ""
    valid_range: tuple[int | float, int | float] | None = None
    valid_values: tuple[Any, ...] | None = None
    invalid_values: tuple[Any, ...] | None = None
    important: bool = False


@dataclass(frozen=True, slots=True)
class MetaCommand:
    id: str
    packet: Mapping[str, HeaderValue] = field(default_factory=dict)
    allowed_packet: Mapping[str, tuple[HeaderValue, ...]] = field(default_factory=dict)
    guard: bool = False
    no_response: bool = False
    rx_only: bool = False
    deprecated: bool = False
    argument_list: tuple[Argument, ...] = ()
    rx_args: tuple[Argument, ...] = ()
    rx_count_from: str | None = None
    rx_index_field: str | None = None
    description: str = ""


__all__ = ["Argument", "MetaCommand"]
