"""Parameter — named measurement / argument bound to a ParameterType.

The XTCE-lite analogue of `<Parameter>` inside `<SpaceSystem>`: a parameter
carries identity, type binding, and (optionally) the subsystem (``domain``)
it belongs to. ``domain`` is the analogue of XTCE's SpaceSystem name — when
set, it overrides the container's domain at update emission and groups the
parameter under the matching group in the parameter cache. When unset, the
container's domain is used as fallback.

Description rides into the parameter spec surfaced at
`GET /api/parameters`. UI rendering choices (icons, sections, format
strings) live in mission Python — never declared here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Parameter:
    name: str
    type_ref: str
    description: str = ""
    domain: str | None = None
    tags: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["Parameter"]
