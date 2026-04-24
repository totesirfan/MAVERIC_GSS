"""Platform RX runners — the inbound packet flow.

    packets.py   — PacketPipeline (dedup window, sequence, rate counters)
    telemetry.py — extract_telemetry_fragments + ingest_packet_telemetry
    events.py    — collect_connect_events + collect_packet_events
    rendering.py — render_packet + fallback (safe wrappers over mission UI)
    logging.py   — rx_log_record (rx_packet envelope),
                   rx_telemetry_records (one event per TelemetryFragment),
                   rx_log_text (mission text-log lines)
    pipeline.py  — RxPipeline + RxResult (stitches the above into a single call)

Author:  Irfan Annuar - USC ISI SERC
"""

from .events import collect_connect_events, collect_packet_events
from .logging import rx_log_record, rx_log_text, rx_telemetry_records
from .packets import PacketPipeline
from .pipeline import RxPipeline, RxResult
from .rendering import fallback_packet_rendering, render_packet
from .telemetry import extract_telemetry_fragments, ingest_packet_telemetry

__all__ = [
    "PacketPipeline",
    "RxPipeline",
    "RxResult",
    "collect_connect_events",
    "collect_packet_events",
    "extract_telemetry_fragments",
    "fallback_packet_rendering",
    "ingest_packet_telemetry",
    "render_packet",
    "rx_log_record",
    "rx_log_text",
    "rx_telemetry_records",
]
