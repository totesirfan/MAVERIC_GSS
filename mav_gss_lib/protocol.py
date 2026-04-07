"""
mav_gss_lib.protocol -- Platform Utilities

Generic text utilities used across the platform.
All protocol-family and mission re-exports have been removed (Phase 11).
Import directly from canonical locations:
  - mav_gss_lib.protocols.*                   (CRC, CSP, KISS, AX.25)
  - mav_gss_lib.missions.maveric.wire_format  (nodes, commands, schema)

Author:  Irfan Annuar - USC ISI SERC
"""

_CLEAN_TABLE = bytearray(0xB7 for _ in range(256))  # middle dot
for _b in range(32, 127):
    _CLEAN_TABLE[_b] = _b
_CLEAN_TABLE = bytes(_CLEAN_TABLE)


def clean_text(data: bytes) -> str:
    """Printable ASCII representation with non-printable bytes as middle dot."""
    return data.translate(_CLEAN_TABLE).decode('latin-1')
