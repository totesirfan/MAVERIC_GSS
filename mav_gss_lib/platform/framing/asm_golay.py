"""
mav_gss_lib.platform.framing.asm_golay -- ASM+Golay Uplink Encoder (AX100 Mode 5)

Self-contained encoder for the ASM+Golay over-the-air frame format
used by the GomSpace AX100 radio in Mode 5 (AX100 Software Manual
§10.1.5).  Validated against both gr-satellites u482c_decode and
live AX100 hardware reception.

Over-the-air frame layout (Manual §10.1.5, always 312 bytes):
    [preamble 50B] [ASM 4B] [golay 3B] [data field 255B]

ASM sync word: 0x930B51DE
    The AX100 manual specifies 0xC9D08A7B as the register value
    (§10.1.2), but the AX5043 radio chip serializes bits LSB-first
    per byte, so the actual over-the-air bit pattern is 0x930B51DE
    (each byte bit-reversed).  Since gfsk_mod(do_unpack=True) sends
    bytes MSB-first, we use the over-the-air value directly — no
    bit reversal needed.  Validated against both gr-satellites'
    ax100_deframer and live AX100 hardware reception.

Golay(24,12) header — 3 bytes, 24 bits:
    Codeword format: [12 parity bits (upper)] [12 data bits (lower)]
    The 12-bit data field contains the frame length in the lower 8
    bits.  The U482C protocol defines bits 8-10 as optional flags
    (viterbi, scrambler, RS), but real AX100 TX packets leave these
    zero — the AX100 controls FEC via config parameters (csp_rs,
    csp_rand), not per-frame flags.  gr-satellites' ax100_deframer
    confirms this by hardcoding RS=1 and scrambler from config,
    ignoring the per-frame flag bits entirely.

Data field processing order (Manual §10.2):
    CSP packet → CRC-32C (via csp.wrap()) → RS(255,223) encode
    → CCSDS scramble → zero-pad to 255 bytes

Reed-Solomon: CCSDS conventional RS(255,223) via libfec/libcorrect.
    GF(2^8), primitive poly 0x187, fcr=112, prim=11, 32 parity bytes.
    Dynamically shortened: pad = 223 - payload_len.

CCSDS scrambler: polynomial h(x) = x^8+x^7+x^5+x^3+1 (§10.2.3).
    XORed over the RS codeword only (not preamble/ASM/Golay header).

Encoding: NRZ, MSB first (§10.1.5).  No G3RUH, no NRZI — those
    are Mode 6 (AX.25) only.  The gfsk_mod block handles GFSK
    modulation; this encoder just builds the baseband byte frame.

Configuration requirements:
    - AX100 must have mode=5, csp_rs=true, csp_rand=true
    - csp_crc: match GSS setting (gss.yml mission.config.csp.csp_crc)
    - After switching the AX100 to Mode 5, run 'config load 1' to
      force the AX5043 radio chip to reinitialize its RX registers

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import atexit as _atexit
import ctypes as _ctypes
import ctypes.util as _ctypes_util
import os as _os
import sys as _sys
from typing import Any

from mav_gss_lib.platform.framing.contract import Framer


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
ASM        = bytes([0x93, 0x0B, 0x51, 0xDE]) # Over-the-air ASM sync word (0x930B51DE)
RS_PARITY  = 32                              # Manual §10.2.2: RS(223,255), 32-byte parity
MAX_PAYLOAD = 223                            # max RS data capacity (255 - 32)


_rs_cache = {}

def _get_rs(pad: int) -> Any:
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


def rs_encode(payload: bytes) -> bytes:
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

def ccsds_scrambler_sequence(length: int) -> bytes:
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


# -- Golay(24,12) Encoder -----------------------------------------------------

# Generator matrix rows (Morelos-Zaragoza construction, matches gr-satellites
# golay24.c).  Each 24-bit row: upper 12 = identity bit, lower 12 = parity
# sub-matrix B(i).  The parity computation s = B * r (dot-product per row)
# is mathematically equivalent to XOR-of-selected-rows due to the anti-
# diagonal symmetry of B for the extended Golay code.
_GOLAY_H = [
    0x8008ed, 0x4001db, 0x2003b5, 0x100769, 0x80ed1, 0x40da3,
    0x20b47,  0x1068f,  0x8d1d,   0x4a3b,   0x2477,  0x1ffe,
]


def golay_encode(value_12bit: int) -> bytes:
    """Encode a 12-bit value into a 24-bit Golay(24,12) codeword.

    Codeword format: [12 parity bits (upper)] [12 data bits (lower)].
    gr-satellites u482c_decode extracts data from the lower 12 bits:
        frame_len = length_field & 0xff
        viterbi   = length_field & 0x100
        scrambler = length_field & 0x200
        rs        = length_field & 0x400"""
    r = value_12bit & 0xFFF
    s = 0
    for i in range(12):
        s <<= 1
        s |= (_GOLAY_H[i] & r).bit_count() % 2
    codeword = ((s & 0xFFF) << 12) | r
    return codeword.to_bytes(3, 'big')


# -- Frame Assembly -----------------------------------------------------------

def build_asm_golay_frame(csp_packet: bytes) -> bytes:
    """Build complete ASM+Golay over-the-air frame from a CSP packet.

    Produces a 312-byte frame ready for GFSK modulation via GNU Radio's
    gfsk_mod(do_unpack=True).  Bytes go directly to the modulator with
    no bit reversal — gfsk_mod sends MSB first, which produces the
    correct over-the-air bit pattern with ASM 0x930B51DE.

    Processing pipeline (Manual §10.2):
        CSP packet (with CRC-32C) → RS encode → CCSDS scramble
        → Golay header → ASM sync → preamble → 312-byte frame

    Args:
        csp_packet: CSP packet bytes (max 223B), including 4B CSP
                    header and 4B CRC-32C appended by CSPConfig.wrap().

    Output: 312-byte frame:
            [preamble 50B][ASM 4B][golay 3B][data field 255B]"""
    if not _GR_RS_OK:
        raise RuntimeError("libfec not found — cannot build ASM+Golay frame")
    plen = len(csp_packet)
    if plen > MAX_PAYLOAD:
        raise ValueError(f"CSP packet {plen}B exceeds RS capacity {MAX_PAYLOAD}B")

    # 1. RS encode (conventional, dynamically shortened)
    rs_codeword = rs_encode(csp_packet)     # plen + 32 bytes
    frame_len = len(rs_codeword)            # = plen + 32

    # 2. CCSDS scrambler (XOR with PN sequence, only frame_len bytes)
    pn = _PN_MAX[:frame_len]
    scrambled = (int.from_bytes(rs_codeword, 'big') ^ int.from_bytes(pn, 'big')).to_bytes(frame_len, 'big')

    # 3. Golay header — 12-bit data: plain frame_len, no flags.
    #    The U482C protocol defines bits 8-10 as viterbi/scrambler/RS flags,
    #    but real AX100 packets leave these zero.  FEC is controlled by config
    #    params (csp_rs, csp_rand), not per-frame flags.  gr-satellites'
    #    ax100_deframer hardcodes RS/scrambler from config, ignoring flags.
    golay_value = frame_len & 0xFF
    golay_field = golay_encode(golay_value)

    # 4. Assemble: [preamble][ASM][golay][data field zero-padded to 255B]
    data_field = scrambled.ljust(255, b'\x00')
    return PREAMBLE + ASM + golay_field + data_field


class AsmGolayFramer(Framer):
    """`Framer` adapter producing an AX100 Mode 5 ASM+Golay over-the-air frame.

    Output is fixed-size (312 bytes). `max_payload()` is the inner-payload
    cap imposed by RS(255,223). `overhead()` reports zero — fixed-output
    framers don't add a per-payload header that downstream layers see.
    """

    frame_label = "ASM+Golay"

    __slots__ = ()

    @property
    def available(self) -> bool:
        return _GR_RS_OK

    def frame(self, payload: bytes) -> bytes:
        if not _GR_RS_OK:
            raise RuntimeError(
                "ASM+Golay selected but libfec RS encoder is unavailable in this "
                "environment. Install libfec (e.g. `sudo apt install libfec-dev && "
                "sudo ldconfig`, `conda install -c ryanvolz libfec`, or build from "
                "https://github.com/quiet/libfec) or pick another framer."
            )
        if len(payload) > MAX_PAYLOAD:
            raise ValueError(
                f"command too large for ASM+Golay RS payload "
                f"({len(payload)}B > {MAX_PAYLOAD}B)"
            )
        return build_asm_golay_frame(payload)

    def overhead(self) -> int:
        return 0

    def max_payload(self) -> int | None:
        return MAX_PAYLOAD

    def log_fields(self) -> dict[str, Any]:
        return {}

    def log_line(self) -> str | None:
        return None
