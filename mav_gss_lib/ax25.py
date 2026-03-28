"""
mav_gss_lib.ax25 -- AX.25 Uplink Encoder (AX100 Mode 6)

Self-contained encoder that replicates the GNU Radio AX.25 TX chain:
    HDLC framer → G3RUH scrambler → NRZI encoder → bit packing

This allows AX.25 frames to be sent through the same simple flowgraph
used for ASM+Golay (PDU → tagged stream → GFSK mod), eliminating the
need for separate GNU Radio blocks.

HDLC frame layout:
    [preamble flags] [bit-stuffed payload + FCS] [postamble flags]

Flag byte: 0x7E (01111110)
FCS: CRC-16-CCITT (init=0xFFFF, reflected poly=0x8408, final invert)
Bit order: LSB first per byte
Encoding: G3RUH scrambled, NRZI encoded

Author:  Irfan Annuar - USC ISI SERC
"""


# -- CRC-16-CCITT (HDLC FCS) -------------------------------------------------

def _crc_ccitt(data):
    """CRC-16-CCITT as used in HDLC/X.25 FCS.

    Init: 0xFFFF, reflected polynomial 0x8408, final XOR 0xFFFF.
    Returns 16-bit CRC value."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x8408
            else:
                crc >>= 1
    return crc ^ 0xFFFF


# -- HDLC Framing -------------------------------------------------------------

_FLAG_BITS = [0, 1, 1, 1, 1, 1, 1, 0]   # 0x7E LSB first


def _bytes_to_bits_lsb(data):
    """Convert bytes to bit list, LSB first per byte."""
    bits = []
    for byte in data:
        for i in range(8):
            bits.append((byte >> i) & 1)
    return bits


def _bit_stuff(bits):
    """Insert a 0 bit after every run of five consecutive 1s."""
    out = []
    ones = 0
    for b in bits:
        out.append(b)
        if b == 1:
            ones += 1
            if ones == 5:
                out.append(0)
                ones = 0
        else:
            ones = 0
    return out


def hdlc_frame(payload, preamble_bytes=20, postamble_bytes=20):
    """HDLC-frame a payload, matching gr-satellites hdlc_framer.

    Returns a list of bits (0/1 ints): preamble flags + bit-stuffed
    (payload + FCS) + postamble flags.

    Parameters match the GNU Radio block: preamble_bytes=20, postamble_bytes=20."""
    # Compute FCS over raw payload bytes
    fcs = _crc_ccitt(payload)
    frame_data = payload + fcs.to_bytes(2, 'little')

    # Convert to bits (LSB first) and bit-stuff
    data_bits = _bytes_to_bits_lsb(frame_data)
    stuffed = _bit_stuff(data_bits)

    # Assemble: preamble flags + stuffed data + postamble flags
    preamble = _FLAG_BITS * preamble_bytes
    postamble = _FLAG_BITS * postamble_bytes
    return preamble + stuffed + postamble


# -- G3RUH Scrambler ----------------------------------------------------------

def g3ruh_scramble(bits):
    """Multiplicative scrambler matching digital.scrambler_bb(0x21, 0x0, 16).

    Implements the G3RUH polynomial x^17 + x^12 + 1 using GNU Radio's
    Fibonacci LFSR (see gnuradio/digital/lfsr.h next_bit_scramble):
        output  = register LSB
        new_bit = parity(register & mask) XOR input
        register shifts right, new_bit enters at bit reg_len (bit 16)

    The effective register is 17 bits (0–16), with mask 0x21 giving
    feedback taps at bits 0 and 5 (delays 17 and 12 from input)."""
    reg = 0x00000  # seed (17 effective bits)
    mask = 0x21
    reg_len = 16
    out = []
    for b in bits:
        output = reg & 1
        newbit = (bin(reg & mask).count('1') % 2) ^ (b & 1)
        reg = (reg >> 1) | (newbit << reg_len)
        out.append(output)
    return out


# -- NRZI Encoder --------------------------------------------------------------

def nrzi_encode(bits):
    """NRZI encoder matching gr-satellites nrzi_encode.

    Data 0 → toggle output state.
    Data 1 → keep output state.
    Initial state: 0."""
    state = 0
    out = []
    for b in bits:
        if b == 0:
            state ^= 1
        out.append(state)
    return out


# -- Bit Packing ---------------------------------------------------------------

def _pack_bits(bits):
    """Pack a bit list into bytes (MSB first, matching pack_k_bits + do_unpack).

    GFSK mod with do_unpack=True unpacks bytes MSB first, so we pack MSB first
    to preserve bit order.  Trailing bits that don't fill a full byte are
    discarded, matching GNU Radio's pack_k_bits_bb(8) behaviour."""
    out = bytearray()
    for i in range(0, len(bits) - 7, 8):
        byte = 0
        for j in range(8):
            byte = (byte << 1) | bits[i + j]
        out.append(byte)
    return bytes(out)


# -- Top-Level Builder ---------------------------------------------------------

def build_ax25_gfsk_frame(ax25_packet):
    """Build complete AX.25 over-the-air frame from an AX.25-wrapped CSP packet.

    Replicates the GNU Radio AX.25 TX chain:
        HDLC framer → G3RUH scrambler → NRZI encoder → pack bits

    Input:  AX.25 packet (header + CSP payload) from AX25Config.wrap().
    Output: Frame bytes ready for GFSK mod with do_unpack=True."""
    bits = hdlc_frame(ax25_packet)
    bits = g3ruh_scramble(bits)
    bits = nrzi_encode(bits)
    return _pack_bits(bits)
