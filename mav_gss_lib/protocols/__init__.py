"""
mav_gss_lib.protocols -- Reusable CubeSat Protocol-Family Support

Protocol-family primitives shared across missions:
    crc          -- CRC-16 XMODEM, CRC-32C Castagnoli
    csp          -- CSP v1 header, KISS framing, CSPConfig
    ax25         -- AX.25 encoder, AX25Config
    golay        -- ASM+Golay encoder (AX100 Mode 5)
    frame_detect -- Frame type detection and normalization
"""

from mav_gss_lib.protocols.crc import crc16, crc32c, verify_csp_crc32
from mav_gss_lib.protocols.csp import (
    FEND, FESC, TFEND, TFESC, kiss_wrap,
    try_parse_csp_v1, CSPConfig,
)
from mav_gss_lib.protocols.ax25 import (
    AX25Config, build_ax25_gfsk_frame,
)
from mav_gss_lib.protocols.frame_detect import detect_frame_type, normalize_frame
