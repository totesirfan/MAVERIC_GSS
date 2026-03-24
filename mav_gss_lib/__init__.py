"""
mav_gss_lib -- MAVERIC Ground Station Shared Library

Shared protocol and transport code for the MAVERIC CubeSat
ground station software suite (MAV_RX2, MAV_TX2).

Modules:
    protocol   -- Mission protocol: nodes, CSP, KISS, CRC-16, CRC-32C, command format, schema
    transport  -- ZMQ + PMT: PUB/SUB sockets, PDU send/receive

Author:  Irfan Annuar - USC ISI SERC
"""

from mav_gss_lib.protocol import (
    NODE_NAMES, NODE_IDS, PTYPE_NAMES, PTYPE_IDS, GS_NODE,
    node_label, ptype_label, resolve_node,
    TS_MIN_MS, TS_MAX_MS,
    crc16, crc32c, verify_csp_crc32,
    build_cmd_raw,
    try_parse_csp_v1, try_parse_command,
    fingerprint, clean_text, CSPConfig,
    load_command_defs, apply_schema, validate_args,
)

from mav_gss_lib.transport import (
    init_zmq_sub, init_zmq_pub, receive_pdu, send_pdu,
)