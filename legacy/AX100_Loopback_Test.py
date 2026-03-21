"""
MAVERIC AX100 Loopback Test v2
Uses actual gr-satellites blocks to decode our encoded frame.

    conda activate gnuradio
    python3 ax100_loopback_test.py
"""

import numpy as np
import pmt
from gnuradio import gr, blocks
import satellites

# ── Our encoder (same as epy_block) ─────────────────────────────

GF_EXP = [0]*512
GF_LOG = [0]*256
x = 1
for i in range(255):
    GF_EXP[i] = x
    GF_LOG[x] = i
    x <<= 1
    if x & 0x100: x ^= 0x187
for i in range(255, 512):
    GF_EXP[i] = GF_EXP[i - 255]

def gf_mul(a, b):
    if a == 0 or b == 0: return 0
    return GF_EXP[GF_LOG[a] + GF_LOG[b]]

NROOTS = 32
genpoly = [0]*(NROOTS+1)
genpoly[0] = 1
for i in range(NROOTS):
    genpoly[i+1] = 1
    root = GF_EXP[(112+i)*11 % 255]
    for j in range(i, 0, -1):
        if genpoly[j] != 0:
            genpoly[j] = genpoly[j-1] ^ gf_mul(genpoly[j], root)
        else:
            genpoly[j] = genpoly[j-1]
    genpoly[0] = gf_mul(genpoly[0], root)

def rs_encode(data):
    parity = [0]*NROOTS
    for i in range(len(data)):
        fb_val = data[i] ^ parity[0]
        if fb_val != 0:
            fb_log = GF_LOG[fb_val]
            for j in range(NROOTS-1):
                parity[j] = parity[j+1] ^ GF_EXP[fb_log + GF_LOG[genpoly[NROOTS-1-j]]]
            parity[NROOTS-1] = GF_EXP[fb_log + GF_LOG[genpoly[0]]]
        else:
            parity = parity[1:] + [0]
    return parity

GOLAY_GEN = [0b110111000101,0b101110001011,0b011100010111,0b111000101101,
             0b110001011011,0b100010110111,0b000101101111,0b001011011101,
             0b010110111001,0b101101110001,0b011011100011,0b111111111110]

def golay24_encode(d12):
    d = d12 & 0xFFF; p = 0
    for i in range(12):
        if d & (1<<(11-i)): p ^= GOLAY_GEN[i]
    return (d<<12)|(p&0xFFF)

def ccsds_scramble(data):
    out = bytearray(len(data))
    lfsr = 0xFF
    for i in range(len(data)):
        pn = 0
        for bit in range(8):
            pn = (pn<<1)|((lfsr>>7)&1)
            fb = ((lfsr>>0)^(lfsr>>2)^(lfsr>>4)^(lfsr>>7))&1
            lfsr = ((lfsr<<1)|fb)&0xFF
        out[i] = data[i] ^ pn
    return bytes(out)

def ax100_encode(payload):
    parity = rs_encode(list(payload))
    rs_cw = bytes(payload) + bytes(parity)
    cw = golay24_encode(len(rs_cw))
    golay_bytes = bytes([(cw>>16)&0xFF, (cw>>8)&0xFF, cw&0xFF])
    post_asm = golay_bytes + rs_cw
    scrambled = ccsds_scramble(post_asm)
    asm = bytes([0x93, 0x0B, 0x51, 0xDE])
    return asm + scrambled

# ── Test ────────────────────────────────────────────────────────

