"""
mav_gss_lib.golay -- Compatibility facade

Canonical location: mav_gss_lib.protocols.golay
This module re-exports all public symbols for backward compatibility.
"""

from mav_gss_lib.protocols.golay import *  # noqa: F401,F403
from mav_gss_lib.protocols.golay import (  # noqa: F401
    MAX_PAYLOAD,
    build_asm_golay_frame,
    rs_encode,
    golay_encode,
    ccsds_scrambler_sequence,
    _GR_RS_OK,
)
