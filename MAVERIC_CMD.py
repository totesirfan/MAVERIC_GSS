"""
MAVERIC Command Terminal v2.2
Irfan Annuar -- USC ISI SERC

Type commands, they get KISS-wrapped with a CSP v1 header and
transmitted via AX100 ASM+Golay.

Single command:    EPS PING
Batch commands:    + EPS SET_MODE auto / + EPS SET_VOLTAGE 3.3 / send
CSP config:        csp / csp off / csp dest 8 / csp dport 24

GNU Radio flowgraph needs:
  ZMQ SUB Message Source (tcp://127.0.0.1:52002)
    -> AX100 ASM+Golay Encoder
    -> GFSK Modulator (4800 baud)
    -> SDR Sink (437.250 MHz)
"""

import zmq
import pmt
import re
import sys
import os
import json
import time
from datetime import datetime
from crc import Calculator, Crc16

try:
    import readline  # enables arrow keys, history, cursor movement in input()
except ImportError:
    pass  # Windows — input() still works, just no arrow keys

# -- Config -------------------------------------------------------------------

VERSION  = "2.3"
ZMQ_ADDR = "tcp://127.0.0.1:52002"
LOG_DIR  = "logs"
MAX_RS_PAYLOAD = 223

NODES = {
    'NONE': 0, 'LPPM': 1, 'EPS': 2, 'UPPM': 3,
    'HOLONAV': 4, 'ASTROBOARD': 5, 'GS': 6, 'FTDI': 7,
}
NODES_REV = {v: k for k, v in NODES.items()}

PTYPES = {'NONE': 0, 'REQ': 1, 'RES': 2, 'ACK': 3}

ORIGIN = NODES['GS']

# KISS constants
FEND  = 0xC0
FESC  = 0xDB
TFEND = 0xDC
TFESC = 0xDD

# -- ANSI Colors (matches MAVERIC_GSS.py) -------------------------------------

C_CYAN    = "\033[96m"
C_GREEN   = "\033[92m"
C_YELLOW  = "\033[93m"
C_RED     = "\033[91m"
C_DIM     = "\033[2m"
C_BOLD    = "\033[1m"
C_END     = "\033[0m"

# -- Box Drawing (matches MAVERIC_GSS.py) -------------------------------------

BOX_W = 80
INN_W = BOX_W - 4

TOP = f"\u250c{'\u2500' * (BOX_W - 2)}\u2510"
MID = f"\u251c{'\u2500' * (BOX_W - 2)}\u2524"
BOT = f"\u2514{'\u2500' * (BOX_W - 2)}\u2518"

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

def strip_ansi(s):
    return _ANSI_RE.sub("", s)

def _row(content=""):
    visible_len = len(strip_ansi(content))
    pad = max(0, INN_W - visible_len)
    return f"{C_DIM}\u2502{C_END} {content}{' ' * pad} {C_DIM}\u2502{C_END}"

def node_label(node_id):
    name = NODES_REV.get(node_id)
    return f"{node_id} ({name})" if name else str(node_id)

PTYPES_REV = {v: k for k, v in PTYPES.items()}

def ptype_label(ptype_id):
    name = PTYPES_REV.get(ptype_id)
    return f"{ptype_id} ({name})" if name else str(ptype_id)

# -- CSP v1 Header ------------------------------------------------------------

