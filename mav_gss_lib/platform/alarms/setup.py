"""Pure engine-assembly helpers for the alarm framework.

No FastAPI, no asyncio, no I/O. Given a parsed mission spec_root and
a registry, builds container specs, the carrier-stale index, and a
compiled parameter-rule lookup. Tests can drive these helpers directly
without bringing up a server.

Author:  Irfan Annuar - USC ISI SERC
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from mav_gss_lib.platform.alarms.evaluators.container import (
    ContainerStaleSpec, parameter_carrier_index, parse_specs_from_yaml,
    periodic_container_ids,
)
from mav_gss_lib.platform.alarms.evaluators.parameter import PluginRegistry
from mav_gss_lib.platform.alarms.registry import AlarmRegistry
from mav_gss_lib.platform.alarms.schema import AlarmRule, parse_alarm_rules


@dataclass(frozen=True, slots=True)
class AlarmEnvironment:
    container_specs: dict[str, ContainerStaleSpec]
    parameter_rules: dict[str, tuple[AlarmRule, ...]]
    plugins: PluginRegistry


def walk_concrete_entry_names(entries) -> list[str]:
    """Flatten ``SequenceContainer.entry_list`` into bare parameter names.

    ParameterRefEntry contributes its `.name`. RepeatEntry unwraps to
    `.entry.name`. PagedFrameEntry is skipped — its parameters live in
    concrete child containers that appear separately in
    ``sequence_containers`` and are walked there.
    """
    # Late import to avoid a top-level cycle: containers module imports
    # from spec types which import from contract types.
    from mav_gss_lib.platform.spec.containers import (
        PagedFrameEntry, ParameterRefEntry, RepeatEntry,
    )
    out: list[str] = []
    for e in entries:
        if isinstance(e, ParameterRefEntry):
            out.append(e.name)
        elif isinstance(e, RepeatEntry):
            inner = getattr(e, "entry", None)
            inner_name = getattr(inner, "name", None) if inner is not None else None
            if inner_name is not None:
                out.append(inner_name)
        elif isinstance(e, PagedFrameEntry):
            continue  # parameters resolved via concrete children
    return out


def compile_parameter_rules(spec_root) -> dict[str, tuple[AlarmRule, ...]]:
    """Parse every parameter's ``alarm:`` block. A single rejection logs
    and skips that parameter — does not abort engine assembly."""
    rules: dict[str, tuple[AlarmRule, ...]] = {}
    for p in spec_root.parameters.values():
        if p.alarm is None:
            continue
        qualified = f"{p.domain}.{p.name}" if p.domain else p.name
        try:
            rules[qualified] = parse_alarm_rules({"alarm": p.alarm})
        except ValueError as exc:
            logging.warning(
                "alarm rule for %s rejected: %s; parameter will not alarm",
                qualified, exc,
            )
    return rules


def build_alarm_environment(
    spec_root,
    registry: AlarmRegistry,
    last_arrival_ms: dict[str, int],
    now_ms: int,
    mission_alarm_plugins: dict | None = None,
) -> AlarmEnvironment:
    """Assemble container specs + carrier index + parameter rules.

    Mutates ``registry.set_parameter_carriers`` and seeds
    ``last_arrival_ms[cid]`` for every monitored container.
    """
    raw_containers = {
        cid: {
            "domain": c.domain,
            "expected_period_ms": getattr(c, "expected_period_ms", 0) or 0,
            "stale": getattr(c, "stale", None) or {},
            "entry_list": [{"name": n} for n in walk_concrete_entry_names(c.entry_list)],
        }
        for cid, c in spec_root.sequence_containers.items()
    }
    container_specs = parse_specs_from_yaml(raw_containers)
    periodic = periodic_container_ids(container_specs)
    parameter_domain = {
        p.name: p.domain or "" for p in spec_root.parameters.values()
    }
    registry.set_parameter_carriers(parameter_carrier_index(
        raw_containers, periodic_only=periodic,
        parameter_domain=parameter_domain,
    ))
    for cid in periodic:
        last_arrival_ms.setdefault(cid, now_ms)
    return AlarmEnvironment(
        container_specs=container_specs,
        parameter_rules=compile_parameter_rules(spec_root),
        plugins=PluginRegistry(mission_alarm_plugins or {}),
    )


__all__ = [
    "AlarmEnvironment", "build_alarm_environment", "compile_parameter_rules",
    "walk_concrete_entry_names",
]
