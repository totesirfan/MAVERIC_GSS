"""AlarmRegistry — single in-process owner of alarm state.

Author:  Irfan Annuar - USC ISI SERC
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Iterable, Mapping

from mav_gss_lib.platform.alarms.contract import (
    AlarmChange, AlarmEvent, AlarmSource, AlarmState, Severity,
)


@dataclass(slots=True)
class _AlarmEntry:
    id: str
    source: AlarmSource
    label: str
    detail: str
    severity: Severity
    state: AlarmState
    first_seen_ms: int
    last_eval_ms: int
    last_transition_ms: int
    context: dict
    latched: bool

    def snapshot(self) -> AlarmEvent:
        return AlarmEvent(
            id=self.id, source=self.source, label=self.label, detail=self.detail,
            severity=self.severity, state=self.state,
            first_seen_ms=self.first_seen_ms, last_eval_ms=self.last_eval_ms,
            last_transition_ms=self.last_transition_ms, context=dict(self.context),
        )


@dataclass(frozen=True, slots=True)
class Verdict:
    id: str
    source: AlarmSource
    label: str
    severity: Severity | None
    detail: str = ""
    context: dict = field(default_factory=dict)
    persistence_required: int = 1
    latched: bool = False


class CarrierStaleIndex:
    """Per-parameter carrier-stale tracking, decoupled from the registry.

    A parameter is "fresh" iff at least one of its declared carriers is
    fresh; "stale" iff every carrier is stale. The registry hands
    container verdicts in via ``update_from_verdict``; consumers query
    ``stale_for(parameter_name)`` to decide whether to suppress parameter
    alarms.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._parameter_carriers: dict[str, frozenset[str]] = {}
        self._stale_carriers: set[str] = set()

    def set_parameter_carriers(self, mapping: Mapping[str, Iterable[str]]) -> None:
        with self._lock:
            self._parameter_carriers = {
                name: frozenset(carriers) for name, carriers in mapping.items()
            }

    def stale_for(self, parameter_name: str) -> bool:
        with self._lock:
            carriers = self._parameter_carriers.get(parameter_name)
            if not carriers:
                return False
            return carriers.issubset(self._stale_carriers)

    def update_from_verdict(self, verdict: "Verdict") -> None:
        if verdict.source is not AlarmSource.CONTAINER:
            return
        cid = verdict.context.get("container_id") if isinstance(verdict.context, dict) else None
        if not cid:
            return
        with self._lock:
            if verdict.severity is not None:
                self._stale_carriers.add(cid)
            else:
                self._stale_carriers.discard(cid)


