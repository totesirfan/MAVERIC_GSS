"""Platform — the mission/platform boundary and the runners that drive it.

Layout:
    contract/         — what missions implement (Protocols + types)
    rx/               — inbound packet flow: PacketPipeline, RxPipeline,
                        rx_log_record + rx_telemetry_records (JSONL envelopes)
    tx/               — outbound command flow: prepare_command, frame_command,
                        tx_log_record (JSONL envelope)
    config/           — platform-config update spec + appliers
    telemetry/        — runtime fragment/policy/state/router types
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
from .contract.rendering import (
    Cell,
    ColumnDef,
    DetailBlock,
    IntegrityBlock,
    PacketRendering,
)
from .contract.telemetry import (
    CatalogProvider,
    TelemetryDomainSpec,
    TelemetryExtractor,
    TelemetryOps,
)
from .contract.ui import UiOps
from .loader import (
    load_mission_spec,
    load_mission_spec_from_split,
    validate_mission_spec,
)
from .runtime import PlatformRuntime
from .rx.events import collect_connect_events, collect_packet_events
from .rx.logging import rx_log_record, rx_log_text, rx_telemetry_records
from .rx.packets import PacketPipeline
from .rx.pipeline import RxPipeline, RxResult
from .rx.rendering import fallback_packet_rendering, render_packet
from .rx.telemetry import extract_telemetry_fragments, ingest_packet_telemetry
from .telemetry import (
    DomainState,
    EntryLoader,
    MergePolicy,
    TelemetryFragment,
    TelemetryRouter,
    lww_by_ts,
)
from .tx.commands import CommandRejected, PreparedCommand, frame_command, prepare_command
from .tx.logging import tx_log_record

__all__ = [
    "CatalogProvider",
    "Cell",
    "ColumnDef",
    "CommandDraft",
    "CommandOps",
    "CommandRejected",
    "CommandRendering",
    "DEFAULT_PLATFORM_CONFIG_SPEC",
    "DetailBlock",
    "DomainState",
    "EncodedCommand",
    "EntryLoader",
    "EventOps",
    "FramedCommand",
    "HttpOps",
    "IntegrityBlock",
    "MergePolicy",
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
    "PlatformConfigSpec",
    "PlatformRuntime",
    "PreparedCommand",
    "RxPipeline",
    "RxResult",
    "TelemetryDomainSpec",
    "TelemetryExtractor",
    "TelemetryFragment",
    "TelemetryOps",
    "TelemetryRouter",
    "UiOps",
    "ValidationIssue",
    "apply_mission_config_update",
    "apply_platform_config_update",
    "collect_connect_events",
    "collect_packet_events",
    "extract_telemetry_fragments",
    "fallback_packet_rendering",
    "frame_command",
    "ingest_packet_telemetry",
    "load_mission_spec",
    "load_mission_spec_from_split",
    "lww_by_ts",
    "persist_mission_config",
    "prepare_command",
    "render_packet",
    "rx_log_record",
    "rx_log_text",
    "rx_telemetry_records",
    "tx_log_record",
    "validate_mission_spec",
]
