"""Platform — the mission/platform boundary and the runners that drive it.

Layout:
    contract/         — what missions implement (Protocols + types)
    rx/               — inbound packet flow: PacketPipeline, RxPipeline,
                        rx_log_record + parameter_log_records (JSONL envelopes)
    tx/               — outbound command flow: prepare_command, frame_command,
                        tx_log_record (JSONL envelope)
    config/           — platform-config update spec + appliers
    parameter_cache.py — flat ParameterCache (single source of live state)
    runtime.py        — PlatformRuntime container
    loader.py         — MissionSpec loading
    _log_envelope.py  — shared new_event_id + ts_iso helpers (RX/TX)

Most callers import from this facade:
    from mav_gss_lib.platform import MissionSpec, PacketOps, CommandOps

Author:  Irfan Annuar - USC ISI SERC
"""

from .config.spec import DEFAULT_PLATFORM_CONFIG_SPEC, PlatformConfigSpec
from .config.updates import (
    apply_mission_config_update,
    apply_platform_config_update,
    persist_mission_config,
)
from .contract.commands import (
    CommandDraft,
    CommandOps,
    CommandRendering,
    EncodedCommand,
    FramedCommand,
    ValidationIssue,
)
from .contract.events import EventOps, PacketEventSource
from .contract.http import HttpOps
from .contract.mission import (
    MissionConfigSpec,
    MissionContext,
    MissionPreflightFn,
    MissionSpec,
)
from .contract.packets import (
    MissionPacket,
    NormalizedPacket,
    PacketEnvelope,
    PacketFlags,
    PacketOps,
)
from .contract.parameters import ParamUpdate
from .contract.rendering import (
    Cell,
    ColumnDef,
    DetailBlock,
    IntegrityBlock,
    PacketRendering,
)
from .contract.ui import UiOps
from .loader import (
    load_mission_spec,
    load_mission_spec_from_split,
    validate_mission_spec,
)
from .parameter_cache import ParameterCache
from .runtime import PlatformRuntime
from .rx.events import collect_connect_events, collect_packet_events
from .rx.logging import parameter_log_records, rx_log_record, rx_log_text
from .rx.packet_pipeline import PacketPipeline
from .rx.pipeline import RxPipeline, RxResult
from .rx.rendering import fallback_packet_rendering, render_packet
from .tx.commands import CommandRejected, PreparedCommand, frame_command, prepare_command
from .tx.logging import tx_log_record
from . import spec

__all__ = [
    "Cell",
    "ColumnDef",
    "CommandDraft",
    "CommandOps",
    "CommandRejected",
    "CommandRendering",
    "DEFAULT_PLATFORM_CONFIG_SPEC",
    "DetailBlock",
    "EncodedCommand",
    "EventOps",
    "FramedCommand",
    "HttpOps",
    "IntegrityBlock",
    "MissionConfigSpec",
    "MissionContext",
    "MissionPacket",
    "MissionPreflightFn",
    "MissionSpec",
    "NormalizedPacket",
    "PacketEnvelope",
    "PacketEventSource",
    "PacketFlags",
    "PacketOps",
    "PacketPipeline",
    "PacketRendering",
    "ParamUpdate",
    "ParameterCache",
    "PlatformConfigSpec",
    "PlatformRuntime",
    "PreparedCommand",
    "RxPipeline",
    "RxResult",
    "UiOps",
    "ValidationIssue",
    "apply_mission_config_update",
    "apply_platform_config_update",
    "collect_connect_events",
    "collect_packet_events",
    "fallback_packet_rendering",
    "frame_command",
    "load_mission_spec",
    "load_mission_spec_from_split",
    "parameter_log_records",
    "persist_mission_config",
    "prepare_command",
    "render_packet",
    "rx_log_record",
    "rx_log_text",
    "tx_log_record",
    "validate_mission_spec",
]
