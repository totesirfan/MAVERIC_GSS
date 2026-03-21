"""
mav_gss_lib -- MAVERIC Ground Station Shared Library

Shared protocol, display, and transport code for the MAVERIC CubeSat
ground station software suite (MAV_RX, MAV_TX).

Modules:
    protocol   -- Mission protocol: nodes, CSP, KISS, CRC, command format
    display    -- Terminal UI: colors, box drawing, text formatting
    transport  -- ZMQ + PMT: PUB/SUB sockets, PDU send/receive

Author:  Irfan Annuar - USC ISI SERC
"""

from mav_gss_lib.protocol import (
    NODE_NAMES, NODE_IDS, PTYPE_NAMES, PTYPE_IDS, GS_NODE,
    node_label, ptype_label, resolve_node,
    FEND, FESC, TFEND, TFESC,
    TS_MIN_MS, TS_MAX_MS,
    crc_calc, build_cmd_raw, kiss_wrap, build_kiss_cmd,
    try_parse_csp_v1, try_parse_command, try_extract_timestamp,
    fingerprint, clean_text, CSPConfig,
)

from mav_gss_lib.display import (
    C, BOX_W, INN_W, TOP, MID, BOT,
    strip_ansi, row, wrap_ascii, wrap_hex,
    banner, info_line, info_line_dim, separator,
)

from mav_gss_lib.transport import (
    init_zmq_sub, init_zmq_pub, receive_pdu, send_pdu,
)