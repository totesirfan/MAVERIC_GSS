"""
MAV_TX -- MAVERIC Command Terminal

Uplink command interface for the MAVERIC CubeSat mission. Builds KISS-wrapped
commands with a CSP v1 header and publishes them as PMT PDUs over ZMQ for
the AX100 ASM+Golay encoder flowgraph in GNU Radio.

Single command:    EPS PING
Batch commands:    + EPS SET_MODE auto / + EPS SET_VOLTAGE 3.3 / send
CSP config:        csp / csp dest 8 / csp dport 24

When maveric_commands.yml is present, args are validated against the schema
before sending. Type mismatches and missing args produce warnings but do
not block transmission -- the operator always has final say.

Requires GNU Radio flowgraph:
    ZMQ SUB Source (:52002) -> AX100 Encoder -> GFSK Mod -> USRP Sink

Author:  Irfan Annuar - USC ISI SERC
"""

import os
import json
import time
from datetime import datetime

try:
    import readline  # arrow keys, history, cursor movement in input()
except ImportError:
    pass  # Windows -- input() still works, just no line editing

from mav_gss_lib.protocol import (
    NODE_NAMES, NODE_IDS, GS_NODE,
    node_label, ptype_label, resolve_node,
    build_kiss_cmd, CSPConfig,
    load_command_defs, validate_args,
)
from mav_gss_lib.display import (
    C, TOP, MID, BOT, INN_W,
    row, strip_ansi, wrap_ascii, wrap_hex,
    banner, info_line, separator,
)
from mav_gss_lib.transport import init_zmq_pub, send_pdu

# -- Config -------------------------------------------------------------------

VERSION  = "3.1"
ZMQ_ADDR = "tcp://127.0.0.1:52002"
LOG_DIR  = "logs"
MAX_RS_PAYLOAD = 223
CMD_DEFS_PATH = "maveric_commands.yml"


# -- Logging ------------------------------------------------------------------

def open_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(LOG_DIR, f"uplink_{ts}.jsonl")
    return open(path, "a"), path


def log_tx(f, n, cmds, payload, csp_enabled):
    rec = {
        "n": n, "ts": datetime.now().astimezone().isoformat(),
        "cmds": cmds, "hex": payload.hex(), "len": len(payload),
        "num_cmds": len(cmds), "csp": csp_enabled,
    }
    f.write(json.dumps(rec) + "\n")
    f.flush()


# -- CSP CLI ------------------------------------------------------------------

def csp_show(csp):
    hdr = csp.build_header()
    state = f"{C.SUCCESS}enabled{C.END}" if csp.enabled else f"{C.DIM}disabled{C.END}"
    print(f" {C.DIM}CSP V1{C.END}      {state}  "
          f"{C.DIM}Prio:{csp.prio} Src:{csp.src} Dest:{csp.dest} "
          f"DPort:{csp.dport} SPort:{csp.sport} Flags:0x{csp.flags:02X}{C.END}")
    print(f" {C.DIM}CSP Bytes{C.END}   {hdr.hex(' ')}  {C.DIM}(placeholder){C.END}")


def csp_handle(csp, args):
    if not args:
        csp_show(csp)
        return
    parts = args.split()
    cmd = parts[0].lower()
    if cmd == 'on':
        csp.enabled = True
        print(f"  {C.SUCCESS}CSP header enabled{C.END}")
    elif cmd == 'off':
        csp.enabled = False
        print(f"  {C.WARNING}CSP header disabled{C.END}")
    elif cmd in ('prio', 'src', 'dest', 'dport', 'sport', 'flags') and len(parts) > 1:
        val = int(parts[1], 0)
        setattr(csp, cmd, val)
        print(f"  CSP {cmd} = {val}")
    else:
        print(f"  {C.ERROR}csp [on|off|prio|src|dest|dport|sport|flags] [value]{C.END}")


# -- Render -------------------------------------------------------------------

def _csp_row(csp):
    hdr = csp.build_header()
    h = int.from_bytes(hdr, 'big')
    return row(
        f"  {C.LABEL}CSP V1{C.END}      "
        f"Prio {C.VALUE}{(h>>30)&3}{C.END}  "
        f"Src {C.VALUE}{(h>>25)&0x1F}{C.END}  "
        f"Dest {C.VALUE}{(h>>20)&0x1F}{C.END}  "
        f"DPort {C.VALUE}{(h>>14)&0x3F}{C.END}  "
        f"SPort {C.VALUE}{(h>>8)&0x3F}{C.END}  "
        f"Flags {C.VALUE}0x{h&0xFF:02X}{C.END}"
    )


