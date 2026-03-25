"""
mav_gss_lib.parsing -- RX Packet Processing Pipeline

Stateless packet processing: takes raw PDU bytes from ZMQ and returns
a structured packet record dict for display and logging.

No UI, no I/O, no threads -- pure data transformation.

Author:  Irfan Annuar - USC ISI SERC
"""

import time
from datetime import datetime

import mav_gss_lib.protocol as protocol
from mav_gss_lib.protocol import (
    detect_frame_type, normalize_frame,
    try_parse_csp_v1, try_parse_command, apply_schema,
    verify_csp_crc32, clean_text,
)


def process_rx_packet(meta, raw, cmd_defs, seen_fps, tx_freq_map,
                      last_arrival, packet_count, unknown_count,
                      uplink_echo_count, pkt_times, max_seen_fps=10_000):
    """Process one raw PDU into a structured packet record.

    Args:
        meta:               gr-satellites metadata dict
        raw:                raw PDU bytes
        cmd_defs:           loaded command schema dict
        seen_fps:           OrderedDict for duplicate detection (mutated in place)
        tx_freq_map:        transmitter→frequency map
        last_arrival:       timestamp of previous packet (or None)
        packet_count:       current valid packet count
        unknown_count:      current unknown packet count
        uplink_echo_count:  current uplink echo count
        pkt_times:          list of recent packet timestamps (mutated in place)
        max_seen_fps:       max fingerprint cache size

    Returns:
        (pkt_record, counters) where counters is a dict with updated:
            packet_count, unknown_count, uplink_echo_count, frequency, last_arrival
    """
    now = time.time()
    delta_t = (now - last_arrival) if last_arrival is not None else None
    gs_ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    gs_ts_short = datetime.now().strftime("%H:%M:%S")

    # Frame detection and normalization
    frame_type = detect_frame_type(meta)
    tx_name = str(meta.get("transmitter", ""))
    frequency = tx_freq_map.get(tx_name)

    inner_payload, stripped_hdr, warnings = normalize_frame(frame_type, raw)
    csp, csp_plausible = try_parse_csp_v1(inner_payload)

    # Command parsing
    cmd, cmd_tail = (None, None)
    ts_result = None
    if len(inner_payload) > 4:
        cmd, cmd_tail = try_parse_command(inner_payload[4:])
        if cmd:
            apply_schema(cmd, cmd_defs)

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
        is_dup = fp in seen_fps
        if is_dup:
            seen_fps.move_to_end(fp)
        else:
            seen_fps[fp] = None
        if len(seen_fps) > max_seen_fps:
            for _ in range(max_seen_fps // 5):
                seen_fps.popitem(last=False)

    # Rate tracking
    pkt_times.append(now)
    pkt_times[:] = [t for t in pkt_times if t > now - 60.0]

    # Unknown packet detection
    is_unknown = cmd is None
    unknown_num = None
    if is_unknown:
        unknown_count += 1
        unknown_num = unknown_count
    else:
        packet_count += 1

    # Uplink echo detection
    is_uplink_echo = bool(cmd and (
        cmd.get("src") == protocol.GS_NODE
        or (cmd.get("dest") != protocol.GS_NODE and cmd.get("echo") != protocol.GS_NODE)
    ))
    if is_uplink_echo:
        uplink_echo_count += 1

    pkt_record = {
        "pkt_num": packet_count,
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

    counters = {
        "packet_count": packet_count,
        "unknown_count": unknown_count,
        "uplink_echo_count": uplink_echo_count,
        "frequency": frequency,
        "last_arrival": now,
    }

    return pkt_record, counters


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
