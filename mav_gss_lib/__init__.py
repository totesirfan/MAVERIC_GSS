"""
mav_gss_lib -- MAVERIC Ground Station Shared Library

Shared protocol and transport code for the MAVERIC CubeSat
ground station software suite (MAV_RX2, MAV_TX2).

Modules:
    protocol   -- Mission protocol: nodes, CSP, KISS, CRC-16, CRC-32C, command format, schema
    transport  -- ZMQ + PMT: PUB/SUB sockets, PDU send/receive
    parsing    -- RX packet processing pipeline
    logging    -- Session logging (JSONL + text)
    config     -- Shared config loader + config command handlers

Author:  Irfan Annuar - USC ISI SERC
"""

from mav_gss_lib.protocol import (
    NODE_NAMES, NODE_IDS, PTYPE_NAMES, PTYPE_IDS, GS_NODE,
    init_nodes, node_name, ptype_name, node_label, ptype_label, resolve_node,
    TS_MIN_MS, TS_MAX_MS,
    crc16, crc32c, verify_csp_crc32,
    build_cmd_raw,
    try_parse_csp_v1, try_parse_command,
    detect_frame_type, normalize_frame, parse_cmd_line,
    clean_text, format_arg_value, CSPConfig,
    load_command_defs, apply_schema, validate_args,
)

from mav_gss_lib.transport import (
    init_zmq_sub, init_zmq_pub, receive_pdu, send_pdu,
)

from mav_gss_lib.parsing import RxPipeline, build_rx_log_record

from mav_gss_lib.logging import SessionLog, TXLog