def render_single(n, dest, cmd, args, payload, csp, raw_cmd):
    ts = datetime.now().strftime("%H:%M:%S")
    crc = int.from_bytes(raw_cmd[-2:], 'little')
    echo = raw_cmd[2]
    ptype = raw_cmd[3]
    csp_tag = f"  {C.DIM}[CSP]{C.END}" if csp.enabled else ""

    print(f"{C.DIM}{TOP}{C.END}")
    h_left = f"{C.BOLD}{C.SUCCESS}TX #{n}{C.END}    {C.SUCCESS}UPLINK{C.END}{csp_tag}"
    h_right = f"{C.DIM}{len(payload)} B payload{C.END}"
    h_lv = len(f"TX #{n}    UPLINK") + (7 if csp.enabled else 0)
    h_rv = len(f"{len(payload)} B payload")
    gap = INN_W - h_lv - len(ts) - h_rv
    g1 = max(2, gap // 2)
    g2 = gap - g1
    print(row(f"{h_left}{' '*g1}{ts}{' '*g2}{h_right}"))

    print(f"{C.DIM}{MID}{C.END}")
    print(row())
    if csp.enabled:
        print(_csp_row(csp))
    print(row(
        f"  {C.LABEL}CMD{C.END}         "
        f"Src {C.VALUE}{node_label(GS_NODE)}{C.END}  "
        f"Dest {C.VALUE}{node_label(dest)}{C.END}  "
        f"Echo {C.VALUE}{node_label(echo)}{C.END}  "
        f"Type {C.VALUE}{ptype_label(ptype)}{C.END}"
    ))
    print(row(f"  {C.LABEL}CMD ID{C.END}      {C.VALUE}{cmd}{C.END}"))
    if args:
        print(row(f"  {C.LABEL}CMD ARGS{C.END}    {C.VALUE}{args}{C.END}"))
    print(row())

    print(f"{C.DIM}{MID}{C.END}")
    print(row())
    for hl in wrap_hex(payload.hex(' ')):
        print(hl)
    print(row())
    for al in wrap_ascii(payload):
        print(al)
    print(row(f"  {C.DIM}CRC-16{C.END}      {C.DIM}0x{crc:04x}{C.END}"))
    print(row())
    print(f"{C.DIM}{BOT}{C.END}")


def render_batch(n, batch_info, payload, csp):
    ts = datetime.now().strftime("%H:%M:%S")
    num = len(batch_info)
    csp_tag = f"  {C.DIM}[CSP]{C.END}" if csp.enabled else ""

    print(f"{C.DIM}{TOP}{C.END}")
    h_left = f"{C.BOLD}{C.SUCCESS}TX #{n}{C.END}    {C.WARNING}BATCH ({num} cmds){C.END}{csp_tag}"
    h_right = f"{C.DIM}{len(payload)} B payload{C.END}"
    h_lv = len(f"TX #{n}    BATCH ({num} cmds)") + (7 if csp.enabled else 0)
    h_rv = len(f"{len(payload)} B payload")
    gap = INN_W - h_lv - len(ts) - h_rv
    g1 = max(2, gap // 2)
    g2 = gap - g1
    print(row(f"{h_left}{' '*g1}{ts}{' '*g2}{h_right}"))

    print(f"{C.DIM}{MID}{C.END}")
    print(row())
    if csp.enabled:
        print(_csp_row(csp))
        print(row())
    for i, (dest, cmd, args, kiss_len) in enumerate(batch_info):
        args_str = f"  {C.LABEL}args{C.END} {C.VALUE}{args}{C.END}" if args else ""
        print(row(
            f"  {C.LABEL}CMD {i+1}{C.END}       "
            f"Dest {C.VALUE}{node_label(dest)}{C.END}  "
            f"{C.VALUE}{cmd}{C.END}{args_str}  {C.DIM}({kiss_len}B){C.END}"
        ))
    print(row())

    print(f"{C.DIM}{MID}{C.END}")
    print(row())
    for hl in wrap_hex(payload.hex(' ')):
        print(hl)
    print(row())
    for al in wrap_ascii(payload):
        print(al)
    print(row())
    print(f"{C.DIM}{BOT}{C.END}")


def render_raw(n, payload):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{C.DIM}{TOP}{C.END}")
    print(row(f"{C.BOLD}{C.SUCCESS}TX #{n}{C.END}    {C.ERROR}RAW{C.END}    {ts}    {C.DIM}{len(payload)} B{C.END}"))
    print(f"{C.DIM}{MID}{C.END}")
    print(row())
    for hl in wrap_hex(payload.hex(' ')):
        print(hl)
    print(row())
    print(f"{C.DIM}{BOT}{C.END}")


# -- Command Parsing ----------------------------------------------------------

def parse_cmd_line(line):
    parts = line.split(None, 2)
    if len(parts) < 2:
        return None
    dest = resolve_node(parts[0])
    if dest is None:
        return None
    return (dest, parts[1], parts[2] if len(parts) > 2 else "")


def check_args(cmd, args, cmd_defs):
    """Validate command and args against schema before sending.

    When schema is loaded:
      - Unknown commands are BLOCKED (not in YAML = not allowed)
      - Arg type/count mismatches are BLOCKED
    When schema is not loaded:
      - Everything passes (no validation possible)

    Returns True to proceed, False to block."""
    if not cmd_defs:
        return True

    if cmd not in cmd_defs:
        print(f"  {C.ERROR}\u26a0 '{cmd}' not defined in schema -- blocked{C.END}")
        return False

    valid, issues = validate_args(cmd, args, cmd_defs)
    if not valid:
        for issue in issues:
            print(f"  {C.ERROR}\u26a0 {issue}{C.END}")
        return False

    return True


# -- Main Loop ----------------------------------------------------------------

def main():
    csp = CSPConfig()

    # Load command schema for pre-send validation
    cmd_defs = load_command_defs(CMD_DEFS_PATH)

    banner("MAVERIC TX", VERSION)
    print()
    info_line("ZMQ", ZMQ_ADDR)
    info_line("Origin", f"GS ({GS_NODE})")
    info_line("Framing", "KISS + AX100 ASM+Golay")
    if cmd_defs:
        info_line("Schema", f"{len(cmd_defs)} commands from {CMD_DEFS_PATH}")
    else:
        info_line("Schema", "none (no validation)")

    ctx, sock = init_zmq_pub(ZMQ_ADDR)
    logf, logpath = open_log()
    print(f" {C.DIM}Log{C.END}         {logpath}")
    print()
    csp_show(csp)
    print(f"\n {C.DIM}Type a command or 'help'{C.END}\n")

    n = 0
    last = None
    batch = []

    def max_payload():
        return MAX_RS_PAYLOAD - csp.overhead()

    try:
        while True:
            prompt = (f"  {C.WARNING}+({len(batch)}){C.END}{C.LABEL}\u25b6{C.END} "
                      if batch else f"  {C.LABEL}\u25b6{C.END} ")
            try:
                line = input(prompt).strip()
            except EOFError:
                break
            if not line:
                continue
            low = line.lower()

            if low in ('q', 'quit', 'exit'):
                if batch:
                    print(f"  {C.WARNING}Discarding {len(batch)} queued commands{C.END}")
                break

            if low == 'help':
                print(f"""
  {C.BOLD}Single command:{C.END}
    {C.LABEL}<dest> <cmd> [args]{C.END}     send immediately

  {C.BOLD}Batch commands:{C.END}
    {C.LABEL}+ <dest> <cmd> [args]{C.END}   queue a command
    {C.LABEL}send{C.END}                    transmit all queued
    {C.LABEL}batch{C.END}                   show queue
    {C.LABEL}clear{C.END}                   discard queue

  {C.BOLD}CSP config:{C.END}
    {C.LABEL}csp{C.END}                     show CSP settings
    {C.LABEL}csp on/off{C.END}              enable/disable
    {C.LABEL}csp dest N{C.END}              set destination
    {C.LABEL}csp dport N{C.END}             set destination port

  {C.BOLD}Other:{C.END}
    {C.LABEL}!!{C.END}                      repeat last command
    {C.LABEL}nodes{C.END}                   list node IDs
    {C.LABEL}raw <hex>{C.END}               send raw hex bytes
    {C.LABEL}q{C.END}                       quit
""")
                continue

            if low == 'nodes':
                print(f"\n  {C.BOLD}Node Addresses:{C.END}")
                for nid in sorted(NODE_NAMES):
                    tag = f" {C.SUCCESS}<- you{C.END}" if nid == GS_NODE else ""
                    print(f"    {nid} = {C.BOLD}{NODE_NAMES[nid]}{C.END}{tag}")
                print()
                continue

            if low == 'csp' or low.startswith('csp '):
                csp_handle(csp, line[3:].strip() if len(line) > 3 else "")
                continue

            if low == 'batch':
                if not batch:
                    print(f"  {C.DIM}batch is empty{C.END}")
                else:
                    total = sum(len(k) for _, _, _, k in batch)
                    print(f"\n  {C.BOLD}Batch Queue{C.END}  "
                          f"{C.DIM}{len(batch)} commands, {total}B + {csp.overhead()}B CSP{C.END}")
                    for i, (d, c, a, k) in enumerate(batch):
                        print(f"    {C.DIM}{i+1}.{C.END} {C.BOLD}{node_label(d)}{C.END}  "
                              f"{C.LABEL}{c}{C.END}  {a}  {C.DIM}({len(k)}B){C.END}")
                    print(f"  {C.DIM}{max_payload()-total}B remaining in frame{C.END}\n")
                continue

            if low == 'clear':
                if batch:
                    print(f"  {C.DIM}cleared {len(batch)} commands{C.END}")
                    batch.clear()
                else:
                    print(f"  {C.DIM}nothing to clear{C.END}")
                continue

            if low == 'send':
                if not batch:
                    print(f"  {C.ERROR}nothing queued -- use + to add commands{C.END}")
                    continue
                kiss_stream = bytearray()
                batch_info = []
                for d, c, a, k in batch:
                    kiss_stream.extend(k)
                    batch_info.append((d, c, a, len(k)))
                if len(kiss_stream) > max_payload():
                    print(f"  {C.ERROR}batch too large: {len(kiss_stream)}B > {max_payload()}B max{C.END}")
                    continue
                payload = csp.wrap(bytes(kiss_stream))
                n += 1
                send_pdu(sock, payload)
                render_batch(n, batch_info, payload, csp)
                log_tx(logf, n, [{"dest": d, "dest_lbl": NODE_NAMES.get(d, "?"),
                    "cmd": c, "args": a} for d, c, a, _ in batch], payload, csp.enabled)
                batch.clear()
                continue

            if line.startswith('+'):
                cmd_text = line[1:].strip()
                if not cmd_text:
                    print(f"  {C.ERROR}need: + <dest> <cmd> [args]{C.END}")
                    continue
                parsed = parse_cmd_line(cmd_text)
                if parsed is None:
                    print(f"  {C.ERROR}bad command{C.END}")
                    continue
                dest, cmd, args = parsed
                if not check_args(cmd, args, cmd_defs):
                    continue
                kiss, raw = build_kiss_cmd(dest, cmd, args)
                current = sum(len(k) for _, _, _, k in batch)
                if current + len(kiss) > max_payload():
                    print(f"  {C.ERROR}won't fit: {current+len(kiss)}B > {max_payload()}B{C.END}")
                    continue
                batch.append((dest, cmd, args, kiss))
                print(f"  {C.DIM}queued #{len(batch)}: {node_label(dest)} {cmd} {args} "
                      f"({len(kiss)}B, {max_payload()-current-len(kiss)}B remaining){C.END}")
                continue

            if low in ('!!', 'last'):
                if last is None:
                    print(f"  {C.DIM}nothing to repeat{C.END}")
                    continue
                dest, cmd, args = last
            elif low.startswith('raw '):
                try:
                    raw_bytes = bytes.fromhex(line[4:].replace(' ', ''))
                except ValueError:
                    print(f"  {C.ERROR}bad hex{C.END}")
                    continue
                n += 1
                send_pdu(sock, raw_bytes)
                render_raw(n, raw_bytes)
                continue
            else:
                parsed = parse_cmd_line(line)
                if parsed is None:
                    print(f"  {C.ERROR}need: <dest> <cmd> [args]{C.END}")
                    continue
                dest, cmd, args = parsed
                last = (dest, cmd, args)

            # Validate against schema before sending
            if not check_args(cmd, args, cmd_defs):
                continue

            kiss, raw_cmd = build_kiss_cmd(dest, cmd, args)
            if len(kiss) + csp.overhead() > MAX_RS_PAYLOAD:
                print(f"  {C.ERROR}command too large{C.END}")
                continue
            payload = csp.wrap(kiss)
            n += 1
            send_pdu(sock, payload)
            render_single(n, dest, cmd, args, payload, csp, raw_cmd)
            log_tx(logf, n, [{"dest": dest, "dest_lbl": NODE_NAMES.get(dest, "?"),
                "cmd": cmd, "args": args}], payload, csp.enabled)

    except KeyboardInterrupt:
        if batch:
            print(f"\n  {C.WARNING}Discarding {len(batch)} queued commands{C.END}")

    print(f"\n")
    separator()
    print(f"  {C.BOLD}Session ended{C.END}")
    print(f"  Transmitted:  {C.BOLD}{n}{C.END}")
    separator()
    print(f"  {C.DIM}{logpath}{C.END}")
    print()
    logf.close()
    sock.close()
    ctx.term()


if __name__ == "__main__":
    main()