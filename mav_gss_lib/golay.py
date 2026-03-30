"""
mav_gss_lib.golay -- ASM+Golay Uplink Encoder (AX100 Mode 5)

Self-contained encoder for the ASM+Golay over-the-air frame format
used by the GomSpace AX100 radio in Mode 5 (AX100 Software Manual
§10.1.5), validated against gr-satellites u482c_decode.

Frame layout (Manual §10.1.5, always 312 bytes):
    [preamble 50B] [ASM 4B] [golay 3B] [data field 255B]

The Golay 12-bit field encodes flags + frame length:
    bit 11:   unused
    bit 10:   RS flag (1 = Reed-Solomon enabled)
    bit 9:    scrambler flag (1 = CCSDS randomization enabled)
    bit 8:    viterbi flag (0 for Mode 5)
    bits 7-0: frame_len (= payload_len + 32 RS parity)

The data field contains the CCSDS-scrambled RS codeword, zero-padded
to 255 bytes.  The RS codeword is dynamically shortened:
RS(frame_len, payload_len) using conventional (non-CCSDS-dual-basis)
RS with pad = 255 - frame_len.

Encoding: NRZ, MSB first (Manual §10.1.5).
Scrambler polynomial: h(x) = x^8+x^7+x^5+x^3+1 (Manual §10.2.3).
ASM sync word: 0x930B51DE (bit-reversed form of Manual's 0xC9D08A7B,
    matching gr-satellites ax100_deframer convention).

Author:  Irfan Annuar - USC ISI SERC
"""

import atexit as _atexit
import ctypes as _ctypes
import ctypes.util as _ctypes_util
import os as _os
import sys as _sys


def _find_libfec():
    """Locate libfec shared library (libcorrect's compatibility shim)."""
    # 1. ctypes.util.find_library — checks standard search paths
    path = _ctypes_util.find_library("fec")
    if path:
        try:
            return _ctypes.CDLL(path)
        except OSError:
            pass
    # 2. Bare name — works when conda env sets DYLD_LIBRARY_PATH / LD_LIBRARY_PATH
    for name in ("libfec.dylib", "libfec.so"):
        try:
            return _ctypes.CDLL(name)
        except OSError:
            pass
    # 3. Conda prefix — handles cases where env vars aren't forwarded
    #    Check both the current env and the base (parent) conda installation,
    #    since libfec may only be installed in the base radioconda prefix.
    prefixes = []
    for p in (_os.environ.get("CONDA_PREFIX"), getattr(_sys, "prefix", "")):
        if p:
            prefixes.append(p)
            # Also check parent (base) conda install — e.g. radioconda/envs/gnuradio -> radioconda
            parent = _os.path.dirname(_os.path.dirname(p))
            if parent and parent not in prefixes:
                prefixes.append(parent)
    for prefix in prefixes:
        for name in ("libfec.dylib", "libfec.so"):
            candidate = _os.path.join(prefix, "lib", name)
            if _os.path.isfile(candidate):
                try:
                    return _ctypes.CDLL(candidate)
                except OSError:
                    pass
    return None


_libfec = _find_libfec()

if _libfec is not None:
    _libfec.init_rs_char.restype = _ctypes.c_void_p
    _libfec.init_rs_char.argtypes = [
        _ctypes.c_int, _ctypes.c_int, _ctypes.c_int,
        _ctypes.c_int, _ctypes.c_int, _ctypes.c_uint,
    ]
    _libfec.encode_rs_char.restype = None
    _libfec.encode_rs_char.argtypes = [
        _ctypes.c_void_p,
        _ctypes.POINTER(_ctypes.c_ubyte),
        _ctypes.POINTER(_ctypes.c_ubyte),
    ]
    _libfec.free_rs_char.argtypes = [_ctypes.c_void_p]
    _GR_RS_OK = True
else:
    _GR_RS_OK = False


# -- Constants ----------------------------------------------------------------

PREAMBLE   = b'\xAA' * 50                    # Manual Table 5.4: preamb=0xAA, preamblen=50
ASM        = bytes([0x93, 0x0B, 0x51, 0xDE]) # Manual §10.1.2: 0xC9D08A7B bit-reversed per byte
RS_PARITY  = 32                              # Manual §10.2.2: RS(223,255), 32-byte parity
MAX_PAYLOAD = 223                            # max RS data capacity (255 - 32)


_rs_cache = {}

def _get_rs(pad):
    """Get (or create and cache) an RS encoder handle for a given pad value."""
    rs = _rs_cache.get(pad)
    if rs is None:
        rs = _libfec.init_rs_char(8, 0x187, 112, 11, 32, pad)
        if not rs:
            raise RuntimeError("init_rs_char failed")
        _rs_cache[pad] = rs
    return rs

def _cleanup_rs_cache():
    for rs in _rs_cache.values():
        _libfec.free_rs_char(rs)
    _rs_cache.clear()

if _GR_RS_OK:
    _atexit.register(_cleanup_rs_cache)


