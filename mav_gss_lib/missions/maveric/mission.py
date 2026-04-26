"""MAVERIC MissionSpec entry point — declarative pipeline.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mav_gss_lib.missions.maveric.declarative import build_declarative_capabilities
from mav_gss_lib.missions.maveric.identity_router import get_identity_router
from mav_gss_lib.missions.maveric.imaging.events import MavericImagingEvents
from mav_gss_lib.missions.maveric.imaging import ImageAssembler, get_imaging_router
from mav_gss_lib.missions.maveric.packets import DeclarativePacketsAdapter
from mav_gss_lib.missions.maveric.plugins import PLUGINS
from mav_gss_lib.missions.maveric.preflight import build_preflight
from mav_gss_lib.missions.maveric.ui.formatters import _assert_dispatch_plugins_registered
from mav_gss_lib.missions.maveric.ui.ops import MavericUiOps
from mav_gss_lib.platform import EventOps, MissionConfigSpec, MissionContext, MissionSpec
from mav_gss_lib.platform.contract.mission import HttpOps


MISSION_DIR = Path(os.path.abspath(os.path.dirname(__file__)))
MISSION_YML_PATH = MISSION_DIR / "mission.yml"

_AX25_DEFAULTS = {
    "src_call": "NOCALL", "src_ssid": 0,
    "dest_call": "NOCALL", "dest_ssid": 0,
}
_CSP_DEFAULTS = {
    "priority": 2, "source": 0, "destination": 0,
    "dest_port": 0, "src_port": 0, "flags": 0, "csp_crc": True,
}
_IMAGING_DEFAULTS = {"thumb_prefix": "tn_"}
_TX_DEFAULTS = {"frequency": "XXX.XX MHz", "uplink_mode": "ASM+Golay"}


def _seed(mission_cfg: dict[str, Any], platform_cfg: dict[str, Any]) -> None:
    """Gap-fill operator-overridable defaults. Identity keys
    (nodes/ptypes/mission_name) live in mission.yml extensions and are
    NOT seeded into mission_cfg — the codec is the protection."""
    for key, defaults in (
        ("ax25", _AX25_DEFAULTS),
        ("csp", _CSP_DEFAULTS),
        ("imaging", _IMAGING_DEFAULTS),
    ):
        existing = mission_cfg.get(key) if isinstance(mission_cfg.get(key), dict) else {}
        merged = dict(defaults)
        merged.update(existing)
        mission_cfg[key] = merged
    if isinstance(platform_cfg, dict):
        tx_cfg = platform_cfg.setdefault("tx", {})
        if isinstance(tx_cfg, dict):
            for k, v in _TX_DEFAULTS.items():
                tx_cfg.setdefault(k, v)


def _image_dir(mission_cfg: dict[str, Any]) -> str:
    imaging = mission_cfg.get("imaging") or {}
    return str(imaging.get("dir") or mission_cfg.get("image_dir") or "images")


def build(ctx: MissionContext) -> MissionSpec:
    _seed(ctx.mission_config, ctx.platform_config)

    capabilities = build_declarative_capabilities(
        mission_yml_path=MISSION_YML_PATH,
        platform_cfg=ctx.platform_config,
        mission_cfg=ctx.mission_config,
    )
    # Fail-loud at boot if the formatter dispatch table drifts from the
    # plugin registry.
    _assert_dispatch_plugins_registered(PLUGINS)

    image_assembler = ImageAssembler(_image_dir(ctx.mission_config))
    # Accessor closes over the live `ctx.mission_config` reference so
    # /api/config edits to `imaging.thumb_prefix` reach the imaging router
    # without a MissionSpec rebuild.
    routers = [
        get_imaging_router(image_assembler, config_accessor=lambda: ctx.mission_config),
        get_identity_router(capabilities.packet_codec, capabilities.mission),
    ]

    preflight_hook = build_preflight(
        platform_config=ctx.platform_config,
        mission_config=ctx.mission_config,
        mission_dir=MISSION_DIR,
    )

    return MissionSpec(
        id="maveric",
        name=str(ctx.mission_config.get("mission_name") or "MAVERIC"),
        packets=DeclarativePacketsAdapter(
            codec=capabilities.packet_codec,
            mission=capabilities.mission,
        ),
        commands=capabilities.command_ops,
        ui=MavericUiOps(
            codec=capabilities.packet_codec,
            mission=capabilities.mission,
        ),
        telemetry=capabilities.telemetry_ops,
        events=EventOps(sources=[MavericImagingEvents(
            codec=capabilities.packet_codec,
            image_assembler=image_assembler,
        )]),
        http=HttpOps(routers=routers),
        config=MissionConfigSpec(
            editable_paths={"ax25.*", "csp.*", "imaging.thumb_prefix"},
            # mission.yml is the protection — operators can't edit
            # identity (nodes/ptypes/mission_name) via /api/config because
            # those keys live in mission.yml extensions, not mission_cfg.
            protected_paths=set(),
        ),
        preflight=preflight_hook,
    )
