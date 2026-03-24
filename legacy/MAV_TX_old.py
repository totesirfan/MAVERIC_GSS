"""
MAV_TX -- MAVERIC Command Terminal

Uplink command interface for the MAVERIC CubeSat mission. Builds raw
commands with a CSP v1 header + CRC-32C and publishes them as PMT PDUs
over ZMQ for the AX.25 encoder flowgraph in GNU Radio.

Output PDU ready for HDLC framer:
    [AX.25 header 16B][CSP v1 header 4B][command + CRC-16][CRC-32C 4B BE]

Single command:    EPS PING
Batch commands:    + EPS SET_MODE auto / + EPS SET_VOLTAGE 3.3 / send
                   (each queued command is sent as its own packet)
CSP config:        csp / csp dest 8 / csp dport 24
AX.25 config:      ax25 / ax25 dest WS9XSW / ax25 src WM2XBB

When maveric_commands.yml is present, args are validated against the schema
before sending. Type mismatches and missing args produce warnings but do
not block transmission -- the operator always has final say.

Requires GNU Radio flowgraph:
    ZMQ SUB Source (:52002) -> HDLC Framer -> GFSK Mod -> USRP Sink
    (PDU already includes AX.25 header — no custom GRC blocks needed)

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
    build_cmd_raw, AX25Config, CSPConfig,
    load_command_defs, validate_args,
)
from mav_gss_lib.display import (
    C, TOP, MID, BOT, INN_W,
    row, strip_ansi, wrap_ascii, wrap_hex,
    banner, info_line, separator,
)
from mav_gss_lib.transport import init_zmq_pub, send_pdu

# -- Config -------------------------------------------------------------------

VERSION  = "3.2"
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


def log_tx(f, n, dest, cmd, args, payload, csp_enabled):
    rec = {
        "n": n,
        "ts": datetime.now().astimezone().isoformat(),
        "dest": dest,
        "dest_lbl": NODE_NAMES.get(dest, "?"),
        "cmd": cmd,
        "args": args,
        "hex": payload.hex(),
        "len": len(payload),
        "csp": csp_enabled,
    }
    f.write(json.dumps(rec) + "\n")
    f.flush()


# -- AX.25 CLI ----------------------------------------------------------------

def ax25_show(ax25):
    state = f"{C.SUCCESS}enabled{C.END}" if ax25.enabled else f"{C.DIM}disabled{C.END}"
    print(f" {C.DIM}AX.25{C.END}       {state}  "
          f"{C.DIM}Dest:{ax25.dest_call}-{ax25.dest_ssid} "
          f"Src:{ax25.src_call}-{ax25.src_ssid}{C.END}")


def ax25_handle(ax25, args):
    if not args:
        ax25_show(ax25)
        return
    parts = args.split()
    cmd = parts[0].lower()
    if cmd == 'on':
        ax25.enabled = True
        print(f"  {C.SUCCESS}AX.25 header enabled{C.END}")
    elif cmd == 'off':
        ax25.enabled = False
        print(f"  {C.WARNING}AX.25 header disabled{C.END}")
    elif cmd == 'dest' and len(parts) > 1:
        ax25.dest_call = parts[1].upper()[:6]
        if len(parts) > 2 and parts[2].isdigit():
            ax25.dest_ssid = int(parts[2]) & 0x0F
        print(f"  AX.25 dest = {ax25.dest_call}-{ax25.dest_ssid}")
    elif cmd == 'src' and len(parts) > 1:
        ax25.src_call = parts[1].upper()[:6]
        if len(parts) > 2 and parts[2].isdigit():
            ax25.src_ssid = int(parts[2]) & 0x0F
        print(f"  AX.25 src = {ax25.src_call}-{ax25.src_ssid}")
    else:
        print(f"  {C.ERROR}ax25 [on|off|dest <call> [ssid]|src <call> [ssid]]{C.END}")


# -- CSP CLI ------------------------------------------------------------------

def csp_show(csp):
    hdr = csp.build_header()
    state = f"{C.SUCCESS}enabled{C.END}" if csp.enabled else f"{C.DIM}disabled{C.END}"
    print(f" {C.DIM}CSP V1{C.END}      {state}  "
          f"{C.DIM}Prio:{csp.prio} Src:{csp.src} Dest:{csp.dest} "
          f"DPort:{csp.dport} SPort:{csp.sport} Flags:0x{csp.flags:02X}{C.END}")
    overhead = csp.overhead()
    print(f" {C.DIM}CSP Bytes{C.END}   {hdr.hex(' ')}  "
          f"{C.DIM}({overhead}B overhead: 4B hdr + 4B CRC-32C){C.END}")


def csp_handle(csp, args):
    if not args:
        csp_show(csp)
        return
    parts = args.split()
    cmd = parts[0].lower()
    if cmd == 'on':
        csp.enabled = True
        print(f"  {C.SUCCESS}CSP header + CRC-32C enabled{C.END}")
    elif cmd == 'off':
        csp.enabled = False
        print(f"  {C.WARNING}CSP header + CRC-32C disabled{C.END}")
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
    csp_tag = f"  {C.DIM}[CSP+CRC32C]{C.END}" if csp.enabled else ""
    csp_tag_vis = len("  [CSP+CRC32C]") if csp.enabled else 0

    print(f"{C.DIM}{TOP}{C.END}")
    h_left = f"{C.BOLD}{C.SUCCESS}TX #{n}{C.END}    {C.SUCCESS}UPLINK{C.END}{csp_tag}"
    h_right = f"{C.DIM}{len(payload)} B payload{C.END}"
    h_lv = len(f"TX #{n}    UPLINK") + csp_tag_vis
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
    if csp.enabled:
        csp_crc32 = int.from_bytes(payload[-4:], 'big')
        print(row(f"  {C.DIM}CRC-32C{C.END}     {C.DIM}0x{csp_crc32:08x}{C.END}"))
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
    """Validate args against schema. Print warnings, return True to proceed."""
    valid, issues = validate_args(cmd, args, cmd_defs)
    if not valid:
        for issue in issues:
            print(f"  {C.WARNING}\u26a0 {issue}{C.END}")
    return True  # warnings only -- operator has final say


# -- Main Loop ----------------------------------------------------------------

def main():
    csp = CSPConfig()
    ax25 = AX25Config()

    # Load command schema for pre-send validation
    cmd_defs = load_command_defs(CMD_DEFS_PATH)

    banner("MAVERIC TX", VERSION)
    print()
    info_line("ZMQ", ZMQ_ADDR)
    info_line("Origin", f"GS ({GS_NODE})")
    info_line("Framing", "CSP v1 + CRC-32C → AX.25 → HDLC")
    if cmd_defs:
        info_line("Schema", f"{len(cmd_defs)} commands from {CMD_DEFS_PATH}")
    else:
        info_line("Schema", "none (no validation)")

    ctx, sock = init_zmq_pub(ZMQ_ADDR)
    logf, logpath = open_log()
    print(f" {C.DIM}Log{C.END}         {logpath}")
    print()
    csp_show(csp)
    ax25_show(ax25)
    print(f"\n {C.DIM}Type a command or 'help'{C.END}\n")

    n = 0
    last = None
    batch = []

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
    {C.LABEL}send{C.END}                    transmit queued (one per packet)
    {C.LABEL}batch{C.END}                   show queue
    {C.LABEL}clear{C.END}                   discard queue

  {C.BOLD}CSP config:{C.END}
    {C.LABEL}csp{C.END}                     show CSP settings
    {C.LABEL}csp on/off{C.END}              enable/disable
    {C.LABEL}csp dest N{C.END}              set destination
    {C.LABEL}csp dport N{C.END}             set destination port

  {C.BOLD}AX.25 config:{C.END}
    {C.LABEL}ax25{C.END}                    show AX.25 settings
    {C.LABEL}ax25 on/off{C.END}             enable/disable
    {C.LABEL}ax25 dest CALL [SSID]{C.END}   set dest callsign
    {C.LABEL}ax25 src  CALL [SSID]{C.END}   set src callsign

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

            if low == 'ax25' or low.startswith('ax25 '):
                ax25_handle(ax25, line[4:].strip() if len(line) > 4 else "")
                continue

            if low == 'batch':
                if not batch:
                    print(f"  {C.DIM}batch is empty{C.END}")
                else:
                    print(f"\n  {C.BOLD}Batch Queue{C.END}  "
                          f"{C.DIM}{len(batch)} commands (each sent as own packet){C.END}")
                    for i, (d, c, a, r) in enumerate(batch):
                        print(f"    {C.DIM}{i+1}.{C.END} {C.BOLD}{node_label(d)}{C.END}  "
                              f"{C.LABEL}{c}{C.END}  {a}  {C.DIM}({len(r)}B){C.END}")
                    print()
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
                num = len(batch)
                print(f"  {C.WARNING}sending {num} commands (one per packet)...{C.END}")
                for dest, cmd, args, raw_cmd in batch:
                    payload = ax25.wrap(csp.wrap(raw_cmd))
                    n += 1
                    send_pdu(sock, payload)
                    render_single(n, dest, cmd, args, payload, csp, raw_cmd)
                    log_tx(logf, n, dest, cmd, args, payload, csp.enabled)
                print(f"  {C.SUCCESS}batch complete: {num} packets sent{C.END}")
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
                check_args(cmd, args, cmd_defs)
                raw_cmd = build_cmd_raw(dest, cmd, args)
                if len(raw_cmd) + csp.overhead() + ax25.overhead() > MAX_RS_PAYLOAD:
                    print(f"  {C.ERROR}command too large{C.END}")
                    continue
                batch.append((dest, cmd, args, raw_cmd))
                print(f"  {C.DIM}queued #{len(batch)}: {node_label(dest)} {cmd} {args} "
                      f"({len(raw_cmd)}B){C.END}")
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

            # Validate args against schema before sending
            check_args(cmd, args, cmd_defs)

            raw_cmd = build_cmd_raw(dest, cmd, args)
            if len(raw_cmd) + csp.overhead() + ax25.overhead() > MAX_RS_PAYLOAD:
                print(f"  {C.ERROR}command too large{C.END}")
                continue
            payload = ax25.wrap(csp.wrap(raw_cmd))
            n += 1
            send_pdu(sock, payload)
            render_single(n, dest, cmd, args, payload, csp, raw_cmd)
            log_tx(logf, n, dest, cmd, args, payload, csp.enabled)

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