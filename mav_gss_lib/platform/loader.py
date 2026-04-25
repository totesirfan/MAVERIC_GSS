"""MissionSpec loader — resolve a mission id to a built MissionSpec.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from .contract.mission import MissionContext, MissionSpec

_SPEC_LOG = logging.getLogger("mav_gss_lib.platform.spec")


def _forward_parse_warnings(mission: Any) -> None:
    """Log every Mission.parse_warnings entry under the spec logger.

    Called after the mission is built so operators see authoring warnings
    at startup. The warnings are also attached to WebRuntime.parse_warnings
    for inclusion in the /ws/preflight payload.
    """
    for w in getattr(mission, "parse_warnings", ()):
        _SPEC_LOG.warning(str(w))


def load_mission_spec_from_split(
    platform_cfg: dict[str, Any],
    mission_id: str,
    mission_cfg: dict[str, Any],
    *,
    data_dir: str | Path = "logs",
) -> MissionSpec:
    """Load the active mission's MissionSpec from split state directly."""

    if not mission_id:
        raise ValueError("missing required mission id")

    module = importlib.import_module(f"mav_gss_lib.missions.{mission_id}.mission")
    build = getattr(module, "build", None)
    if build is None:
        raise ValueError(f"mission '{mission_id}' has no build(ctx) function")

    ctx = MissionContext(
        platform_config=platform_cfg,
        mission_config=mission_cfg,
        data_dir=Path(data_dir),
    )
    spec = build(ctx)
    validate_mission_spec(spec)
    _forward_parse_warnings(spec)
    return spec


def load_mission_spec(cfg: dict[str, Any], *, data_dir: str | Path = "logs") -> MissionSpec:
    """Test-only convenience: accept a native `{platform, mission}` dict and
    delegate to `load_mission_spec_from_split`.

    Production code paths (`PlatformRuntime.from_split`, `WebRuntime`) call
    `load_mission_spec_from_split` directly with the split tuple. This wrapper
    keeps test ergonomics ergonomic without smuggling the flat legacy shape
    back into the loader surface.
    """

    mission_section = cfg.get("mission") or {}
    mission_id = mission_section.get("id")
    if not mission_id:
        raise ValueError("missing required config key: mission.id")

    return load_mission_spec_from_split(
        cfg.get("platform") or {},
        mission_id,
        mission_section.get("config") or {},
        data_dir=data_dir,
    )


def validate_mission_spec(spec: MissionSpec) -> None:
    """Validate required MissionSpec shape without assuming mission vocabulary."""

    if not isinstance(spec.id, str) or not spec.id:
        raise ValueError("MissionSpec.id must be a non-empty string")
    if not isinstance(spec.name, str) or not spec.name:
        raise ValueError("MissionSpec.name must be a non-empty string")
    for attr in ("packets", "ui", "config"):
        if getattr(spec, attr, None) is None:
            raise ValueError(f"MissionSpec.{attr} is required")