class CSPConfig:
    def __init__(self):
        self.enabled = True
        self.prio    = 2
        self.src     = 0
        self.dest    = 8
        self.dport   = 24
        self.sport   = 0
        self.flags   = 0x00

    def build_header(self):
        h = ((self.prio  & 0x03) << 30 |
             (self.src   & 0x1F) << 25 |
             (self.dest  & 0x1F) << 20 |
             (self.dport & 0x3F) << 14 |
             (self.sport & 0x3F) << 8  |
             (self.flags & 0xFF))
        return h.to_bytes(4, 'big')

    def overhead(self):
        return 4 if self.enabled else 0

    def show(self):
        hdr = self.build_header()
        state = f"{C_GREEN}enabled{C_END}" if self.enabled else f"{C_DIM}disabled{C_END}"
        print(f" {C_DIM}CSP V1{C_END}      {state}  {C_DIM}Prio:{self.prio} Src:{self.src} Dest:{self.dest} DPort:{self.dport} SPort:{self.sport} Flags:0x{self.flags:02X}{C_END}")
        print(f" {C_DIM}CSP Bytes{C_END}   {hdr.hex(' ')}  {C_DIM}(placeholder){C_END}")

    def handle_cmd(self, args):
        if not args:
            self.show()
            return True
        parts = args.split()
        cmd = parts[0].lower()
        if cmd == 'on':
            self.enabled = True
            print(f"  {C_GREEN}CSP header enabled{C_END}")
        elif cmd == 'off':
            self.enabled = False
            print(f"  {C_YELLOW}CSP header disabled{C_END}")
        elif cmd in ('prio','src','dest','dport','sport','flags') and len(parts) > 1:
            val = int(parts[1], 0)
            setattr(self, cmd, val)
            print(f"  CSP {cmd} = {val}")
        else:
            print(f"  {C_RED}csp [on|off|prio|src|dest|dport|sport|flags] [value]{C_END}")
        return True

# -- Command Builder ----------------------------------------------------------

crc_calc = Calculator(Crc16.XMODEM)

def build_cmd_raw(dest, cmd, args="", echo=0, ptype=1):
    p = bytearray()
    p.append(ORIGIN)
    p.append(dest)
    p.append(echo)
    p.append(ptype)
    p.append(len(cmd))
    p.append(len(args))
    p.extend(cmd.encode('ascii'))
    p.append(0x00)
    p.extend(args.encode('ascii'))
    p.append(0x00)
    crc = crc_calc.checksum(p)
    p.extend(crc.to_bytes(2, byteorder='little'))
    return p

def kiss_wrap(raw_cmd):
    escaped = bytearray()
    for b in raw_cmd:
        if b == FEND:
            escaped.extend(bytes([FESC, TFEND]))
        elif b == FESC:
            escaped.extend(bytes([FESC, TFESC]))
        else:
            escaped.append(b)
    frame = bytearray([FEND, 0x00])
    frame.extend(escaped)
    frame.append(FEND)
    return bytes(frame)

def build_kiss_cmd(dest, cmd, args="", echo=0, ptype=1):
    raw = build_cmd_raw(dest, cmd, args, echo, ptype)
    return kiss_wrap(raw), raw

def wrap_with_csp(csp, kiss_payload):
    if csp.enabled:
        return csp.build_header() + kiss_payload
    return kiss_payload

# -- ZMQ ---------------------------------------------------------------------

def zmq_connect(addr):
    ctx  = zmq.Context()
    sock = ctx.socket(zmq.PUB)
    sock.bind(addr)
    time.sleep(0.3)
    return ctx, sock

def zmq_send(sock, payload):
    meta = pmt.make_dict()
    vec  = pmt.init_u8vector(len(payload), list(payload))
    sock.send(pmt.serialize_str(pmt.cons(meta, vec)))

# -- Logging ------------------------------------------------------------------

def open_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(LOG_DIR, f"uplink_{ts}.jsonl")
    return open(path, "a"), path

def log_tx(f, n, cmds, payload, csp_enabled):
    rec = {
        "n": n,
        "ts": datetime.now().astimezone().isoformat(),
        "cmds": cmds,
        "hex": payload.hex(),
        "len": len(payload),
        "num_cmds": len(cmds),
        "csp": csp_enabled,
    }
    f.write(json.dumps(rec) + "\n")
    f.flush()

# -- Display (GSS-style boxes) -----------------------------------------------

ASCII_LINE_W = INN_W - 14  # "  ASCII       " = 14 visible chars

def _wrap_ascii(payload):
    """Convert payload to printable ASCII and wrap to fit inside box."""
    text = ''.join(chr(b) if 32 <= b < 127 else '\u00b7' for b in payload)
    lines = []
    for i in range(0, len(text), ASCII_LINE_W):
        chunk = text[i:i+ASCII_LINE_W]
        if i == 0:
            lines.append(_row(f"  {C_DIM}ASCII{C_END}       {C_DIM}{chunk}{C_END}"))
        else:
            lines.append(_row(f"              {C_DIM}{chunk}{C_END}"))
    return lines