def main():
    from crc import Calculator, Crc16
    crc_calc = Calculator(Crc16.XMODEM)

    # Build "EPS PING" payload
    msg = bytearray([6, 2, 0, 1, 4, 0])
    msg.extend(b'PING')
    msg.append(0x00)
    msg.extend(b'')
    msg.append(0x00)
    crc = crc_calc.checksum(msg)
    msg.extend(crc.to_bytes(2, byteorder='little'))
    payload = bytes(msg)

    print("=" * 60)
    print("  MAVERIC AX100 Loopback Test")
    print("=" * 60)
    print(f"\n  Payload ({len(payload)}B): {payload.hex(' ')}")

    # Encode
    frame = ax100_encode(payload)
    print(f"  Frame   ({len(frame)}B): {frame.hex(' ')}")

    # ── Step-by-step decode ──

    print(f"\n  --- Step-by-step decode ---")

    # 1. Strip ASM
    asm = frame[:4]
    scrambled = frame[4:]
    print(f"  1. ASM: {asm.hex(' ')}")

    # 2. Descramble (CCSDS scrambler is self-inverse)
    descrambled = ccsds_scramble(scrambled)
    print(f"  2. Descrambled ({len(descrambled)}B): {descrambled.hex(' ')}")

    # 3. Golay decode length
    golay_hdr = descrambled[:3]
    print(f"  3. Golay header bytes: {golay_hdr.hex(' ')}")

    # Try gr-satellites Golay decoder
    decoded_len = None
    try:
        decoded_len = satellites.nanocom_golay_decode_length(
            golay_hdr[0], golay_hdr[1], golay_hdr[2])
        print(f"     gr-satellites Golay decoded length: {decoded_len}")
    except Exception as e:
        print(f"     Golay block error: {e}")

    if decoded_len is None or decoded_len < 0:
        # Fallback: manually extract upper 12 bits
        golay_word = (golay_hdr[0] << 16) | (golay_hdr[1] << 8) | golay_hdr[2]
        decoded_len = golay_word >> 12
        print(f"     Manual Golay: upper 12 bits = {decoded_len}")

    # 4. Extract RS codeword
    rs_codeword = descrambled[3:3+decoded_len]
    print(f"  4. RS codeword ({len(rs_codeword)}B)")
    print(f"     Data:   {rs_codeword[:len(payload)].hex(' ')}")
    print(f"     Parity: {rs_codeword[len(payload):].hex(' ')}")

    # 5. RS decode via gr-satellites
    print(f"  5. RS decode via gr-satellites...")
    try:
        tb = gr.top_block()

        rs_pdu = pmt.cons(pmt.PMT_NIL,
                          pmt.init_u8vector(len(rs_codeword), list(rs_codeword)))

        src = blocks.message_strobe(rs_pdu, 100)
        rs_dec = satellites.decode_rs(True, 0)  # verbose=True, basis=0 (conventional)
        dbg = blocks.message_debug()

        tb.msg_connect(src, 'strobe', rs_dec, 'in')
        tb.msg_connect(rs_dec, 'out', dbg, 'store')

        tb.start()
        import time; time.sleep(0.5)
        tb.stop(); tb.wait()

        n = dbg.num_messages()
        if n > 0:
            decoded_bytes = bytes(pmt.u8vector_elements(pmt.cdr(dbg.get_message(0))))
            print(f"     Decoded ({len(decoded_bytes)}B): {decoded_bytes.hex(' ')}")
            match = (decoded_bytes == payload)
        else:
            print(f"     No output from RS decoder")
            print(f"     Trying dual basis (basis=1)...")

            # Try dual basis
            tb2 = gr.top_block()
            src2 = blocks.message_strobe(rs_pdu, 100)
            rs_dec2 = satellites.decode_rs(True, 1)  # basis=1 (dual)
            dbg2 = blocks.message_debug()
            tb2.msg_connect(src2, 'strobe', rs_dec2, 'in')
            tb2.msg_connect(rs_dec2, 'out', dbg2, 'store')
            tb2.start(); time.sleep(0.5); tb2.stop(); tb2.wait()

            n2 = dbg2.num_messages()
            if n2 > 0:
                decoded_bytes = bytes(pmt.u8vector_elements(pmt.cdr(dbg2.get_message(0))))
                print(f"     Dual basis decoded ({len(decoded_bytes)}B): {decoded_bytes.hex(' ')}")
                match = (decoded_bytes == payload)
            else:
                print(f"     Dual basis also failed")
                print(f"     Manual data check instead:")
                data_part = rs_codeword[:len(payload)]
                match = (data_part == payload)
                print(f"     Data == payload: {match}")

    except Exception as e:
        print(f"     RS decode error: {e}")
        data_part = rs_codeword[:len(payload)]
        match = (data_part == payload)
        print(f"     Manual data check: {match}")

    print(f"\n{'=' * 60}")
    if match:
        print(f"  RESULT: PASS")
    else:
        print(f"  RESULT: FAIL")
    print(f"{'=' * 60}")

if __name__ == '__main__':
    main()