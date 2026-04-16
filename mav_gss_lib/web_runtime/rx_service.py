"""
mav_gss_lib.web_runtime.rx_service -- RX Service

Owns the RX side of the web runtime: ZMQ SUB → pipeline → log → WS broadcast.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import deque
from queue import Empty, Queue
from typing import TYPE_CHECKING

from mav_gss_lib.parsing import RxPipeline, build_rx_log_record
from mav_gss_lib.protocols.frame_detect import is_noise_frame
from mav_gss_lib.transport import SUB_STATUS, init_zmq_sub, poll_monitor, receive_pdu, zmq_cleanup

from ._broadcast import broadcast_safe

if TYPE_CHECKING:
    from .state import WebRuntime


class RxService:
    """Own the RX side of the web runtime: ZMQ -> parse -> log -> broadcast."""

    def __init__(self, runtime: "WebRuntime") -> None:
        self.runtime = runtime
        self.status = ["OFFLINE"]
        self.packets: deque = deque(maxlen=runtime.max_packets)
        self.queue: Queue = Queue()
        self.stop = threading.Event()
        self.broadcast_stop = False
        self.clients: list = []
        self.lock = threading.Lock()
        self.log = None
        self.thread_handle: threading.Thread | None = None
        self.broadcast_task = None
        self.pipeline = RxPipeline(runtime.adapter, {})
        self.last_rx_at: float = 0.0
        self._was_traffic_active: bool = False

    def _should_drop_rx(self, now: float) -> bool:
        """Return True if *now* is inside the TX→RX blackout window.

        Reads ``runtime.tx_blackout_until`` without locking — plain float
        reads/writes are GIL-atomic on CPython, which is sufficient here.
        Matches a real deaf radio: the packet is dropped before the pipeline
        sees it, so rate/silence counters behave as if nothing arrived.
        """
        return now < self.runtime.tx_blackout_until

    def _should_drop_noise(self, meta, raw: bytes) -> bool:
        """Return True for gr-satellites AX.25 noise frames.

        Delegates to is_noise_frame after resolving the frame type via
        the active adapter. Mirrors _should_drop_rx: called before any
        state mutation so a dropped frame produces no side effects.
        """
        frame_type = self.runtime.adapter.detect_frame_type(meta)
        return is_noise_frame(frame_type, raw)

    def start_receiver(self) -> None:
        if self.thread_handle and self.thread_handle.is_alive():
            return
        self.stop.clear()
        self.thread_handle = threading.Thread(target=self._thread, daemon=True, name="maveric-rx-sub")
        self.thread_handle.start()

    def restart_receiver(self) -> None:
        self.stop.set()
        if self.thread_handle:
            self.thread_handle.join(timeout=1.0)
        self.stop.clear()
        self.thread_handle = threading.Thread(target=self._thread, daemon=True, name="maveric-rx-sub")
        self.thread_handle.start()

    def _thread(self) -> None:
        addr = self.runtime.cfg.get("rx", {}).get("zmq_addr", "tcp://127.0.0.1:52001")
        try:
            ctx, sock, monitor = init_zmq_sub(addr)
        except Exception as exc:
            logging.error("RX ZMQ init failed: %s", exc)
            return

        status = "OFFLINE"
        while not self.stop.is_set():
            status = poll_monitor(monitor, SUB_STATUS, status)
            self.status[0] = status
            result = receive_pdu(sock)
            if result is not None:
                if self._should_drop_rx(time.time()):
                    continue  # deaf during TX→RX blackout window
                self.queue.put((self.runtime.session.generation, *result))

        zmq_cleanup(monitor, SUB_STATUS, status, sock, ctx)

    async def broadcast(self, msg):
        """Broadcast one JSON-serializable message to all RX websocket clients."""
        text = json.dumps(msg) if isinstance(msg, dict) else msg
        await broadcast_safe(self.clients, self.lock, text)

    async def broadcast_loop(self) -> None:
        """Drain received packets and push packet/status updates to clients."""
        version = self.runtime.cfg.get("general", {}).get("version", "")
        last_status_push = 0.0
        while True:
            drained = 0
            while True:
                try:
                    item_gen, meta, raw = self.queue.get_nowait()
                except Empty:
                    break
                if item_gen < self.runtime.session.generation:
                    continue
                if self._should_drop_noise(meta, raw):
                    continue  # gr-satellites noise — behave as if never received
                pkt = self.pipeline.process(meta, raw)
                record = build_rx_log_record(pkt, version, meta, self.runtime.adapter)
                try:
                    if self.log:
                        self.log.write_jsonl(record)
                        self.log.write_packet(pkt, adapter=self.runtime.adapter)
                except Exception as exc:
                    logging.warning("RX log write failed: %s", exc)
                pkt_json = {
                    "num": pkt.pkt_num,
                    "time": pkt.gs_ts_short,
                    "time_utc": pkt.gs_ts,
                    "frame": pkt.frame_type,
                    "size": len(pkt.raw),
                    "raw_hex": pkt.raw.hex(),
                    "warnings": pkt.warnings,
                    "is_echo": pkt.is_uplink_echo,
                    "is_dup": pkt.is_dup,
                    "is_unknown": pkt.is_unknown,
                    "_rendering": record["_rendering"],
                }
                self.packets.append(pkt_json)
                msg = json.dumps({"type": "packet", "data": pkt_json})
                await broadcast_safe(self.clients, self.lock, msg)

                # Plugin hook — let adapter inject extra WS messages
                hook = getattr(self.runtime.adapter, 'on_packet_received', None)
                if hook:
                    try:
                        extra_msgs = hook(pkt)
                        if extra_msgs:
                            for extra in extra_msgs:
                                extra_text = json.dumps(extra)
                                await broadcast_safe(self.clients, self.lock, extra_text)
                    except Exception as exc:
                        logging.warning("on_packet_received hook failed: %s", exc)

                # Track last RX time and detect inactive→active transition
                self.last_rx_at = time.time()
                if not self._was_traffic_active:
                    self._was_traffic_active = True
                    traffic_msg = json.dumps({"type": "traffic_status", "active": True})
                    await broadcast_safe(self.runtime.session_clients, self.runtime.session_lock, traffic_msg)

                drained += 1

            if self.broadcast_stop:
                if drained == 0:
                    return
                continue

            now = time.time()
            # Detect active→inactive traffic transition (10s timeout)
            if self._was_traffic_active and self.last_rx_at > 0 and (now - self.last_rx_at) > 10.0:
                self._was_traffic_active = False
                traffic_msg = json.dumps({"type": "traffic_status", "active": False})
                await broadcast_safe(self.runtime.session_clients, self.runtime.session_lock, traffic_msg)

            if drained == 0 and now - last_status_push > 1.0:
                last_status_push = now
                cutoff = now - 5
                recent = sum(1 for t in self.pipeline.pkt_times if t > cutoff)
                pkt_rate = round(recent * 12, 1) if recent else 0
                silence_s = round(now - self.pipeline.last_arrival, 1) if self.pipeline.last_arrival else 0
                status_msg = json.dumps(
                    {
                        "type": "status",
                        "zmq": self.status[0],
                        "pkt_rate": pkt_rate,
                        "silence_s": silence_s,
                        "packet_count": self.pipeline.packet_count,
                    }
                )
                await broadcast_safe(self.clients, self.lock, status_msg)

            await asyncio.sleep(0.05)
