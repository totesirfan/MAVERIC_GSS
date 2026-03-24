"""
mav_gss_lib.transport -- ZMQ + PMT Transport Layer

PUB/SUB sockets and PMT PDU serialization for both RX (subscribe to
decoded frames from gr-satellites) and TX (publish command PDUs to
the AX.25 encoder flowgraph).

Author:  Irfan Annuar - USC ISI SERC
"""

import sys
import time
import zmq
import pmt
from datetime import datetime


def init_zmq_sub(addr, timeout_ms=200):
    """Initialize ZMQ SUB socket for receiving PDUs (RX).

    Uses PUB/SUB instead of PUSH/PULL because PUSH/PULL round-robins
    messages across consumers -- stale processes from previous runs
    silently steal half the packets.
    """
    context = zmq.Context()
    sock = context.socket(zmq.SUB)
    sock.setsockopt(zmq.SUBSCRIBE, b"")
    sock.setsockopt(zmq.RCVHWM, 10000)
    sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sock.connect(addr)
    return context, sock


def init_zmq_pub(addr, settle_ms=300):
    """Initialize ZMQ PUB socket for sending PDUs (TX).

    Binds and pauses briefly so subscribers have time to connect
    before the first message is published.
    """
    context = zmq.Context()
    sock = context.socket(zmq.PUB)
    sock.bind(addr)
    time.sleep(settle_ms / 1000.0)
    return context, sock


def receive_pdu(sock, on_error=None):
    """Receive and deserialize one PMT PDU from ZMQ.

    Returns (meta_dict, raw_bytes), or None on timeout.
    Malformed messages are caught and logged via on_error callback
    (or to stderr if no callback provided).
    """
    try:
        msg = sock.recv()
    except zmq.Again:
        return None

    try:
        pdu = pmt.deserialize_str(msg)
        meta = pmt.to_python(pmt.car(pdu))
        raw = bytes(pmt.u8vector_elements(pmt.cdr(pdu)))
    except Exception as e:
        ts = datetime.now().astimezone().strftime("%H:%M:%S")
        error_msg = f"[{ts}] PMT deserialize error: {e}"
        if on_error:
            on_error(error_msg)
        else:
            print(f"\n  [ERROR] {error_msg}", file=sys.stderr)
        return None

    if meta is None:
        meta = {}
    return meta, raw


def send_pdu(sock, payload):
    """Send payload bytes as a PMT PDU over ZMQ."""
    meta = pmt.make_dict()
    vec = pmt.init_u8vector(len(payload), list(payload))
    sock.send(pmt.serialize_str(pmt.cons(meta, vec)))