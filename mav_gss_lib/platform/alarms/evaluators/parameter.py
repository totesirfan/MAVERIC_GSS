"""Parameter alarm evaluator — dispatch over rule kinds.

Field selector ``on:`` supports:
  - string: dict key (``value.get(on)``)
  - integer: sequence index (``value[on]``)
  - mismatch: returns None → no alarm fires (silent rather than throw)

Author:  Irfan Annuar - USC ISI SERC
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from mav_gss_lib.platform.alarms.contract import AlarmSource, Severity
from mav_gss_lib.platform.alarms.registry import Verdict
from mav_gss_lib.platform.alarms.schema import (
    AlarmRule, EnumRule, FlagsRule, NormRule, PythonRule, StaticRule,
)


PluginCallable = Callable[[Any], tuple[Severity | None, str]]


@dataclass(frozen=True, slots=True)
class PluginRegistry:
    plugins: Mapping[str, PluginCallable]

    def get(self, ref: str) -> PluginCallable | None:
        return self.plugins.get(ref)


def evaluate_parameter(
    parameter_event_base: str,
    rules: Iterable[AlarmRule],
    value: Any,
    *,
    plugins: PluginRegistry | None = None,
) -> list[Verdict]:
    rules = tuple(rules)
    multi = len(rules) > 1
    out: list[Verdict] = []
    for rule in rules:
        target = _select_field(rule, value)
        sev, detail = _dispatch(rule, target, plugins)
        out.append(Verdict(
            id=_event_id(parameter_event_base, rule, multi),
            source=AlarmSource.PARAMETER,
            label=parameter_event_base.split(".")[-1].upper(),
            severity=sev, detail=detail,
            persistence_required=getattr(rule, "persistence", 1),
            latched=getattr(rule, "latched", False),
            context={"raw": _safe_for_context(value)},
        ))
    return out


def _select_field(rule: AlarmRule, value: Any) -> Any:
    on = getattr(rule, "on", None)
    if on is None:
        return value
    if isinstance(on, str):
        if isinstance(value, dict):
            return value.get(on)
        return None
    if isinstance(on, int):
        if isinstance(value, (list, tuple)):
            try:
                return value[on]
            except IndexError:
                return None
        return None
    return None


def _event_id(base: str, rule: AlarmRule, multi: bool) -> str:
    if not multi:
        return base
    on = getattr(rule, "on", None)
    if on is not None:
        return f"{base}.{on}"
    # No selector + multi-rule: use rule kind to disambiguate. Two rules
    # of the same kind without selectors collide; reject at parse time
    # would be cleaner, but currently no mission-yml uses that shape.
    return f"{base}.{type(rule).__name__.lower().replace('rule', '')}"


def _dispatch(rule, target, plugins):
    if target is None and not isinstance(rule, FlagsRule):
        return None, ""
    if isinstance(rule, StaticRule):
        return _eval_static(rule, target)
    if isinstance(rule, NormRule):
        return _eval_norm(rule, target)
    if isinstance(rule, EnumRule):
        return _eval_enum(rule, target)
    if isinstance(rule, FlagsRule):
        return _eval_flags(rule, target)
    if isinstance(rule, PythonRule):
        return _eval_python(rule, target, plugins)
    return None, ""


def _eval_static(rule: StaticRule, target: Any) -> tuple[Severity | None, str]:
    try:
        x = float(target)
    except (TypeError, ValueError):
        return None, ""
    for sev in (Severity.CRITICAL, Severity.WARNING, Severity.WATCH):
        band = rule.bands.get(sev)
        if band is None:
            continue
        lo, hi = band
        if (lo is not None and x < lo) or (hi is not None and x > hi):
            return sev, f"{x:g}"
    return None, ""


def _eval_norm(rule: NormRule, target: Any) -> tuple[Severity | None, str]:
    try:
        components = list(target)
        if not components:
            return None, ""
        n = math.sqrt(sum(float(c) * float(c) for c in components))
    except (TypeError, ValueError):
        return None, ""
    for sev in (Severity.CRITICAL, Severity.WARNING, Severity.WATCH):
        band = rule.bands.get(sev)
        if band is None:
            continue
        lo, hi = band
        if (lo is not None and n < lo) or (hi is not None and n > hi):
            return sev, f"‖v‖={n:g}"
    return None, ""


def _eval_enum(rule: EnumRule, target: Any) -> tuple[Severity | None, str]:
    if target is True:
        key = "true"
    elif target is False:
        key = "false"
    else:
        key = str(target)
    if key in rule.map:
        return rule.map[key], key
    if rule.default is not None:
        return rule.default, key
    return None, ""


def _eval_flags(rule: FlagsRule, value: Any) -> tuple[Severity | None, str]:
    if not isinstance(value, dict):
        return None, ""
    triggered: list[tuple[Severity, str]] = []

    def _check(names: tuple[str, ...], sev: Severity, want_set: bool) -> None:
        hits = []
        for n in names:
            if n not in value:
                continue  # missing key != cleared
            if bool(value[n]) is want_set:
                hits.append(n)
        if hits:
            triggered.append((sev, ",".join(hits)))

    _check(rule.critical_if_any, Severity.CRITICAL, True)
    _check(rule.warning_if_any,  Severity.WARNING,  True)
    _check(rule.watch_if_any,    Severity.WATCH,    True)
    _check(rule.critical_if_clear, Severity.CRITICAL, False)
    _check(rule.warning_if_clear,  Severity.WARNING,  False)

    if not triggered:
        return None, ""
    sev = max(s for s, _ in triggered)
    detail = "; ".join(d for s, d in triggered if s == sev)
    return sev, detail


def _eval_python(rule: PythonRule, target: Any,
                 plugins: PluginRegistry | None) -> tuple[Severity | None, str]:
    if plugins is None:
        return None, ""
    fn = plugins.get(rule.callable_ref)
    if fn is None:
        return None, ""
    try:
        result = fn(target)
    except Exception:
        return None, ""
    if not isinstance(result, tuple) or len(result) != 2:
        return None, ""
    sev, detail = result
    return sev, str(detail or "")


def _safe_for_context(value):
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {k: _safe_for_context(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_for_context(v) for v in value]
    return repr(value)


__all__ = ["PluginRegistry", "evaluate_parameter"]
