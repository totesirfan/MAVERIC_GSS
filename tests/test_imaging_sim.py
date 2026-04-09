#!/usr/bin/env python3
"""
test_imaging_sim.py -- Simulate satellite image downlink via ZMQ

Chunks a test JPEG and sends it through the ZMQ PUB socket as if
gr-satellites had demodulated and decoded real downlink packets.

Each packet is a fully formed AX.25-framed, CSP-wrapped command frame
with correct CRC-16 and CRC-32C — identical to what the RX pipeline
expects from the real radio chain.

Usage:
    # Start MAV_WEB.py first, then in another terminal:
    python3 tests/test_imaging_sim.py [image_path] [--chunk-size 150] [--delay 0.05]

    # With no args, generates a small synthetic JPEG test pattern
    python3 tests/test_imaging_sim.py

Author:  Irfan Annuar - USC ISI SERC
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mav_gss_lib.protocols.ax25 import AX25Config
from mav_gss_lib.protocols.crc import crc16, crc32c


# -- Node / ptype IDs (from mission.example.yml) ----------------------------

NODES = {"NONE": 0, "LPPM": 1, "EPS": 2, "UPPM": 3, "HLNV": 4, "ASTR": 5, "GS": 6, "FTDI": 7}
PTYPE_RES = 2  # response


# -- Packet builders ---------------------------------------------------------

def build_command_frame(src, dest, echo, ptype, cmd_id, args_bytes):
    """Build raw MAVERIC command wire format with CRC-16.

    Wire: [src][dest][echo][ptype][id_len][args_len][id\\0][args\\0][crc16-LE]
    """
    id_bytes = cmd_id.encode('ascii')
    packet = bytearray([
        src & 0xFF, dest & 0xFF, echo & 0xFF, ptype & 0xFF,
        len(id_bytes) & 0xFF, len(args_bytes) & 0xFF,
    ])
    packet.extend(id_bytes)
    packet.append(0x00)
    packet.extend(args_bytes)
    packet.append(0x00)
    crc_val = crc16(packet)
    packet.extend(crc_val.to_bytes(2, byteorder='little'))
    return bytes(packet)


def build_csp_header(src_node, dest_node, dport=0, sport=24, prio=2, flags=0):
    """Build a 4-byte CSP v1 header."""
    h = ((prio & 0x03) << 30 |
         (src_node & 0x1F) << 25 |
         (dest_node & 0x1F) << 20 |
         (dport & 0x3F) << 14 |
         (sport & 0x3F) << 8 |
         (flags & 0xFF))
    return h.to_bytes(4, 'big')


def wrap_full_packet(cmd_bytes, src_node, dest_node=6):
    """Wrap command bytes in CSP + CRC-32C + AX.25 header.

    Produces a complete packet matching what gr-satellites outputs
    after demodulating an AX.25 downlink frame.
    """
    # CSP: header + payload + CRC-32C
    csp_hdr = build_csp_header(src_node, dest_node)
    csp_packet = csp_hdr + cmd_bytes
    csp_crc = crc32c(csp_packet).to_bytes(4, 'big')
    csp_full = csp_packet + csp_crc

    # AX.25: header (dest + src + 03 F0) + CSP payload
    ax25 = AX25Config()
    ax25.dest_call = "WM2XBB"
    ax25.dest_ssid = 97
    ax25.src_call = "WS9XSW"
    ax25.src_ssid = 96
    return ax25.wrap(csp_full)


def send_pmt_pdu(sock, payload):
    """Send payload as a PMT PDU with AX.25 transmitter metadata."""
    import pmt
    # Metadata must include transmitter so detect_frame_type classifies as AX.25
    meta = pmt.make_dict()
    meta = pmt.dict_add(meta, pmt.intern("transmitter"), pmt.intern("AX.25"))
    vec = pmt.init_u8vector(len(payload), list(payload))
    sock.send(pmt.serialize_str(pmt.cons(meta, vec)))


# -- Packet factories for imaging commands -----------------------------------

def make_cnt_chunks_response(filename, num_chunks, src_node):
    """img_cnt_chunks RX response: Filename, Num Chunks (text args)."""
    args_str = f"{filename} {num_chunks}"
    cmd = build_command_frame(src_node, NODES["GS"], 0, PTYPE_RES,
                              "img_cnt_chunks", args_str.encode('ascii'))
    return wrap_full_packet(cmd, src_node)


def make_get_chunk_response(filename, chunk_num, chunk_size, data, src_node):
    """img_get_chunk RX response: Filename, Chunk Number, Chunk Size, Data (blob).

    The first 3 args are space-separated ASCII text. Data is raw binary
    appended after a space — the schema parser extracts it as a blob from
    args_raw at the byte offset past the 3 text fields.
    """
    text_prefix = f"{filename} {chunk_num} {chunk_size} ".encode('ascii')
    args_bytes = text_prefix + data
    cmd = build_command_frame(src_node, NODES["GS"], 0, PTYPE_RES,
                              "img_get_chunk", args_bytes)
    return wrap_full_packet(cmd, src_node)


# -- Test image generation ---------------------------------------------------

TEST_COLORS = {
    "red":     (220, 50, 50),
    "green":   (50, 180, 80),
    "blue":    (50, 80, 220),
    "orange":  (230, 140, 30),
    "purple":  (150, 60, 200),
    "cyan":    (30, 200, 200),
}


def generate_test_jpeg(color_name="red", width=128, height=128):
    """Generate a colored test JPEG with a gradient pattern.

    Uses PIL if available for a nice gradient image.
    Falls back to a solid-color minimal JPEG otherwise.
    """
    base = TEST_COLORS.get(color_name, (200, 200, 200))

    try:
        from PIL import Image as PILImage, ImageDraw, ImageFont
        import io

        img = PILImage.new('RGB', (width, height))
        pixels = img.load()
        for y in range(height):
            for x in range(width):
                # Diagonal gradient from base color to white
                t = (x + y) / (width + height)
                r = int(base[0] + (255 - base[0]) * t * 0.6)
                g = int(base[1] + (255 - base[1]) * t * 0.6)
                b = int(base[2] + (255 - base[2]) * t * 0.6)
                pixels[x, y] = (min(r, 255), min(g, 255), min(b, 255))

        # Draw color name as label
        draw = ImageDraw.Draw(img)
        try:
            draw.text((4, 4), color_name.upper(), fill=(255, 255, 255))
        except Exception:
            pass

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85)
        return buf.getvalue()
    except ImportError:
        pass

    # Fallback: minimal valid JPEG (solid color, 8x8)
    # This is a hardcoded minimal JPEG — won't show the color but is valid
    return bytes([
        0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
        0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
        0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
        0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
        0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
        0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
        0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
        0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
        0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
        0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
        0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
        0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D,
        0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
        0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
        0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
        0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
        0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
        0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F, 0x00, 0x7B, 0x94,
        0x11, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0xFF, 0xD9,
    ])


# -- Interactive menu --------------------------------------------------------

TEST_IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_images")


def find_test_images():
    """Find JPEG/PNG files in the test_images directory."""
    if not os.path.isdir(TEST_IMAGES_DIR):
        return []
    images = []
    for f in sorted(os.listdir(TEST_IMAGES_DIR)):
        if f.lower().endswith(('.jpg', '.jpeg', '.png')):
            path = os.path.join(TEST_IMAGES_DIR, f)
            size = os.path.getsize(path)
            images.append((f, path, size))
    return images


def interactive_select():
    """Show a menu to select image, delay, drop settings."""
    print("=" * 50)
    print("  MAVERIC Imaging Downlink Simulator")
    print("=" * 50)
    print()

    # Image selection
    test_images = find_test_images()
    print("Select image source:")
    print()
    for i, (name, path, size) in enumerate(test_images):
        chunks = -(-size // 150)
        print(f"  [{i + 1}] {name}  ({size:,} bytes, ~{chunks} chunks)")
    print()
    print(f"  [g] Generate synthetic colored image")
    print(f"  [q] Quit")
    print()
    choice = input("Choice: ").strip().lower()

    if choice == 'q':
        sys.exit(0)

    if choice == 'g':
        color_names = list(TEST_COLORS.keys())
        print()
        for i, c in enumerate(color_names):
            print(f"  [{i + 1}] {c}")
        ci = input(f"Color [1-{len(color_names)}]: ").strip()
        try:
            color = color_names[int(ci) - 1]
        except (ValueError, IndexError):
            color = "red"
        data = generate_test_jpeg(color, 640, 480)
        filename = f"test_{color}.jpg"
        print(f"Generated {filename}: {len(data)} bytes")
    else:
        try:
            idx = int(choice) - 1
            name, path, _ = test_images[idx]
        except (ValueError, IndexError):
            print("Invalid choice")
            sys.exit(1)
        with open(path, "rb") as f:
            data = f.read()
        filename = name
        print(f"Loaded {filename}: {len(data)} bytes")

    # Downlink filename
    print()
    fn_input = input(f"Downlink filename [{filename}]: ").strip()
    if fn_input:
        filename = fn_input

    # Delay
    print()
    delay_input = input("Delay between chunks in seconds [0.05]: ").strip()
    try:
        delay = float(delay_input) if delay_input else 0.05
    except ValueError:
        delay = 0.05

    # Packet loss
    print()
    drop_input = input("Drop every Nth chunk (0=none) [0]: ").strip()
    try:
        drop_every = int(drop_input) if drop_input else 0
    except ValueError:
        drop_every = 0

    return [(filename, data)], delay, drop_every


# -- Main --------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Simulate satellite image downlink")
    parser.add_argument("image", nargs="?", help="Path to JPEG file (omit for interactive menu)")
    parser.add_argument("--chunk-size", type=int, default=150, help="Bytes per chunk (default: 150)")
    parser.add_argument("--delay", type=float, default=0.05, help="Delay between chunks in seconds (default: 0.05)")
    parser.add_argument("--filename", default=None, help="Filename reported in packets")
    parser.add_argument("--addr", default="tcp://127.0.0.1:52001", help="ZMQ PUB address (default: tcp://127.0.0.1:52001)")
    parser.add_argument("--node", default="HLNV", choices=["HLNV", "ASTR"], help="Source node (default: HLNV)")
    parser.add_argument("--drop-every", type=int, default=0, help="Drop every Nth chunk to simulate packet loss (0=no drops)")
    args = parser.parse_args()

    src_node = NODES[args.node.upper()]
    chunk_size = min(args.chunk_size, 220)

    # Interactive menu or CLI mode
    if args.image:
        with open(args.image, "rb") as f:
            image_data = f.read()
        filename = args.filename or os.path.basename(args.image)
        images = [(filename, image_data)]
        delay = args.delay
        drop_every = args.drop_every
        print(f"Loaded {args.image}: {len(image_data)} bytes")
    else:
        images, delay, drop_every = interactive_select()

    print(f"\nChunk size: {chunk_size}, Delay: {delay}s, Source: {args.node}")
    if drop_every:
        print(f"Dropping every {drop_every}th chunk")
    print(f"Publishing to {args.addr}")

    # Initialize ZMQ PUB
    import zmq
    ctx = zmq.Context()
    sock = ctx.socket(zmq.PUB)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.SNDHWM, 10000)
    try:
        sock.bind(args.addr)
    except zmq.ZMQError as e:
        print(f"ERROR: Cannot bind to {args.addr}: {e}")
        print("Is GNU Radio or another process already bound on this port?")
        sys.exit(1)

    print("\nPUB socket bound. Press ENTER when MAV_WEB shows ZMQ RX ONLINE...")
    input()
    print("Sending packets...\n")

    for img_idx, (filename, image_data) in enumerate(images):
        # Chunk the image
        chunks = []
        offset = 0
        while offset < len(image_data):
            end = min(offset + chunk_size, len(image_data))
            chunks.append(image_data[offset:end])
            offset = end
        num_chunks = len(chunks)

        if img_idx > 0:
            print()
        print(f"=== {filename} ({num_chunks} chunks, {len(image_data):,} bytes) ===")

        # Send img_cnt_chunks response
        print(f"  [1/{num_chunks + 1}] img_cnt_chunks: {num_chunks} chunks")
        pdu = make_cnt_chunks_response(filename, num_chunks, src_node)
        send_pmt_pdu(sock, pdu)
        time.sleep(delay)

        # Send img_get_chunk responses
        dropped_indices = []
        for i, chunk in enumerate(chunks):
            if drop_every > 0 and i > 0 and i % drop_every == 0:
                print(f"  [{i + 2}/{num_chunks + 1}] chunk {i} DROPPED")
                dropped_indices.append(i)
                time.sleep(delay)
                continue
            print(f"  [{i + 2}/{num_chunks + 1}] chunk {i} ({len(chunk)} bytes)")
            pdu = make_get_chunk_response(filename, i, len(chunk), chunk, src_node)
            send_pmt_pdu(sock, pdu)
            time.sleep(delay)

        if dropped_indices:
            print(f"  Done: {filename} ({len(dropped_indices)} chunks dropped: {dropped_indices})")
            print(f"\n  Press ENTER to re-request {len(dropped_indices)} missing chunk(s)...")
            input()
            print(f"  Re-sending dropped chunks...")
            for i in dropped_indices:
                chunk = chunks[i]
                print(f"  [re-request] chunk {i} ({len(chunk)} bytes)")
                pdu = make_get_chunk_response(filename, i, len(chunk), chunk, src_node)
                send_pmt_pdu(sock, pdu)
                time.sleep(delay)
            print(f"  All dropped chunks re-sent for {filename}")
        else:
            print(f"  Done: {filename}")

    print(f"\nAll images sent! Check http://127.0.0.1:8080/?page=imaging")

    sock.close()
    ctx.term()


if __name__ == "__main__":
    main()
