"""Inject a real eps_hk RES fixture into the live RX pipeline for preview.

Publishes the captured 120-byte CSP payload from downlink_20260414_182003.jsonl
pkt 11 as a PMT PDU on the RX ZMQ address that MAV_WEB.py's RX service subscribes
to. The dashboard sees it as a live packet, runs it through the real parser +
rendering + broadcast path, and the browser shows the new "EPS_HK" detail block.

Usage:
    # Terminal 1
    conda activate gnuradio
    python3 MAV_WEB.py

    # Terminal 2 (after the dashboard has opened in the browser)
    conda activate gnuradio
    python3 scripts/preview_eps_hk.py

    # Click the new eps_hk packet in the RX list → see the EPS_HK block.
    # Ctrl+C to stop injecting.

If you want to run one-shot, pass --once:
    python3 scripts/preview_eps_hk.py --once
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.config import load_gss_config
from mav_gss_lib.transport import init_zmq_pub, send_pdu


# Real packet 11 from logs/json/downlink_20260414_182003.jsonl — 120 bytes,
# CSP v1 header + eps_hk RES + 96 bytes of int16 HK values + CRCs.
FIXTURE_HEX = (
    "900600000206000206606570735f686b00b4000000e823220088266c"
    "1d2c2134023f00f50c8c00f40176132600c8000000feff00000000fe"
    "ff00000000feff00000000feff00000000000000000000feff000000"
    "00feff00000000feff00000000feff00000000000000000000feff00"
    "000040a33bd839ce"
)

# The transmitter string is what frame_detect.py keys off to pick
# "ASM+GOLAY" (and then normalize_frame returns the raw unchanged).
_TX_META_BYTES = b"9k6 FSK AX100 ASM+Golay downlink (preview injection)"


def _build_kiss_pdu(meta_str: bytes, raw: bytes) -> tuple[dict, bytes]:
    """The PMT PDU the RX ZMQ socket expects is built by send_pdu itself —
    this helper just packages the (meta_dict, raw_bytes) pair that will be
    serialized. Kept separate for clarity."""
    return ({"transmitter": meta_str.decode("ascii", errors="replace")}, raw)


def main() -> int:
    ap = argparse.ArgumentParser(description="Inject eps_hk preview packet into MAV_WEB RX.")
    ap.add_argument("--once", action="store_true", help="Publish one packet and exit.")
    ap.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Seconds between publishes when not --once (default 2.0).",
    )
    args = ap.parse_args()

    cfg = load_gss_config()
    addr = cfg.get("rx", {}).get("zmq_addr", "tcp://127.0.0.1:52001")
    print(f"[preview] binding ZMQ PUB on {addr}")
    print(f"[preview] make sure MAV_WEB.py is already running and its RX status is ONLINE.")

    import pmt
    ctx, sock, _monitor = init_zmq_pub(addr, settle_ms=400)

    raw = bytes.fromhex(FIXTURE_HEX)
    # send_pdu in transport.py writes meta=pmt.make_dict() (empty). Our
    # pipeline only reads meta["transmitter"], so we build a custom PDU
    # here that puts the transmitter string into the meta dict.
    def _publish_once() -> None:
        meta = pmt.make_dict()
        meta = pmt.dict_add(meta, pmt.intern("transmitter"),
                            pmt.intern(_TX_META_BYTES.decode("ascii")))
        vec = pmt.init_u8vector(len(raw), list(raw))
        sock.send(pmt.serialize_str(pmt.cons(meta, vec)))

    try:
        if args.once:
            _publish_once()
            print("[preview] published 1 packet")
            time.sleep(0.5)  # give the SUB side a moment to drain
            return 0

        print(f"[preview] publishing every {args.interval}s — Ctrl+C to stop")
        count = 0
        while True:
            _publish_once()
            count += 1
            print(f"[preview] published packet #{count}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[preview] stopped.")
        return 0
    finally:
        sock.close(linger=0)
        ctx.term()


if __name__ == "__main__":
    raise SystemExit(main())