class AlarmRegistry:
    def __init__(self, *, carriers: CarrierStaleIndex | None = None) -> None:
        self._lock = RLock()
        self._entries: dict[str, _AlarmEntry] = {}
        self._pending: dict[str, int] = {}
        self.carriers = carriers if carriers is not None else CarrierStaleIndex()

    # -- carrier index passthroughs (kept for ergonomics) --------------

    def set_parameter_carriers(self, mapping: Mapping[str, Iterable[str]]) -> None:
        self.carriers.set_parameter_carriers(mapping)

    def carrier_stale_for(self, parameter_name: str) -> bool:
        return self.carriers.stale_for(parameter_name)

    # -- state machine --------------------------------------------------

    def observe(self, verdict: Verdict, now_ms: int) -> AlarmChange | None:
        with self._lock:
            # Carrier-stale tracking reflects the *condition*, not the alarm
            # state. Latched container alarms can stay visible while the
            # carrier resumes — parameter alarms re-engage as soon as the
            # condition clears, regardless of whether the operator has acked.
            self.carriers.update_from_verdict(verdict)

            entry = self._entries.get(verdict.id)
            if verdict.severity is None:
                self._pending.pop(verdict.id, None)
                return self._maybe_clear(entry, now_ms)
            if entry is None:
                return self._observe_pending(verdict, now_ms)
            self._pending.pop(verdict.id, None)
            return self._update_existing(entry, verdict, now_ms)

    def _observe_pending(self, verdict: Verdict, now_ms: int) -> AlarmChange | None:
        if verdict.persistence_required <= 1:
            self._pending.pop(verdict.id, None)
            return self._fire_new(verdict, now_ms)
        count = self._pending.get(verdict.id, 0) + 1
        if count >= verdict.persistence_required:
            self._pending.pop(verdict.id, None)
            return self._fire_new(verdict, now_ms)
        self._pending[verdict.id] = count
        return None

    def _fire_new(self, verdict: Verdict, now_ms: int) -> AlarmChange:
        entry = _AlarmEntry(
            id=verdict.id, source=verdict.source, label=verdict.label,
            detail=verdict.detail, severity=verdict.severity or Severity.WATCH,
            state=AlarmState.UNACKED_ACTIVE,
            first_seen_ms=now_ms, last_eval_ms=now_ms, last_transition_ms=now_ms,
            context=dict(verdict.context), latched=verdict.latched,
        )
        self._entries[verdict.id] = entry
        return AlarmChange(event=entry.snapshot(), prev_state=None,
                           prev_severity=None, removed=False)

    def _update_existing(self, entry: _AlarmEntry, verdict: Verdict,
                         now_ms: int) -> AlarmChange | None:
        prev_state = entry.state
        prev_severity = entry.severity
        entry.last_eval_ms = now_ms

        if entry.state is AlarmState.UNACKED_CLEARED:
            entry.state = AlarmState.UNACKED_ACTIVE
            entry.first_seen_ms = now_ms
            entry.last_transition_ms = now_ms
            entry.severity = verdict.severity or entry.severity
            entry.detail = verdict.detail or entry.detail
            if verdict.context:
                entry.context = dict(verdict.context)
            return AlarmChange(event=entry.snapshot(), prev_state=prev_state,
                               prev_severity=prev_severity, removed=False)

        # Active states — broadcast on severity OR detail change so UI sees
        # fresh values even when the band hasn't shifted.
        emit = (
            verdict.severity != entry.severity
            or (verdict.detail and verdict.detail != entry.detail)
        )
        if verdict.severity != entry.severity:
            entry.severity = verdict.severity or entry.severity
            entry.last_transition_ms = now_ms
        if verdict.detail:
            entry.detail = verdict.detail
        if verdict.context:
            entry.context = dict(verdict.context)
        if emit:
            return AlarmChange(event=entry.snapshot(), prev_state=prev_state,
                               prev_severity=prev_severity, removed=False)
        return None

    def _maybe_clear(self, entry: _AlarmEntry | None, now_ms: int) -> AlarmChange | None:
        if entry is None:
            return None
        if entry.latched and entry.state in (AlarmState.UNACKED_ACTIVE,
                                             AlarmState.ACKED_ACTIVE):
            return None
        prev_state = entry.state
        prev_severity = entry.severity
        entry.last_eval_ms = now_ms

        if entry.state is AlarmState.UNACKED_ACTIVE:
            entry.state = AlarmState.UNACKED_CLEARED
            entry.last_transition_ms = now_ms
            return AlarmChange(event=entry.snapshot(), prev_state=prev_state,
                               prev_severity=prev_severity, removed=False)
        if entry.state is AlarmState.ACKED_ACTIVE:
            removed = entry.snapshot()
            self._entries.pop(entry.id, None)
            return AlarmChange(event=removed, prev_state=prev_state,
                               prev_severity=prev_severity, removed=True)
        return None

    # -- operator actions ----------------------------------------------

    def acknowledge(self, alarm_id: str, now_ms: int,
                    operator: str = "") -> AlarmChange | None:
        with self._lock:
            entry = self._entries.get(alarm_id)
            if entry is None:
                return None
            prev_state = entry.state
            prev_severity = entry.severity

            if entry.state is AlarmState.UNACKED_ACTIVE:
                entry.state = AlarmState.ACKED_ACTIVE
                entry.last_transition_ms = now_ms
                return AlarmChange(event=entry.snapshot(), prev_state=prev_state,
                                   prev_severity=prev_severity, removed=False,
                                   operator=operator)
            if entry.state is AlarmState.UNACKED_CLEARED:
                removed = entry.snapshot()
                self._entries.pop(alarm_id, None)
                return AlarmChange(event=removed, prev_state=prev_state,
                                   prev_severity=prev_severity, removed=True,
                                   operator=operator)
            return None

    def acknowledge_all(self, now_ms: int, operator: str = "") -> list[AlarmChange]:
        with self._lock:
            ids = list(self._entries.keys())
        out = []
        for aid in ids:
            ch = self.acknowledge(aid, now_ms, operator)
            if ch is not None:
                out.append(ch)
        return out

    def snapshot(self) -> list[AlarmEvent]:
        with self._lock:
            return [e.snapshot() for e in self._entries.values()]


__all__ = ["AlarmRegistry", "CarrierStaleIndex", "Verdict"]
