"""Platform verifier types.

Shapes the verifier state machine consumes; no behavior. The registry that
applies behavior lives in the same module (added in a later task) and pairs
with `CheckWindow` timers and persistence.

Stage is derived from the full verifier outcome map, not a linear chain.
See docs/superpowers/specs/2026-04-24-command-verification-design.md §4.4
for the derivation rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


VerifierStage = Literal["received", "accepted", "complete", "failed"]
VerifierState = Literal["pending", "passed", "failed", "window_expired"]
InstanceStage = Literal[
    "released", "received", "accepted", "complete", "failed", "timed_out",
]


@dataclass(frozen=True, slots=True)
class CheckWindow:
    start_ms: int
    stop_ms: int


@dataclass(frozen=True, slots=True)
class VerifierSpec:
    verifier_id: str          # opaque mission-assigned
    stage: VerifierStage
    check_window: CheckWindow
    display_label: str        # e.g. "UPPM" — mission-provided
    display_tone: str         # 'info' | 'success' | 'warning' | 'danger'


@dataclass(frozen=True, slots=True)
class VerifierSet:
    verifiers: tuple[VerifierSpec, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for v in self.verifiers:
            if v.verifier_id in seen:
                raise ValueError(f"duplicate verifier_id in VerifierSet: {v.verifier_id}")
            seen.add(v.verifier_id)


@dataclass(frozen=True, slots=True)
class VerifierOutcome:
    state: VerifierState
    matched_at_ms: int | None = None
    match_event_id: str | None = None

    @classmethod
    def pending(cls) -> "VerifierOutcome":
        return cls(state="pending")

    @classmethod
    def passed(cls, *, matched_at_ms: int, match_event_id: str) -> "VerifierOutcome":
        return cls(state="passed", matched_at_ms=matched_at_ms, match_event_id=match_event_id)

    @classmethod
    def failed(cls, *, matched_at_ms: int, match_event_id: str) -> "VerifierOutcome":
        return cls(state="failed", matched_at_ms=matched_at_ms, match_event_id=match_event_id)

    @classmethod
    def window_expired(cls) -> "VerifierOutcome":
        return cls(state="window_expired")


@dataclass(slots=True)
class CommandInstance:
    instance_id: str
    correlation_key: tuple
    t0_ms: int
    cmd_event_id: str
    verifier_set: VerifierSet
    outcomes: dict[str, VerifierOutcome] = field(default_factory=dict)
    stage: InstanceStage = "released"