def render_single(n, dest, cmd, args, payload, csp, raw_cmd):
    """Render a single command TX in GSS-style box."""
    ts   = datetime.now().strftime("%H:%M:%S")
    dlbl = node_label(dest)
    crc  = int.from_bytes(raw_cmd[-2:], 'little')

    csp_tag = f"  {C_DIM}[CSP]{C_END}" if csp.enabled else ""

    print(f"{C_DIM}{TOP}{C_END}")

    h_left  = f"{C_BOLD}{C_GREEN}TX #{n}{C_END}    {C_GREEN}UPLINK{C_END}{csp_tag}"
    h_right = f"{C_DIM}{len(payload)} B payload{C_END}"
    h_left_vis  = len(f"TX #{n}    UPLINK") + (7 if csp.enabled else 0)
    h_right_vis = len(f"{len(payload)} B payload")
    gap = INN_W - h_left_vis - len(ts) - h_right_vis
    gap1 = max(2, gap // 2)
    gap2 = gap - gap1
    print(_row(f"{h_left}{' ' * gap1}{ts}{' ' * gap2}{h_right}"))

    print(f"{C_DIM}{MID}{C_END}")
    print(_row())

    # CSP header
    if csp.enabled:
        hdr = csp.build_header()
        h = int.from_bytes(hdr, 'big')
        print(_row(
            f"  {C_CYAN}CSP V1{C_END}      "
            f"Prio {C_BOLD}{(h>>30)&3}{C_END}  "
            f"Src {C_BOLD}{(h>>25)&0x1F}{C_END}  "
            f"Dest {C_BOLD}{(h>>20)&0x1F}{C_END}  "
            f"DPort {C_BOLD}{(h>>14)&0x3F}{C_END}  "
            f"SPort {C_BOLD}{(h>>8)&0x3F}{C_END}  "
            f"Flags {C_BOLD}0x{h&0xFF:02X}{C_END}"
        ))

    # Command fields — extract from raw command bytes
    echo  = raw_cmd[2]
    ptype = raw_cmd[3]
    print(_row(
        f"  {C_CYAN}CMD{C_END}         "
        f"Src {C_BOLD}{node_label(ORIGIN)}{C_END}  "
        f"Dest {C_BOLD}{dlbl}{C_END}  "
        f"Echo {C_BOLD}{node_label(echo)}{C_END}  "
        f"Type {C_BOLD}{ptype_label(ptype)}{C_END}"
    ))
    print(_row(f"  {C_CYAN}CMD ID{C_END}      {C_BOLD}{cmd}{C_END}"))
    if args:
        print(_row(f"  {C_CYAN}CMD ARGS{C_END}    {C_BOLD}{args}{C_END}"))

    print(_row())

    # Raw data section
    print(f"{C_DIM}{MID}{C_END}")
    print(_row())

    hex_str = payload.hex(' ')
    parts = hex_str.split(' ')
    for i in range(0, len(parts), 20):
        chunk = ' '.join(parts[i:i+20])
        if i == 0:
            print(_row(f"  {C_GREEN}HEX{C_END}         {chunk}"))
        else:
            print(_row(f"              {chunk}"))

    print(_row())

    for al in _wrap_ascii(payload):
        print(al)
    print(_row(f"  {C_DIM}CRC-16{C_END}      {C_DIM}0x{crc:04x}{C_END}"))

    print(_row())
    print(f"{C_DIM}{BOT}{C_END}")


def render_batch(n, batch_info, payload, csp):
    """Render a batch TX in GSS-style box."""
    ts = datetime.now().strftime("%H:%M:%S")
    num = len(batch_info)
    csp_tag = f"  {C_DIM}[CSP]{C_END}" if csp.enabled else ""

    print(f"{C_DIM}{TOP}{C_END}")

    h_left  = f"{C_BOLD}{C_GREEN}TX #{n}{C_END}    {C_YELLOW}BATCH ({num} cmds){C_END}{csp_tag}"
    h_right = f"{C_DIM}{len(payload)} B payload{C_END}"
    h_left_vis  = len(f"TX #{n}    BATCH ({num} cmds)") + (7 if csp.enabled else 0)
    h_right_vis = len(f"{len(payload)} B payload")
    gap = INN_W - h_left_vis - len(ts) - h_right_vis
    gap1 = max(2, gap // 2)
    gap2 = gap - gap1
    print(_row(f"{h_left}{' ' * gap1}{ts}{' ' * gap2}{h_right}"))

    print(f"{C_DIM}{MID}{C_END}")
    print(_row())

    # CSP header
    if csp.enabled:
        hdr = csp.build_header()
        h = int.from_bytes(hdr, 'big')
        print(_row(
            f"  {C_CYAN}CSP V1{C_END}      "
            f"Prio {C_BOLD}{(h>>30)&3}{C_END}  "
            f"Src {C_BOLD}{(h>>25)&0x1F}{C_END}  "
            f"Dest {C_BOLD}{(h>>20)&0x1F}{C_END}  "
            f"DPort {C_BOLD}{(h>>14)&0x3F}{C_END}  "
            f"SPort {C_BOLD}{(h>>8)&0x3F}{C_END}  "
            f"Flags {C_BOLD}0x{h&0xFF:02X}{C_END}"
        ))
        print(_row())

    # Each command in the batch
    for i, (dest, cmd, args, kiss_len) in enumerate(batch_info):
        dlbl = node_label(dest)
        args_str = f"  {C_CYAN}args{C_END} {C_BOLD}{args}{C_END}" if args else ""
        print(_row(
            f"  {C_CYAN}CMD {i+1}{C_END}       "
            f"Dest {C_BOLD}{dlbl}{C_END}  "
            f"{C_BOLD}{cmd}{C_END}"
            f"{args_str}"
            f"  {C_DIM}({kiss_len}B){C_END}"
        ))

    print(_row())

    # Raw data section
    print(f"{C_DIM}{MID}{C_END}")
    print(_row())

    hex_str = payload.hex(' ')
    parts = hex_str.split(' ')
    for i in range(0, len(parts), 20):
        chunk = ' '.join(parts[i:i+20])
        if i == 0:
            print(_row(f"  {C_GREEN}HEX{C_END}         {chunk}"))
        else:
            print(_row(f"              {chunk}"))

    print(_row())

    for al in _wrap_ascii(payload):
        print(al)

    print(_row())
    print(f"{C_DIM}{BOT}{C_END}")


def render_raw(n, payload):
    """Render a raw hex TX in GSS-style box."""
    ts = datetime.now().strftime("%H:%M:%S")

    print(f"{C_DIM}{TOP}{C_END}")
    print(_row(f"{C_BOLD}{C_GREEN}TX #{n}{C_END}    {C_RED}RAW{C_END}    {ts}    {C_DIM}{len(payload)} B{C_END}"))
    print(f"{C_DIM}{MID}{C_END}")
    print(_row())

    hex_str = payload.hex(' ')
    parts = hex_str.split(' ')
    for i in range(0, len(parts), 20):
        chunk = ' '.join(parts[i:i+20])
        if i == 0:
            print(_row(f"  {C_GREEN}HEX{C_END}         {chunk}"))
        else:
            print(_row(f"              {chunk}"))

    print(_row())
    print(f"{C_DIM}{BOT}{C_END}")


# -- Node Resolution ----------------------------------------------------------

def resolve_dest(s):
    if s.upper() in NODES:
        return NODES[s.upper()]
    if s.isdigit() and int(s) in NODES_REV:
        return int(s)
    return None

def parse_cmd_line(line):
    parts = line.split(None, 2)
    if len(parts) < 2:
        return None
    dest = resolve_dest(parts[0])
    if dest is None:
        return None
    cmd  = parts[1]
    args = parts[2] if len(parts) > 2 else ""
    return (dest, cmd, args)

# -- Main Loop ----------------------------------------------------------------

def main():
    csp = CSPConfig()
    tx_count = 0

    print(f"\n{C_BOLD}\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510")
    print(f"\u2502                    MAVERIC CMD TERMINAL                  \u2502")
    print(f"\u2502                           {C_END}{C_DIM}v{VERSION}{C_END}{C_BOLD}                           \u2502")
    print(f"\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518{C_END}")
    print()
    print(f" {C_DIM}ZMQ{C_END}         {C_BOLD}{ZMQ_ADDR}{C_END}")
    print(f" {C_DIM}Origin{C_END}      {C_BOLD}GS ({ORIGIN}){C_END}")
    print(f" {C_DIM}Framing{C_END}     KISS + AX100 ASM+Golay")

    ctx, sock = zmq_connect(ZMQ_ADDR)
    logf, logpath = open_log()
    print(f" {C_DIM}Log{C_END}         {logpath}")
    print()

    csp.show()
    print(f"\n {C_DIM}Type a command or 'help'{C_END}\n")

    n      = 0
    last   = None
    batch  = []

    def max_payload():
        return MAX_RS_PAYLOAD - csp.overhead()

    try:
        while True:
            if batch:
                prompt = f"  {C_YELLOW}+({len(batch)}){C_END}{C_CYAN}\u25b6{C_END} "
            else:
                prompt = f"  {C_CYAN}\u25b6{C_END} "

            try:
                line = input(prompt).strip()
            except EOFError:
                break

            if not line:
                continue

            low = line.lower()

            if low in ('q', 'quit', 'exit'):
                if batch:
                    print(f"  {C_YELLOW}Discarding {len(batch)} queued commands{C_END}")
                break

            if low == 'help':
                print(f"""
  {C_BOLD}Single command:{C_END}
    {C_CYAN}<dest> <cmd> [args]{C_END}     send immediately

  {C_BOLD}Batch commands:{C_END}
    {C_CYAN}+ <dest> <cmd> [args]{C_END}   queue a command
    {C_CYAN}send{C_END}                    transmit all queued
    {C_CYAN}batch{C_END}                   show queue
    {C_CYAN}clear{C_END}                   discard queue

  {C_BOLD}CSP config:{C_END}
    {C_CYAN}csp{C_END}                     show CSP settings
    {C_CYAN}csp on/off{C_END}              enable/disable
    {C_CYAN}csp dest N{C_END}              set destination
    {C_CYAN}csp dport N{C_END}             set destination port

  {C_BOLD}Other:{C_END}
    {C_CYAN}!!{C_END}                      repeat last command
    {C_CYAN}nodes{C_END}                   list node IDs
    {C_CYAN}raw <hex>{C_END}               send raw hex bytes
    {C_CYAN}q{C_END}                       quit

  {C_BOLD}Examples:{C_END}
    EPS PING
    + EPS SET_MODE auto
    + EPS SET_VOLTAGE 3.3
    send
""")
                continue

            if low == 'nodes':
                print(f"\n  {C_BOLD}Node Addresses:{C_END}")
                for nid in sorted(NODES_REV):
                    lbl = NODES_REV[nid]
                    tag = f" {C_GREEN}<- you{C_END}" if nid == ORIGIN else ""
                    print(f"    {nid} = {C_BOLD}{lbl}{C_END}{tag}")
                print()
                continue

            # -- CSP config --
            if low == 'csp' or low.startswith('csp '):
                csp_args = line[3:].strip() if len(line) > 3 else ""
                csp.handle_cmd(csp_args)
                continue

            # -- batch commands --
            if low == 'batch':
                if not batch:
                    print(f"  {C_DIM}batch is empty{C_END}")
                else:
                    total = sum(len(k) for _, _, _, k in batch)
                    remaining = max_payload() - total
                    print(f"\n  {C_BOLD}Batch Queue{C_END}  {C_DIM}{len(batch)} commands, {total}B + {csp.overhead()}B CSP{C_END}")
                    for i, (dest, cmd, args, kiss) in enumerate(batch):
                        dlbl = node_label(dest)
                        print(f"    {C_DIM}{i+1}.{C_END} {C_BOLD}{dlbl}{C_END}  {C_CYAN}{cmd}{C_END}  {args}  {C_DIM}({len(kiss)}B){C_END}")
                    print(f"  {C_DIM}{remaining}B remaining in frame{C_END}\n")
                continue

            if low == 'clear':
                if batch:
                    print(f"  {C_DIM}cleared {len(batch)} commands{C_END}")
                    batch.clear()
                else:
                    print(f"  {C_DIM}nothing to clear{C_END}")
                continue

            if low == 'send':
                if not batch:
                    print(f"  {C_RED}nothing queued -- use + to add commands{C_END}")
                    continue

                kiss_stream = bytearray()
                batch_info = []
                for dest, cmd, args, kiss in batch:
                    kiss_stream.extend(kiss)
                    batch_info.append((dest, cmd, args, len(kiss)))

                if len(kiss_stream) > max_payload():
                    print(f"  {C_RED}batch too large: {len(kiss_stream)}B > {max_payload()}B max{C_END}")
                    continue

                payload = wrap_with_csp(csp, bytes(kiss_stream))
                n += 1
                zmq_send(sock, payload)
                render_batch(n, batch_info, payload, csp)
                log_tx(logf, n,
                       [{"dest": d, "dest_lbl": NODES_REV.get(d,"?"),
                         "cmd": c, "args": a} for d, c, a, _ in batch],
                       payload, csp.enabled)
                batch.clear()
                continue

            # -- queue with + --
            if line.startswith('+'):
                cmd_text = line[1:].strip()
                if not cmd_text:
                    print(f"  {C_RED}need: + <dest> <cmd> [args]{C_END}")
                    continue
                parsed = parse_cmd_line(cmd_text)
                if parsed is None:
                    print(f"  {C_RED}bad command -- format: + <dest> <cmd> [args]{C_END}")
                    continue
                dest, cmd, args = parsed
                kiss, raw = build_kiss_cmd(dest, cmd, args)

                current_total = sum(len(k) for _, _, _, k in batch)
                if current_total + len(kiss) > max_payload():
                    print(f"  {C_RED}won't fit: {current_total + len(kiss)}B > {max_payload()}B{C_END}")
                    continue

                batch.append((dest, cmd, args, kiss))
                dlbl = node_label(dest)
                remaining = max_payload() - (current_total + len(kiss))
                print(f"  {C_DIM}queued #{len(batch)}: {dlbl} {cmd} {args} ({len(kiss)}B, {remaining}B remaining){C_END}")
                continue

            # -- repeat last --
            if low == '!!' or low == 'last':
                if last is None:
                    print(f"  {C_DIM}nothing to repeat{C_END}")
                    continue
                dest, cmd, args = last

            # -- raw hex --
            elif low.startswith('raw '):
                hexstr = line[4:].replace(' ', '')
                try:
                    raw_bytes = bytes.fromhex(hexstr)
                except ValueError:
                    print(f"  {C_RED}bad hex{C_END}")
                    continue
                n += 1
                zmq_send(sock, raw_bytes)
                render_raw(n, raw_bytes)
                continue

            # -- single command --
            else:
                parsed = parse_cmd_line(line)
                if parsed is None:
                    print(f"  {C_RED}need: <dest> <cmd> [args]{C_END}")
                    continue
                dest, cmd, args = parsed
                last = (dest, cmd, args)

            # Build, wrap with CSP, send
            kiss, raw_cmd = build_kiss_cmd(dest, cmd, args)

            if len(kiss) + csp.overhead() > MAX_RS_PAYLOAD:
                print(f"  {C_RED}command too large: {len(kiss) + csp.overhead()}B > {MAX_RS_PAYLOAD}B{C_END}")
                continue

            payload = wrap_with_csp(csp, kiss)
            n += 1
            zmq_send(sock, payload)
            render_single(n, dest, cmd, args, payload, csp, raw_cmd)
            log_tx(logf, n,
                   [{"dest": dest, "dest_lbl": NODES_REV.get(dest,"?"),
                     "cmd": cmd, "args": args}],
                   payload, csp.enabled)

    except KeyboardInterrupt:
        if batch:
            print(f"\n  {C_YELLOW}Discarding {len(batch)} queued commands{C_END}")

    # Session summary (matches GSS style)
    print(f"\n")
    print(f"{C_DIM}{'\u2500' * 50}{C_END}")
    print(f"  {C_BOLD}Session ended{C_END}")
    print(f"  Transmitted:  {C_BOLD}{n}{C_END}")
    print(f"{C_DIM}{'\u2500' * 50}{C_END}")
    print(f"  {C_DIM}{logpath}{C_END}")
    print()

    logf.close()
    sock.close()
    ctx.term()


if __name__ == "__main__":
    main()