"""
mav_gss_lib.parsing -- RX Packet Processing Pipeline

Stateful packet processing: takes raw PDU bytes from ZMQ and returns
structured packet records for display and logging.

No UI, no I/O, no threads -- pure data transformation.

Author:  Irfan Annuar - USC ISI SERC
"""

import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime

from mav_gss_lib.mission_adapter import load_mission_adapter
from mav_gss_lib.textutil import clean_text

DUP_WINDOW = 1.0  # seconds -- only flag as duplicate if same fingerprint seen within this window


@dataclass
class Packet:
    """Structured record for a received packet."""
    pkt_num: int = 0
    gs_ts: str = ""
    gs_ts_short: str = ""
    frame_type: str = ""
    raw: bytes = b""
    inner_payload: bytes = b""
    stripped_hdr: str | None = None
    mission_data: dict = field(default_factory=dict)
    text: str = ""
    warnings: list = field(default_factory=list)
    delta_t: float | None = None
    is_dup: bool = False
    is_uplink_echo: bool = False
    is_unknown: bool = False
    unknown_num: int | None = None



class RxPipeline:
    """Stateful RX packet processing pipeline.

    Holds all packet-tracking state internally. Call process(meta, raw)
    for each received PDU -- counters update automatically.
    """

    def __init__(self, adapter, tx_freq_map=None, max_seen_fps=10_000):
        self.adapter = adapter   # public: tests read pipeline.adapter
        self.tx_freq_map = tx_freq_map or {}
        self.max_seen_fps = max_seen_fps

        # Counters and state
        self.seen_fps = OrderedDict()
        self.pkt_times = deque(maxlen=3600)
        self.total_count = 0
        self.packet_count = 0
        self.unknown_count = 0
        self.uplink_echo_count = 0
        self.last_arrival = None
        self.frequency = None

    @classmethod
    def from_adapter(cls, adapter, tx_freq_map=None, max_seen_fps=10_000):
        return cls(adapter, tx_freq_map=tx_freq_map, max_seen_fps=max_seen_fps)

    @classmethod
    def from_cmd_defs(cls, cmd_defs, tx_freq_map=None, max_seen_fps=10_000):
        """Legacy: build adapter from a cmd_defs dict. Overrides adapter.cmd_defs
        after construction so missions with init_mission hooks don't silently
        drop the caller's dict."""
        from mav_gss_lib.config import load_gss_config
        cfg = load_gss_config()
        adapter = load_mission_adapter(cfg)
        adapter.cmd_defs = cmd_defs
        return cls(adapter, tx_freq_map=tx_freq_map, max_seen_fps=max_seen_fps)

    def reset_counts(self):
        """Reset counters for a new log session."""
        self.total_count = 0
        self.packet_count = 0
        self.unknown_count = 0
        self.uplink_echo_count = 0
        self.seen_fps.clear()
        self.pkt_times.clear()

    def process(self, meta, raw):
        """Process one raw PDU into a Packet record.

        Returns a Packet instance. Internal counters are updated in place.
        """
        now = time.time()
        delta_t = (now - self.last_arrival) if self.last_arrival is not None else None
        now_dt = datetime.now().astimezone()

        # Frame detection and normalization
        frame_type = self.adapter.detect_frame_type(meta)
        self._update_frequency(meta)
        inner_payload, stripped_hdr, warnings = self.adapter.normalize_frame(frame_type, raw)

        parsed = self.adapter.parse_packet(inner_payload, warnings)
        warnings = parsed.warnings

        # Classification
        is_dup = self._check_duplicate(parsed, now)
        is_unknown, unknown_num = self._classify_unknown(parsed)
        is_uplink_echo = self.adapter.is_uplink_echo(parsed)

        # Monotonic packet number — all packets get a unique sequential number
        self.total_count += 1

        # Rate tracking — exclude uplink echoes and unknown packets
        self._update_rate(now, is_uplink_echo, is_unknown)
        self.last_arrival = now

        # Manual f-string formatting — avoids strftime C locale overhead
        tz = now_dt.tzname() or ""
        gs_ts = f"{now_dt.year:04d}-{now_dt.month:02d}-{now_dt.day:02d} {now_dt.hour:02d}:{now_dt.minute:02d}:{now_dt.second:02d} {tz}"
        gs_ts_short = f"{now_dt.hour:02d}:{now_dt.minute:02d}:{now_dt.second:02d}"

        return Packet(
            pkt_num=self.total_count,
            gs_ts=gs_ts,
            gs_ts_short=gs_ts_short,
            frame_type=frame_type,
            raw=raw,
            inner_payload=inner_payload,
            stripped_hdr=stripped_hdr,
            mission_data=parsed.mission_data,
            text=clean_text(inner_payload),
            warnings=warnings,
            delta_t=delta_t,
            is_dup=is_dup,
            is_uplink_echo=is_uplink_echo,
            is_unknown=is_unknown,
            unknown_num=unknown_num,
        )

    # -- Private helpers -------------------------------------------------------

    def _update_frequency(self, meta):
        tx_name = str(meta.get("transmitter", ""))
        freq = self.tx_freq_map.get(tx_name)
        if freq is not None:
            self.frequency = freq

    def _check_duplicate(self, parsed, now):
        """Check for duplicate using a mission-provided fingerprint."""
        fp = self.adapter.duplicate_fingerprint(parsed)
        if fp is None:
            return False
        prev = self.seen_fps.get(fp)
        is_dup = prev is not None and (now - prev) < DUP_WINDOW
        self.seen_fps[fp] = now
        self.seen_fps.move_to_end(fp)
        if len(self.seen_fps) > self.max_seen_fps:
            for _ in range(self.max_seen_fps // 5):
                self.seen_fps.popitem(last=False)
        return is_dup

    def _classify_unknown(self, parsed):
        """Classify packet as unknown or known using the adapter, update counters."""
        is_unknown = self.adapter.is_unknown_packet(parsed)
        if is_unknown:
            self.unknown_count += 1
            return True, self.unknown_count
        self.packet_count += 1
        return False, None

    def _update_rate(self, now, is_uplink_echo, is_unknown):
        """Track packet rate, excluding uplink echoes and unknown packets."""
        if not is_uplink_echo and not is_unknown:
            self.pkt_times.append(now)
        while self.pkt_times and self.pkt_times[0] <= now - 60.0:
            self.pkt_times.popleft()


def build_rx_log_record(pkt, version, meta, adapter, *, operator="", station=""):
    """Build a JSONL log record from a Packet.

    Platform envelope: stable fields shared by all missions, plus operator
    and station stamps so merged logs from multiple laptops self-identify.
    Mission block: adapter-provided opaque payload.
    Rendering: full _rendering for replay passthrough.
    """
    from dataclasses import asdict

    record = {
        "v": version, "pkt": pkt.pkt_num, "gs_ts": pkt.gs_ts,
        "operator": operator, "station": station,
        "frame_type": pkt.frame_type,
        "tx_meta": str(meta.get("transmitter", "")),
        "raw_hex": pkt.raw.hex(), "payload_hex": pkt.inner_payload.hex(),
        "raw_len": len(pkt.raw), "payload_len": len(pkt.inner_payload),
        "duplicate": pkt.is_dup,
        "uplink_echo": pkt.is_uplink_echo,
        "unknown": pkt.is_unknown,
    }
    if pkt.delta_t is not None:
        record["delta_t"] = round(pkt.delta_t, 4)

    # Full rendering payload for replay passthrough
    protocol_blocks = [asdict(b) for b in adapter.protocol_blocks(pkt)]
    integrity_blocks = [asdict(b) for b in adapter.integrity_blocks(pkt)]
    record["_rendering"] = {
        "row": adapter.packet_list_row(pkt),
        "detail_blocks": adapter.packet_detail_blocks(pkt),
        "protocol_blocks": protocol_blocks,
        "integrity_blocks": integrity_blocks,
    }

    # Top-level copies for direct access by log viewer
    record["protocol_blocks"] = protocol_blocks
    record["integrity_blocks"] = integrity_blocks

    # Mission-specific payload — opaque to platform
    mission_data = adapter.build_log_mission_data(pkt)
    if mission_data:
        record["mission"] = mission_data

    return record
