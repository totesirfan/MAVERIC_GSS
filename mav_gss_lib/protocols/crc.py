"""
mav_gss_lib.protocols.crc -- CRC-16 XMODEM & CRC-32C (Castagnoli)

CRC-16 XMODEM: general-purpose checksum used in command wire formats.
CRC-32C (Castagnoli): used in CSP v1 packet integrity.

Both use C-accelerated crcmod for performance.
"""

try:
    import crcmod.predefined as _crcmod
except ImportError:
    raise ImportError(
        "crcmod is required for CRC computation but not installed. "
        "Install with: pip install crcmod   (or: conda install crcmod)"
    ) from None

_crc16_fn = _crcmod.mkCrcFun('xmodem')
_crc32c_fn = _crcmod.mkCrcFun('crc-32c')


def crc16(data: bytes) -> int:
    """CRC-16 XMODEM checksum (C-accelerated via crcmod)."""
    return _crc16_fn(data)


def crc32c(data: bytes) -> int:
    """CRC-32C (Castagnoli) checksum for CSP v1 packet integrity (C-accelerated via crcmod)."""
    return _crc32c_fn(data)


def verify_csp_crc32(inner_payload: bytes) -> tuple[bool | None, int | None, int | None]:
    """Verify CRC-32C over a complete CSP packet (header + data + CRC-32C).

    Last 4 bytes are the received CRC-32C (big-endian); computed over
    everything preceding them.

    Returns (is_valid, received_crc, computed_crc).
    Returns (None, None, None) if payload is too short to contain a CRC."""
    if len(inner_payload) < 8:  # need at least 4B CSP header + 4B CRC
        return None, None, None
    received = int.from_bytes(inner_payload[-4:], 'big')
    computed = crc32c(inner_payload[:-4])
    return received == computed, received, computed
