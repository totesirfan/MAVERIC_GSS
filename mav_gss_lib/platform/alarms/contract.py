"""Alarm bus contract — pure data types shared across the platform.

State machine (per alarm id, server-owned):

      condition fires
          |
          v
   UNACKED_ACTIVE  --ack-->  ACKED_ACTIVE
          |                       |
   condition clears        condition clears
          |                       |
          v                       v
   UNACKED_CLEARED --ack-->  (removed; AlarmChange.removed=True)
                                   |
                                   v
                          ACKED_ACTIVE  --condition clears--> (removed; removed=True)

Severity uses the XTCE-aligned trio (WATCH/WARNING/CRITICAL).

Author:  Irfan Annuar - USC ISI SERC
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any


class Severity(IntEnum):
    WATCH = 1
    WARNING = 2
    CRITICAL = 3

    @classmethod
    def from_name(cls, name: str) -> "Severity":
        return cls[name.strip().upper()]


class AlarmState(StrEnum):
    UNACKED_ACTIVE = "unacked_active"
    ACKED_ACTIVE = "acked_active"
    UNACKED_CLEARED = "unacked_cleared"


class AlarmSource(StrEnum):
    PLATFORM = "platform"
    CONTAINER = "container"
    PARAMETER = "parameter"


@dataclass(frozen=True, slots=True)
class AlarmEvent:
    id: str
    source: AlarmSource
    label: str
    detail: str
    severity: Severity
    state: AlarmState
    first_seen_ms: int
    last_eval_ms: int
    last_transition_ms: int
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AlarmChange:
    """Emitted by the registry on every state-machine transition.

    ``removed`` is True iff this change drops the entry from the
    registry. Clients use it to delete (vs. upsert) their local state.
    """
    event: AlarmEvent
    prev_state: AlarmState | None
    prev_severity: Severity | None
    removed: bool = False
    operator: str = ""


__all__ = [
    "AlarmChange", "AlarmEvent", "AlarmSource", "AlarmState", "Severity",
]
