#!/usr/bin/env python3
"""Fake flight-side responder for com_ping verification testing.

Subscribes to the GSS /ws/tx event stream (which broadcasts a structured
"sent" event carrying cleartext cmd_id + dest — no radio decode needed)
and publishes exactly the right response sequence on the RX ZMQ socket
for the destination that just went out. No duplicate ACKs, no rogue
cross-destination RES.

Routing:
  com_ping → LPPM: UPPM ACK ≈0.4s → LPPM ACK ≈1.2s → LPPM RES "pong" ≈2.5s
  com_ping → UPPM: UPPM ACK ≈0.4s →                 → UPPM RES "pong" ≈2.5s
  com_ping → HLNV: UPPM ACK ≈0.4s → HLNV ACK ≈1.2s → HLNV RES "pong" ≈2.5s
  com_ping → ASTR: UPPM ACK ≈0.4s → ASTR ACK ≈1.2s → ASTR RES "pong" ≈2.5s
  com_ping → EPS : UPPM ACK ≈0.4s → (EPS never acks) → EPS RES "pong" ≈2.5s

Other commands are ignored. Run BEFORE sending a command:

    conda activate
    python3 scripts/fake_flight_com_ping.py

Options:
    --only LPPM       respond only to that dest
    --cmd eps_sw      also treat this cmd_id as a "com_ping"-style exerciser
    --http URL        non-default GSS URL (default http://127.0.0.1:8080)
    --rx-addr ADDR    non-default RX PUB bind (default reads gss.yml)

Stops on Ctrl-C.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mav_gss_lib.config import load_split_config
from mav_gss_lib.protocols.csp import CSPConfig
from mav_gss_lib.missions.maveric.defaults import NODES, PTYPES
from mav_gss_lib.missions.maveric.wire_format import build_cmd_raw
from mav_gss_lib.transport import init_zmq_pub, send_pdu

NODE_ID = {name: nid for nid, name in NODES.items()}
PTYPE_ID = {name: pid for pid, name in PTYPES.items()}

GS   = NODE_ID["GS"]
UPPM = NODE_ID["UPPM"]
LPPM = NODE_ID["LPPM"]
EPS  = NODE_ID["EPS"]
HLNV = NODE_ID["HLNV"]
ASTR = NODE_ID["ASTR"]
ACK  = PTYPE_ID["ACK"]
RES  = PTYPE_ID["RES"]


# Per-dest flow: (second_ack_source_or_None, res_source).
# UPPM is always the gateway-ack source — emitted for every dest except FTDI.
FLOWS: dict[str, tuple[int | None, int]] = {
    "LPPM": (LPPM, LPPM),
    "UPPM": (None, UPPM),   # UPPM is both gateway and responder
    "HLNV": (HLNV, HLNV),
    "ASTR": (ASTR, ASTR),
    "EPS":  (None, EPS),    # EPS has no ack, only RES
}


def _build_response(src: int, ptype: int, cmd_id: str, args: str = "") -> bytes:
    """CSP-wrapped CommandFrame from flight → GS."""
    csp = CSPConfig()
    csp.src = 8; csp.dest = 0; csp.dport = 24; csp.sport = 0
    frame = build_cmd_raw(src=src, dest=GS, cmd=cmd_id, args=args, echo=0, ptype=ptype)
    return csp.wrap(bytes(frame))


def _publish(sock, payload: bytes, label: str) -> None:
    ts = time.strftime("%H:%M:%S")
    ok = send_pdu(sock, payload)
    print(f"  [{ts}] → {label} ({len(payload)}B) {'ok' if ok else 'FAIL'}")


async def respond(pub_sock, cmd_id: str, dest: str, exercised_cmds: set[str]) -> None:
    """Fire the canonical response sequence for a given (cmd_id, dest)."""
    if cmd_id not in exercised_cmds:
        return
    dest_u = (dest or "").upper()
    if dest_u not in FLOWS:
        return
    second_ack_src, res_src = FLOWS[dest_u]

    # UPPM gateway ACK (always fires except for FTDI, which isn't in FLOWS).
    await asyncio.sleep(0.4)
    _publish(pub_sock, _build_response(UPPM, ACK, cmd_id),
             f"UPPM ACK  ({cmd_id} → {dest_u})")

    # Destination ACK for multi-hop nodes (LPPM / HLNV / ASTR).
    if second_ack_src is not None:
        await asyncio.sleep(0.8)
        _publish(pub_sock, _build_response(second_ack_src, ACK, cmd_id),
                 f"{dest_u} ACK")

    # Response.
    await asyncio.sleep(1.3)
    _publish(pub_sock, _build_response(res_src, RES, cmd_id, "pong"),
             f"{dest_u} RES 'pong'")


async def run(http_base: str, ws_base: str, rx_addr: str,
              only: str, exercised: set[str]) -> int:
    try:
        with urlopen(f"{http_base}/api/status", timeout=5) as resp:
            status = json.loads(resp.read())
        token = status.get("auth_token")
    except Exception as exc:
        print(f"ERROR: cannot reach {http_base}/api/status — is MAV_WEB.py running?\n  {exc}",
              file=sys.stderr)
        return 1
    if not token:
        print("ERROR: /api/status returned no auth_token", file=sys.stderr)
        return 1

    try:
        import websockets
    except ImportError:
        print("ERROR: 'websockets' package is required (it ships with uvicorn[standard])",
              file=sys.stderr)
        return 1

    pub_ctx, pub_sock, pub_mon = init_zmq_pub(rx_addr)
    uri = f"{ws_base}/ws/tx?token={token}"
    print(f"fake_flight_com_ping")
    print(f"  /ws/tx  ← {uri}")
    print(f"  downlink → {rx_addr}")
    print(f"  only: {only}   exercised cmd_ids: {sorted(exercised)}")
    print(f"  Ctrl-C to stop.\n")

    try:
        async with websockets.connect(uri, max_size=2**24) as ws:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if msg.get("type") != "sent":
                    continue
                data = msg.get("data") or {}
                payload = data.get("payload") or {}
                cmd_id = payload.get("cmd_id", "")
                dest = (payload.get("dest") or "").upper()
                if only != "ANY" and dest != only:
                    print(f"[{time.strftime('%H:%M:%S')}] skip {cmd_id} → {dest} (only={only})")
                    continue
                print(f"[{time.strftime('%H:%M:%S')}] ↑ sent {cmd_id} → {dest}")
                asyncio.create_task(respond(pub_sock, cmd_id, dest, exercised))
    except KeyboardInterrupt:
        print("\nstopped.")
    except Exception as exc:
        print(f"\nWS error: {exc}", file=sys.stderr)
    finally:
        try:
            pub_mon.close(); pub_sock.close(); pub_ctx.term()
        except Exception:
            pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fake flight-side responder for com_ping verification testing.",
    )
    parser.add_argument("--http", default="http://127.0.0.1:8080",
                        help="GSS HTTP base URL (default: http://127.0.0.1:8080)")
    parser.add_argument("--rx-addr", default=None,
                        help="RX PUB address (default: read from gss.yml)")
    parser.add_argument("--only", default="any",
                        choices=["any", "LPPM", "UPPM", "HLNV", "ASTR", "EPS",
                                 "lppm", "uppm", "hlnv", "astr", "eps"],
                        help="Respond only to sends targeting this dest (default: any)")
    parser.add_argument("--cmd", action="append", default=None,
                        help="Additional cmd_id to treat as com_ping-style exerciser "
                             "(repeatable). Default exercises only 'com_ping'.")
    args = parser.parse_args()

    exercised = {"com_ping"}
    if args.cmd:
        exercised.update(args.cmd)

    platform_cfg, _mid, _mcfg = load_split_config()
    rx_addr = args.rx_addr or platform_cfg["rx"]["zmq_addr"]
    http_base = args.http.rstrip("/")
    ws_base = http_base.replace("http://", "ws://").replace("https://", "wss://")

    return asyncio.run(run(http_base, ws_base, rx_addr, args.only.upper(), exercised))


if __name__ == "__main__":
    sys.exit(main())
