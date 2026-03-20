import zmq
import pmt
import re
import struct
import sys
import time
from datetime import datetime, timezone

# --- CONFIGURATION ---
ZMQ_PORT = "52001"
ZMQ_ADDR = f"tcp://127.0.0.1:{ZMQ_PORT}"

# ANSI Colors
C_CYAN = "\033[96m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_BOLD = "\033[1m"
C_END = "\033[0m"

def clean_text(data: bytes) -> str:
    text = data.decode('ascii', errors='ignore')
    return "".join(c for c in text if c.isprintable()).strip()

def extract_sat_times(data: bytes) -> str:
    match = re.search(rb'\d{13}', data)
    if match:
        try:
            ms = int(match.group())
            dt_utc = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
            dt_local = dt_utc.astimezone()
            return f"{dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC')} | {dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        except:
            return "Invalid Format"
    return "No Timestamp Found"

def parse_csp_v1(header_bytes: bytes):
    if len(header_bytes) < 4:
        return None
    h = int.from_bytes(header_bytes, 'big')
    return {
        "prio": (h >> 30) & 0x03,
        "src": (h >> 25) & 0x1F,
        "dest": (h >> 20) & 0x1F,
        "dport": (h >> 14) & 0x3F,
        "sport": (h >> 8) & 0x3F,
        "flags": h & 0xFF
    }

# --- INITIALIZE ---
packet_count = 0
last_arrival_time = None
last_watchdog_time = time.time()

context = zmq.Context()
sock = context.socket(zmq.SUB)
sock.setsockopt(zmq.SUBSCRIBE, b"")     # subscribe to all topics
sock.setsockopt(zmq.RCVHWM, 10000)      # optional, helps with bursts
sock.connect(ZMQ_ADDR)

spinner = ['█', '▓', '▒', '░', '▒', '▓']
spin_idx = 0

print(f"\n{C_BOLD}┌──────────────────────────────────────────────────────────┐")
print(f"│                MAVERIC GS SOFTWARE v2.7                  │")
print(f"└──────────────────────────────────────────────────────────┘{C_END}")
print(f"Status: Monitoring ZMQ PUB Port {C_BOLD}{ZMQ_PORT}{C_END}\n")

try:
    while True:
        try:
            msg = sock.recv(zmq.NOBLOCK)

            # --- PACKET RECEIVED ---
            current_time = time.time()
            sys.stdout.write("\r" + " " * 60 + "\r")

            if last_arrival_time is not None:
                delta_t = current_time - last_arrival_time
                print(f"    Delta-T: {C_CYAN}{delta_t:.3f}s{C_END}")

            last_arrival_time = current_time
            last_watchdog_time = current_time

            pdu = pmt.deserialize_str(msg)
            meta = pmt.to_python(pmt.car(pdu))
            raw = bytes(pmt.u8vector_elements(pmt.cdr(pdu)))

            packet_count += 1
            gs_ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

            tx_info = str(meta.get('transmitter', ''))
            frame_type = "AX.25" if "AX.25" in tx_info else "AX100"
            color = C_YELLOW if frame_type == "AX.25" else C_GREEN

            idx = raw.find(b"\x03\xf0") if frame_type == "AX.25" else -1
            offset = (idx + 6) if frame_type == "AX.25" else 4

            csp = parse_csp_v1(raw[offset-4:offset]) if len(raw) >= offset else None
            payload = raw[offset:] if len(raw) >= offset else raw

            # --- DISPLAY ---
            print(f"────────────────────────────────────────────────────────────────────────────────")
            print(f"{C_BOLD}{color}Packet #{packet_count:<4}{C_END} | {gs_ts} | {color}{frame_type:<5}{C_END} | {C_BOLD}PDU Length : {len(raw)} Bytes{C_END}")

            if csp:
                print(f" {C_CYAN}CSP v1 │ Prio: {csp['prio']} | Src: {csp['src']} | Dest: {csp['dest']} | DestPort: {csp['dport']} | SrcPort: {csp['sport']} | Flags: 0x{csp['flags']:02x}{C_END}")

            print(f" SAT TIME  [{extract_sat_times(payload)}]")

            # SCANNER (Multiple types)
            if len(payload) >= 8:
                u8 = struct.unpack('<B', payload[0:1])[0]
                u16 = struct.unpack('<H', payload[0:2])[0]
                u32 = struct.unpack('<I', payload[0:4])[0]
                u64 = struct.unpack('<Q', payload[0:8])[0]
                f32 = struct.unpack('<f', payload[0:4])[0]
                f64 = struct.unpack('<d', payload[0:8])[0]

                f32_s = f"{f32:<10.3f}" if -1e5 < f32 < 1e5 else "---"
                f64_s = f"{f64:.6f}" if -1e5 < f64 < 1e5 else "---"

                print(f" {C_BOLD}SCANNER{C_END}   uint8: {u8:<3} | uint16: {u16:<5} | uint32: {u32:<10} | uint64: {u64}")
                print(f"           float32: {f32_s} | float64: {f64_s}")

            print(f" HEX       {raw.hex(' ')}")
            print(f" DATA      {clean_text(payload)}")
            print(f"────────────────────────────────────────────────────────────────────────────────")

        except zmq.Again:
            elapsed = time.time() - last_watchdog_time
            timer_color = C_YELLOW if elapsed > 10 else C_CYAN
            if elapsed > 30:
                timer_color = "\033[91m"

            sys.stdout.write(f"\r{C_BOLD}{C_CYAN} {spinner[spin_idx]} {C_END} Waiting... {timer_color}[SILENCE: {elapsed:04.1f}s]{C_END}")
            sys.stdout.flush()

            spin_idx = (spin_idx + 1) % len(spinner)
            time.sleep(0.1)

except KeyboardInterrupt:
    print(f"\n{C_YELLOW}Monitor Stopped.{C_END}")
    sock.close()
    context.term()