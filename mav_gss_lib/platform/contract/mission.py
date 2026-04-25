"""Top-level mission spec — the single mission/platform boundary.

A `MissionSpec` bundles the mission's packet/command/telemetry/event
capabilities, its UI surface, its optional HTTP routers, its preflight
hook, and its config-shape declaration. Missions build one at load time;
the platform consumes it.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .commands import CommandOps
from .events import EventOps
from .http import HttpOps
from .packets import PacketOps
from .telemetry import TelemetryOps
from .ui import UiOps


# Typed loosely as `Iterable[Any]` to avoid a platform → preflight import
# cycle; concrete objects are `mav_gss_lib.preflight.CheckResult`.
MissionPreflightFn = Callable[[], Iterable[Any]]


@dataclass(frozen=True, slots=True)
class MissionConfigSpec:
    schema: dict[str, Any] = field(default_factory=dict)
    editable_paths: set[str] = field(default_factory=set)
    protected_paths: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class MissionContext:
    platform_config: dict[str, Any]
    mission_config: dict[str, Any]
    data_dir: Path


@dataclass(frozen=True, slots=True)
class MissionSpec:
    id: str
    name: str
    packets: PacketOps
    ui: UiOps
    config: MissionConfigSpec
    commands: CommandOps | None = None
    telemetry: TelemetryOps | None = None
    events: EventOps | None = None
    http: HttpOps | None = None
    preflight: MissionPreflightFn | None = None
    # Non-fatal warnings produced when constructing this MissionSpec —
    # surfaced in /ws/preflight payload and the spec logger at startup.
    # Empty for hand-built missions; populated by the declarative YAML path.
    parse_warnings: tuple[Any, ...] = ()