def rs_encode(payload):
    """RS encode matching gr-satellites encode_rs_8 (Phil Karn FEC).

    Calls libfec's encode_rs_char directly via ctypes — same C function
    that gr-satellites wraps in a GNU Radio block, without the flowgraph
    overhead.  CCSDS conventional RS(255,223): GF(2^8) with primitive
    polynomial 0x187, fcr=112, prim=11, 32 parity bytes.

    Returns: payload + 32 parity bytes."""
    if not _GR_RS_OK:
        raise RuntimeError("libfec not found — cannot encode RS")
    plen = len(payload)
    if plen > MAX_PAYLOAD:
        raise ValueError(f"payload {plen}B exceeds RS capacity {MAX_PAYLOAD}B")

    pad = MAX_PAYLOAD - plen  # shortened code: 255 - 32 - plen
    rs = _get_rs(pad)
    msg = (_ctypes.c_ubyte * plen)(*payload)
    parity = (_ctypes.c_ubyte * 32)()
    _libfec.encode_rs_char(rs, msg, parity)
    return bytes(payload) + bytes(parity)


# -- CCSDS Synchronous Scrambler (matching gr-satellites randomizer.c) ---------

def ccsds_scrambler_sequence(length):
    """Generate CCSDS PN sequence matching gr-satellites ccsds_generate_sequence().

    Uses h(x) = x^8+x^7+x^5+x^3+1 with all-ones initial state.
    Generates one BIT per LFSR clock, packs 8 bits per output byte (MSB first)."""
    x = [1, 1, 1, 1, 1, 1, 1, 1, 1]  # 9-element shift register, all 1s
    seq = bytearray(length)
    for i in range(length * 8):
        seq[i >> 3] |= x[1] << (7 - (i & 7))     # output bit = x[1], pack MSB first
        x[0] = (x[8] ^ x[6] ^ x[4] ^ x[1]) & 1   # feedback taps
        x[1], x[2], x[3], x[4] = x[2], x[3], x[4], x[5]
        x[5], x[6], x[7], x[8] = x[6], x[7], x[8], x[0]
    return bytes(seq)

# Pre-compute max PN sequence (255 bytes, slice as needed).
_PN_MAX = ccsds_scrambler_sequence(255)


# -- Golay(24,12) Encoder (matching gr-satellites golay24.c) -------------------

# Generator matrix rows from gr-satellites (Morelos-Zaragoza construction).
# Each row is a 24-bit value; lower 12 bits are the B(i) parity sub-matrix.
_GOLAY_H = [
    0x8008ed, 0x4001db, 0x2003b5, 0x100769, 0x80ed1, 0x40da3,
    0x20b47,  0x1068f,  0x8d1d,   0x4a3b,   0x2477,  0x1ffe,
]


def golay_encode(value_12bit):
    """Encode a 12-bit value into a 24-bit Golay(24,12) codeword.

    Matches gr-satellites golay24.c encode_golay24() exactly.
    Format: [12 parity bits][12 data bits] (MSB first, 3 bytes)."""
    r = value_12bit & 0xFFF
    s = 0
    for i in range(12):
        s <<= 1
        s |= (_GOLAY_H[i] & r).bit_count() % 2
    codeword = ((s & 0xFFF) << 12) | r
    return codeword.to_bytes(3, 'big')


# -- Frame Assembly -----------------------------------------------------------

def build_asm_golay_frame(csp_packet):
    """Build complete ASM+Golay over-the-air frame from a CSP packet.

    Follows AX100 Manual §10.1.5 frame layout and §10.2 FEC order,
    validated against gr-satellites u482c_decode:
      - Golay 12-bit field: RS flag | scrambler flag | frame_len
      - RS: conventional (decode_rs_8), dynamically shortened
      - CCSDS scrambler on the RS codeword (§10.2.3)
      - Data field zero-padded to 255 bytes

    Input:  CSP packet (max 223B).
    Output: 312-byte frame ready for GFSK modulation.
            [preamble 50B][ASM 4B][golay 3B][data field 255B]"""
    if not _GR_RS_OK:
        raise RuntimeError("libfec not found — cannot build ASM+Golay frame")
    plen = len(csp_packet)
    if plen > MAX_PAYLOAD:
        raise ValueError(f"CSP packet {plen}B exceeds RS capacity {MAX_PAYLOAD}B")

    # RS encode (conventional, shortened)
    rs_codeword = rs_encode(csp_packet)     # plen + 32 bytes
    frame_len = len(rs_codeword)            # = plen + 32

    # CCSDS scrambler (only frame_len bytes) — bulk int XOR is ~13x faster than per-byte loop
    pn = _PN_MAX[:frame_len]
    scrambled = (int.from_bytes(rs_codeword, 'big') ^ int.from_bytes(pn, 'big')).to_bytes(frame_len, 'big')

    # Golay field: [unused 1][rs 1][scrambler 1][viterbi 1][frame_len 8]
    golay_value = (1 << 10) | (1 << 9) | (frame_len & 0xFF)
    golay_field = golay_encode(golay_value)

    # Pad data field to 255 bytes (Manual §10.1.5: [Sync][Golay][Data Field])
    data_field = scrambled.ljust(255, b'\x00')

    return PREAMBLE + ASM + golay_field + data_field
