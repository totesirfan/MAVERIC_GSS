"""
mav_gss_lib.parsing -- RX Packet Processing Pipeline

Stateful packet processing: takes raw PDU bytes from ZMQ and returns
structured packet records for display and logging.

No UI, no I/O, no threads -- pure data transformation.

Author:  Irfan Annuar - USC ISI SERC
"""

import time
from collections import OrderedDict, deque
from datetime import datetime

import mav_gss_lib.protocol as protocol
from mav_gss_lib.protocol import (
    detect_frame_type, normalize_frame,
    try_parse_csp_v1, try_parse_command, apply_schema,
    verify_csp_crc32, clean_text,
)


class RxPipeline:
    """Stateful RX packet processing pipeline.

    Holds all packet-tracking state internally. Call process(meta, raw)
    for each received PDU -- counters update automatically.
    """

    def __init__(self, cmd_defs, tx_freq_map, max_seen_fps=10_000):
        self.cmd_defs = cmd_defs
        self.tx_freq_map = tx_freq_map
        self.max_seen_fps = max_seen_fps

        # Counters and state
        self.seen_fps = OrderedDict()
        self.pkt_times = deque(maxlen=600)
        self.packet_count = 0
        self.unknown_count = 0
        self.uplink_echo_count = 0
        self.last_arrival = None
        self.frequency = None

    def process(self, meta, raw):
        """Process one raw PDU into a structured packet record.

        Returns a pkt_record dict. Internal counters are updated in place.
        """
        now = time.time()
        delta_t = (now - self.last_arrival) if self.last_arrival is not None else None
        gs_ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        gs_ts_short = datetime.now().strftime("%H:%M:%S")

        # Frame detection and normalization
        frame_type = detect_frame_type(meta)
        tx_name = str(meta.get("transmitter", ""))
        freq = self.tx_freq_map.get(tx_name)
        if freq is not None:
            self.frequency = freq

        inner_payload, stripped_hdr, warnings = normalize_frame(frame_type, raw)
        csp, csp_plausible = try_parse_csp_v1(inner_payload)

        # Command parsing
        cmd, cmd_tail = (None, None)
        ts_result = None
        if len(inner_payload) > 4:
            cmd, cmd_tail = try_parse_command(inner_payload[4:])
            if cmd:
                apply_schema(cmd, self.cmd_defs)

        # CRC-32C verification
        crc_valid, crc_rx, crc_comp = (None, None, None)
        if cmd and cmd.get("csp_crc32") is not None:
            crc_valid, crc_rx, crc_comp = verify_csp_crc32(inner_payload)
            if crc_valid is False:
                warnings.append(f"CRC-32C mismatch: rx 0x{crc_rx:08x} != computed 0x{crc_comp:08x}")
        crc_status = {"csp_crc32_valid": crc_valid, "csp_crc32_rx": crc_rx, "csp_crc32_comp": crc_comp}

        # Satellite timestamp
        if cmd and cmd.get("sat_time"):
            ts_result = cmd["sat_time"]

        text = clean_text(inner_payload)

        # Duplicate detection using satellite CRC-16 + CRC-32C
        is_dup = False
        fp = None
        if cmd and cmd.get("crc") is not None and cmd.get("csp_crc32") is not None:
            fp = (cmd["crc"], cmd["csp_crc32"])
            is_dup = fp in self.seen_fps
            if is_dup:
                self.seen_fps.move_to_end(fp)
            else:
                self.seen_fps[fp] = None
            if len(self.seen_fps) > self.max_seen_fps:
                for _ in range(self.max_seen_fps // 5):
                    self.seen_fps.popitem(last=False)

        # Unknown packet detection
        is_unknown = cmd is None
        unknown_num = None
        if is_unknown:
            self.unknown_count += 1
            unknown_num = self.unknown_count
        else:
            self.packet_count += 1

        # Uplink echo detection
        is_uplink_echo = bool(cmd and (
            cmd.get("src") == protocol.GS_NODE
            or (cmd.get("dest") != protocol.GS_NODE and cmd.get("echo") != protocol.GS_NODE)
        ))
        if is_uplink_echo:
            self.uplink_echo_count += 1

        # Rate tracking — exclude uplink echoes from pkt/min
        if not is_uplink_echo:
            self.pkt_times.append(now)
        while self.pkt_times and self.pkt_times[0] <= now - 60.0:
            self.pkt_times.popleft()

        self.last_arrival = now

        return {
            "pkt_num": self.packet_count,
            "gs_ts": gs_ts,
            "gs_ts_short": gs_ts_short,
            "frame_type": frame_type,
            "raw": raw,
            "inner_payload": inner_payload,
            "stripped_hdr": stripped_hdr,
            "csp": csp,
            "csp_plausible": csp_plausible,
            "ts_result": ts_result,
            "cmd": cmd,
            "cmd_tail": cmd_tail,
            "text": text,
            "warnings": warnings,
            "delta_t": delta_t,
            "crc_status": crc_status,
            "is_dup": is_dup,
            "is_uplink_echo": is_uplink_echo,
            "is_unknown": is_unknown,
            "unknown_num": unknown_num,
        }


def build_rx_log_record(pkt, version, meta):
    """Build a JSONL log record dict from a packet record.

    Separates log serialization from packet processing so the main
    loop doesn't need to know the log schema."""
    cmd = pkt["cmd"]
    log_record = {
        "v": version, "pkt": pkt["pkt_num"], "gs_ts": pkt["gs_ts"],
        "frame_type": pkt["frame_type"],
        "tx_meta": str(meta.get("transmitter", "")),
        "raw_hex": pkt["raw"].hex(), "payload_hex": pkt["inner_payload"].hex(),
        "raw_len": len(pkt["raw"]), "payload_len": len(pkt["inner_payload"]),
        "duplicate": pkt["is_dup"],
        "uplink_echo": pkt["is_uplink_echo"],
        "unknown": pkt["is_unknown"],
    }
    if pkt["delta_t"] is not None:
        log_record["delta_t"] = round(pkt["delta_t"], 4)
    if pkt["csp"]:
        log_record["csp_candidate"] = pkt["csp"]
        log_record["csp_plausible"] = pkt["csp_plausible"]
    if pkt["ts_result"]:
        log_record["sat_ts_ms"] = pkt["ts_result"][2]
    crc_status = pkt["crc_status"]
    if crc_status["csp_crc32_valid"] is not None:
        log_record["csp_crc32"] = {
            "valid": crc_status["csp_crc32_valid"],
            "received": f"0x{crc_status['csp_crc32_rx']:08x}",
        }
    if cmd:
        cmd_log = {
            "src": cmd["src"], "dest": cmd["dest"],
            "echo": cmd["echo"], "pkt_type": cmd["pkt_type"],
            "cmd_id": cmd["cmd_id"], "crc": cmd["crc"],
            "crc_valid": cmd.get("crc_valid"),
        }
        if cmd.get("schema_match"):
            typed_log = {}
            for ta in cmd["typed_args"]:
                if ta["type"] == "epoch_ms" and isinstance(ta["value"], dict):
                    typed_log[ta["name"]] = ta["value"]["ms"]
                else:
                    typed_log[ta["name"]] = ta["value"]
            cmd_log["args"] = typed_log
            if cmd["extra_args"]:
                cmd_log["extra_args"] = cmd["extra_args"]
        else:
            cmd_log["args"] = cmd["args"]
            if cmd.get("schema_warning"):
                cmd_log["schema_warning"] = cmd["schema_warning"]
        log_record["cmd"] = cmd_log
        if pkt["cmd_tail"]:
            log_record["tail_hex"] = pkt["cmd_tail"].hex()

    return log_record
