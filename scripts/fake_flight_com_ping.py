#!/usr/bin/env python3
"""Fake flight-side responder for com_ping verification testing.

Subscribes to the GSS uplink PUB socket and, on each observed uplink PDU,
publishes scripted "flight" responses that exercise the command-verification
admission gate and tick strip:

  com_ping → LPPM: UPPM ACK (≈0.4s) → LPPM ACK (≈1.2s) → LPPM RES "pong" (≈2.5s)
  com_ping → EPS : UPPM ACK (≈0.4s) → EPS  RES "pong" (≈2.5s)

It fires BOTH response flows on every uplink. The GSS verifier registry
only matches responses whose (cmd_id, src, ptype) corresponds to a
verifier in an open instance's VerifierSet — so the wrong flow is
silently ignored. No radio decode is attempted; this runs entirely via
ZMQ + MAVERIC's Python framer and works with zero GNU Radio / libfec
dependency on the test host.

Run this BEFORE launching MAV_WEB.py (or just before sending a com_ping):

    conda activate
    python3 scripts/fake_flight_com_ping.py

Stops on Ctrl-C.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mav_gss_lib.config import load_split_config
from mav_gss_lib.protocols.csp import CSPConfig
from mav_gss_lib.missions.maveric.defaults import NODES, PTYPES
from mav_gss_lib.missions.maveric.wire_format import build_cmd_raw
from mav_gss_lib.transport import init_zmq_sub, init_zmq_pub, receive_pdu, send_pdu

NODE_ID = {name: nid for nid, name in NODES.items()}
PTYPE_ID = {name: pid for pid, name in PTYPES.items()}

GS = NODE_ID["GS"]
UPPM = NODE_ID["UPPM"]
LPPM = NODE_ID["LPPM"]
EPS = NODE_ID["EPS"]
ACK = PTYPE_ID["ACK"]
RES = PTYPE_ID["RES"]


def _csp_for_downlink() -> CSPConfig:
    """CSP config for flight → GS packets.

    Source/dest are flipped from the uplink default (operator config
    is GS=0, flight=8; we send src=flight, dest=GS). The platform
    only checks src ≤ 20 and dest ≤ 20 for plausibility, so exact
    numeric values do not need to match gss.yml.
    """
    cfg = CSPConfig()
    cfg.src = 8
    cfg.dest = 0
    cfg.dport = 24
    cfg.sport = 0
    return cfg


def _wrap(cmd_frame: bytes, csp: CSPConfig) -> bytes:
    """Wrap a CommandFrame in CSP v1 (header + optional CRC-32C)."""
    return csp.wrap(cmd_frame)


def _build_response(src: int, ptype: int, cmd_id: str, args: str = "") -> bytes:
    """Build one response PDU: CSP v1 + CommandFrame."""
    cmd = build_cmd_raw(src=src, dest=GS, cmd=cmd_id, args=args, echo=0, ptype=ptype)
    return _wrap(bytes(cmd), _csp_for_downlink())


def _publish(sock, payload: bytes, label: str) -> None:
    ts = time.strftime("%H:%M:%S")
    ok = send_pdu(sock, payload)
    print(f"  [{ts}] → {label} ({len(payload)}B) {'ok' if ok else 'FAIL'}")


def fire_lppm_flow(pub_sock) -> None:
    """UPPM ACK → LPPM ACK → LPPM RES 'pong'."""
    time.sleep(0.4)
    _publish(pub_sock, _build_response(UPPM, ACK, "com_ping"),      "UPPM ACK  (LPPM target)")
    time.sleep(0.8)
    _publish(pub_sock, _build_response(LPPM, ACK, "com_ping"),      "LPPM ACK")
    time.sleep(1.3)
    _publish(pub_sock, _build_response(LPPM, RES, "com_ping", "pong"), "LPPM RES 'pong'")


def fire_eps_flow(pub_sock) -> None:
    """UPPM ACK → EPS RES 'pong' (EPS never acks on its own)."""
    time.sleep(0.4)
    _publish(pub_sock, _build_response(UPPM, ACK, "com_ping"),      "UPPM ACK  (EPS  target)")
    time.sleep(2.1)
    _publish(pub_sock, _build_response(EPS, RES, "com_ping", "pong"), "EPS  RES 'pong'")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tx-addr", default=None,
        help="TX PUB address to subscribe to (default: read from gss.yml)",
    )
    parser.add_argument(
        "--rx-addr", default=None,
        help="RX PUB address to publish on (default: read from gss.yml)",
    )
    parser.add_argument(
        "--only", choices=("lppm", "eps", "both"), default="both",
        help="Which response flow(s) to fire on each observed uplink (default: both)",
    )
    args = parser.parse_args()

    platform_cfg, _mid, _mcfg = load_split_config()
    tx_addr = args.tx_addr or platform_cfg["tx"]["zmq_addr"]
    rx_addr = args.rx_addr or platform_cfg["rx"]["zmq_addr"]

    print(f"fake_flight_com_ping")
    print(f"  subscribe (uplink)  ← {tx_addr}")
    print(f"  publish   (downlink)→ {rx_addr}")
    print(f"  flow(s): {args.only}")
    print(f"  Ctrl-C to stop.\n")

    sub_ctx, sub_sock, sub_mon = init_zmq_sub(tx_addr, timeout_ms=500)
    pub_ctx, pub_sock, pub_mon = init_zmq_pub(rx_addr)

    try:
        while True:
            result = receive_pdu(sub_sock)
            if result is None:
                continue
            meta, raw = result
            ts = time.strftime("%H:%M:%S")
            print(f"[{ts}] ↑ uplink observed ({len(raw)}B) meta={dict(meta) if meta else {}}")

            # Fire flow(s) on independent threads so LPPM + EPS can run
            # concurrently when both are selected, matching realistic
            # multi-target batch behavior.
            threads = []
            if args.only in ("lppm", "both"):
                t = threading.Thread(target=fire_lppm_flow, args=(pub_sock,), daemon=True)
                threads.append(t); t.start()
            if args.only in ("eps", "both"):
                t = threading.Thread(target=fire_eps_flow, args=(pub_sock,), daemon=True)
                threads.append(t); t.start()
            for t in threads:
                t.join()
            print()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        try:
            sub_mon.close(); sub_sock.close(); sub_ctx.term()
            pub_mon.close(); pub_sock.close(); pub_ctx.term()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
