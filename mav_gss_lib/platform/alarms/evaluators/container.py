"""Container staleness evaluator — one alarm per stalled packet stream.

Carrier index resolves each entry's parameter name to the parameter-level
domain (matching ParameterCache.apply keys). Without the resolver, a
container with `domain: spacecraft` carrying `gnc.RATE` would be
indexed under `spacecraft.RATE`, never matching the cache key.

Cold-start: producer (RxService) seeds last_arrival_ms[cid]=now_ms for
every monitored container at construction. With no missing key, the
evaluator's `last_arrival_ms[cid]` only raises KeyError when the caller
forgot to seed; in production it always has a real timestamp.

Author:  Irfan Annuar - USC ISI SERC
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from mav_gss_lib.platform.alarms.contract import AlarmSource, Severity
from mav_gss_lib.platform.alarms.registry import Verdict


@dataclass(frozen=True, slots=True)
class ContainerStaleSpec:
    container_id: str
    label: str
    expected_period_ms: int
    warning_after_ms: int
    critical_after_ms: int

    @property
    def monitored(self) -> bool:
        return self.warning_after_ms > 0 or self.critical_after_ms > 0


def evaluate_containers(
    specs: Mapping[str, ContainerStaleSpec],
    last_arrival_ms: Mapping[str, int],
    now_ms: int,
) -> list[Verdict]:
    """Pure verdict producer. Caller must seed ``last_arrival_ms[cid]`` for
    every monitored container at startup (so cold-start does not fire
    stale alarms before the first packet)."""
    out: list[Verdict] = []
    for cid, spec in specs.items():
        if not spec.monitored:
            continue
        last = last_arrival_ms[cid]  # KeyError => caller forgot to seed
        age_ms = max(0, now_ms - last)
        sev = _severity_for_age(age_ms, spec)
        out.append(Verdict(
            id=f"container.{cid}.stale", source=AlarmSource.CONTAINER,
            label=f"{spec.label} STALE", severity=sev,
            detail=_format_detail(age_ms) if sev else "",
            context={"container_id": cid, "age_ms": age_ms,
                     "expected_period_ms": spec.expected_period_ms,
                     "last_arrival_ms": last},
        ))
    return out


def _severity_for_age(age_ms: int, spec: ContainerStaleSpec) -> Severity | None:
    if spec.critical_after_ms and age_ms >= spec.critical_after_ms:
        return Severity.CRITICAL
    if spec.warning_after_ms and age_ms >= spec.warning_after_ms:
        return Severity.WARNING
    return None


def _format_detail(age_ms: int) -> str:
    if age_ms < 60_000:
        return f"no packet for {age_ms // 1000}s"
    if age_ms < 3_600_000:
        return f"no packet for {age_ms // 60_000}m"
    return f"no packet for {age_ms // 3_600_000}h{(age_ms // 60_000) % 60}m"


def parse_specs_from_yaml(
    sequence_containers: Mapping[str, dict],
) -> dict[str, ContainerStaleSpec]:
    out: dict[str, ContainerStaleSpec] = {}
    for cid, body in sequence_containers.items():
        if not isinstance(body, dict):
            continue
        stale = body.get("stale") or {}
        # Replace underscores with spaces for operator-friendly labels
        label = cid.replace("_", " ").upper()
        out[cid] = ContainerStaleSpec(
            container_id=cid, label=label,
            expected_period_ms=int(body.get("expected_period_ms") or 0),
            warning_after_ms=int(stale.get("warning_after_ms") or 0),
            critical_after_ms=int(stale.get("critical_after_ms") or 0),
        )
    return out


def parameter_carrier_index(
    sequence_containers: Mapping[str, dict],
    *,
    periodic_only: set[str] | frozenset[str],
    parameter_domain: Mapping[str, str],
) -> dict[str, set[str]]:
    """Build parameter-name -> {container_ids} reverse index.

    ``parameter_domain`` maps bare parameter name (e.g. ``"RATE"``) to
    its parameter-level domain (e.g. ``"gnc"``). Falls back to the
    container's domain for entries whose parameter has none. The
    resulting key (``"<domain>.<name>"``) matches ParameterCache keys.
    """
    out: dict[str, set[str]] = {}
    for cid, body in sequence_containers.items():
        if not isinstance(body, dict):
            continue
        if cid not in periodic_only:
            continue
        container_domain = body.get("domain") or ""
        for entry in body.get("entry_list") or []:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not name:
                continue
            domain = parameter_domain.get(name) or container_domain
            qualified = f"{domain}.{name}" if domain else str(name)
            out.setdefault(qualified, set()).add(cid)
    return out


def periodic_container_ids(specs: Mapping[str, ContainerStaleSpec]) -> set[str]:
    return {cid for cid, s in specs.items() if s.monitored}


__all__ = [
    "ContainerStaleSpec", "evaluate_containers", "parameter_carrier_index",
    "parse_specs_from_yaml", "periodic_container_ids",
]
