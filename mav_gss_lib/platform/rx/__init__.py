"""Platform RX runners — the inbound packet flow.

    packet_pipeline.py — PacketPipeline (dedup window, sequence, rate counters)
    events.py       — collect_connect_events + collect_packet_events
    rendering.py    — render_packet + fallback (safe wrappers over mission UI)
    logging.py      — rx_log_record (rx_packet envelope),
                      parameter_log_records (one event per ParamUpdate),
                      rx_log_text (mission text-log lines)
    frame_detect.py — detect_frame_type + normalize_frame + is_noise_frame
                      (transport-metadata heuristics; mission- and server-safe)
    pipeline.py     — RxPipeline + RxResult (stitches the above into a single call)

Author:  Irfan Annuar - USC ISI SERC
"""

from .events import collect_connect_events, collect_packet_events
from .frame_detect import detect_frame_type, is_noise_frame, normalize_frame
from .logging import parameter_log_records, rx_log_record, rx_log_text
from .packet_pipeline import PacketPipeline
from .pipeline import RxPipeline, RxResult
from .rendering import fallback_packet_rendering, render_packet

__all__ = [
    "PacketPipeline",
    "RxPipeline",
    "RxResult",
    "collect_connect_events",
    "collect_packet_events",
    "detect_frame_type",
    "fallback_packet_rendering",
    "is_noise_frame",
    "normalize_frame",
    "parameter_log_records",
    "render_packet",
    "rx_log_record",
    "rx_log_text",
]
