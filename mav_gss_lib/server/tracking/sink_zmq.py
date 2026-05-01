"""ZMQ PUB sink delivering DopplerCorrection center frequencies to the GNU
Radio flowgraph. RX and TX are published on separate PUB sockets so each
maps cleanly to the matching uhd_usrp_{source,sink}.command port in MAV_DUO."""

from __future__ import annotations

import threading

import pmt
import zmq

from mav_gss_lib.platform.tracking.models import DopplerCorrection


class ZmqDopplerSink:
    def __init__(self, *, rx_addr: str, tx_addr: str) -> None:
        self._lock = threading.Lock()
        self._closed = False
        self._ctx = zmq.Context.instance()
        self._rx = self._ctx.socket(zmq.PUB)
        self._rx.setsockopt(zmq.LINGER, 0)
        self._rx.bind(rx_addr)
        try:
            self._tx = self._ctx.socket(zmq.PUB)
            self._tx.setsockopt(zmq.LINGER, 0)
            self._tx.bind(tx_addr)
        except Exception:
            self._rx.close(linger=0)
            raise

    @property
    def rx_endpoint(self) -> str:
        return self._rx.getsockopt(zmq.LAST_ENDPOINT).decode()

    @property
    def tx_endpoint(self) -> str:
        return self._tx.getsockopt(zmq.LAST_ENDPOINT).decode()

    def publish(self, correction: DopplerCorrection) -> None:
        rx_payload = _freq_message(correction.rx_tune_hz)
        tx_payload = _freq_message(correction.tx_tune_hz)
        with self._lock:
            if self._closed:
                return
            self._rx.send(rx_payload, flags=zmq.NOBLOCK)
            self._tx.send(tx_payload, flags=zmq.NOBLOCK)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._rx.close(linger=0)
            finally:
                self._tx.close(linger=0)


def _freq_message(freq_hz: float) -> bytes:
    msg = pmt.make_dict()
    msg = pmt.dict_add(msg, pmt.intern("freq"), pmt.from_double(float(freq_hz)))
    return pmt.serialize_str(msg)


__all__ = ["ZmqDopplerSink"]
