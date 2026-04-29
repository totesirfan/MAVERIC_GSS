"""Platform — the mission/platform boundary and the runners that drive it.

Layout:
    contract/         — what missions implement (Protocols + types)
    rx/               — inbound packet flow: PacketPipeline, RxPipeline
    tx/               — outbound command flow: prepare_command, frame_command
    log_records.py    — unified JSONL event record builders
    config/           — platform-config update spec + appliers
    parameter_cache.py — flat ParameterCache (single source of live state)
    runtime.py        — PlatformRuntime container
    loader.py         — MissionSpec loading
    _log_envelope.py  — shared new_event_id + ts_iso helpers

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
from .loader import (
    load_mission_spec,
    load_mission_spec_from_split,
    validate_mission_spec,
)
from .parameter_cache import ParameterCache
from .runtime import PlatformRuntime
from .log_records import (
    parameter_records,
    radio_event_record,
    rx_packet_record,
    tx_command_record,
)
from .rx.events import collect_connect_events, collect_packet_events
from .rx.packet_pipeline import PacketPipeline
from .rx.pipeline import RxPipeline, RxResult
from .rx.records import RxDecodedRecord, RxIngestRecord, make_ingest_record
from .tx.commands import CommandRejected, PreparedCommand, frame_command, prepare_command
from . import spec

__all__ = [
    "CommandDraft",
    "CommandOps",
    "CommandRejected",
    "DEFAULT_PLATFORM_CONFIG_SPEC",
    "EncodedCommand",
    "EventOps",
    "FramedCommand",
    "HttpOps",
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
    "ParamUpdate",
    "ParameterCache",
    "PlatformConfigSpec",
    "PlatformRuntime",
    "PreparedCommand",
    "RxDecodedRecord",
    "RxIngestRecord",
    "RxPipeline",
    "RxResult",
    "ValidationIssue",
    "apply_mission_config_update",
    "apply_platform_config_update",
    "collect_connect_events",
    "collect_packet_events",
    "frame_command",
    "load_mission_spec",
    "load_mission_spec_from_split",
    "make_ingest_record",
    "parameter_records",
    "persist_mission_config",
    "prepare_command",
    "radio_event_record",
    "rx_packet_record",
    "tx_command_record",
    "validate_mission_spec",
]
