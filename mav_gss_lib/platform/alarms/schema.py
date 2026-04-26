"""Parse inline ``alarm:`` blocks from mission.yml ``parameters:`` entries.

Author:  Irfan Annuar - USC ISI SERC
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mav_gss_lib.platform.alarms.contract import Severity


_RULE_KEYS = ("static", "norm", "enum", "flags", "python")


@dataclass(frozen=True, slots=True)
class StaticRule:
    bands: dict[Severity, tuple[float | None, float | None]]
    on: str | int | None = None
    persistence: int = 1
    latched: bool = False


@dataclass(frozen=True, slots=True)
class NormRule:
    bands: dict[Severity, tuple[float | None, float | None]]
    on: str | int | None = None
    persistence: int = 1
    latched: bool = False


@dataclass(frozen=True, slots=True)
class EnumRule:
    map: dict[str, Severity | None]
    default: Severity | None
    on: str | int | None = None
    persistence: int = 1
    latched: bool = False


@dataclass(frozen=True, slots=True)
class FlagsRule:
    critical_if_any: tuple[str, ...] = ()
    warning_if_any: tuple[str, ...] = ()
    watch_if_any: tuple[str, ...] = ()
    critical_if_clear: tuple[str, ...] = ()
    warning_if_clear: tuple[str, ...] = ()
    persistence: int = 1
    latched: bool = False
    on: str | int | None = None  # always None for flags rules; kept for uniformity


@dataclass(frozen=True, slots=True)
class PythonRule:
    callable_ref: str
    on: str | int | None = None
    persistence: int = 1
    latched: bool = False


AlarmRule = StaticRule | NormRule | EnumRule | FlagsRule | PythonRule


def parse_alarm_rules(parameter_entry: dict) -> tuple[AlarmRule, ...]:
    block = parameter_entry.get("alarm")
    if not block:
        return ()
    items = block if isinstance(block, list) else [block]
    out: list[AlarmRule] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        present = [k for k in _RULE_KEYS if k in item]
        if len(present) > 1:
            raise ValueError(
                f"alarm rule has multiple kinds {present!r}; "
                "use a list to express multiple rules"
            )
        if not present:
            continue
        on = item.get("on")
        # Selector preserves int vs string typing; normalize to plain int/str
        if on is not None and not isinstance(on, (int, str)):
            on = str(on)
        persistence = int(item.get("persistence", 1))
        latched = bool(item.get("latched", False))
        kind = present[0]
        if kind == "static":
            out.append(StaticRule(bands=_parse_bands(item["static"]),
                                  on=on, persistence=persistence, latched=latched))
        elif kind == "norm":
            out.append(NormRule(bands=_parse_bands(item["norm"]),
                                on=on, persistence=persistence, latched=latched))
        elif kind == "enum":
            mapping, default = _parse_enum(item["enum"])
            out.append(EnumRule(map=mapping, default=default,
                                on=on, persistence=persistence, latched=latched))
        elif kind == "flags":
            f = item["flags"]
            out.append(FlagsRule(
                critical_if_any=tuple(f.get("critical_if_any") or ()),
                warning_if_any=tuple(f.get("warning_if_any") or ()),
                watch_if_any=tuple(f.get("watch_if_any") or ()),
                critical_if_clear=tuple(f.get("critical_if_clear") or ()),
                warning_if_clear=tuple(f.get("warning_if_clear") or ()),
                persistence=persistence, latched=latched,
            ))
        elif kind == "python":
            out.append(PythonRule(callable_ref=str(item["python"]),
                                  on=on, persistence=persistence,
                                  latched=latched))
    return tuple(out)


def _parse_bands(block: dict) -> dict[Severity, tuple[float | None, float | None]]:
    bands: dict[Severity, tuple[float | None, float | None]] = {}
    for sev_name, body in block.items():
        sev = Severity.from_name(sev_name)
        if not isinstance(body, dict):
            raise ValueError(f"alarm band {sev_name!r} must be a mapping")
        lo = body.get("min")
        hi = body.get("max")
        if lo is None and hi is None:
            raise ValueError(f"alarm band {sev_name!r} requires at least min or max")
        bands[sev] = (
            float(lo) if lo is not None else None,
            float(hi) if hi is not None else None,
        )
    return bands


def _parse_enum(block: dict) -> tuple[dict[str, Severity | None], Severity | None]:
    mapping: dict[str, Severity | None] = {}
    default: Severity | None = None
    for k, v in block.items():
        sev = None if v is None else Severity.from_name(str(v))
        if k == "default":
            default = sev
        else:
            mapping[str(k)] = sev
    return mapping, default


__all__ = [
    "AlarmRule", "EnumRule", "FlagsRule", "NormRule", "PythonRule", "StaticRule",
    "parse_alarm_rules",
]
