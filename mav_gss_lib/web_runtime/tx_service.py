"""
mav_gss_lib.web_runtime.tx_service -- TX Service

Owns the TX side of the web runtime: queue, send state, history, and ZMQ PUB.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Awaitable, Callable, NamedTuple

from mav_gss_lib.protocols.ax25 import build_ax25_gfsk_frame
from mav_gss_lib.transport import PUB_STATUS, init_zmq_pub, send_pdu, zmq_cleanup

from ._broadcast import broadcast_safe
from .tx_queue import QueueItem

if TYPE_CHECKING:
    from .state import WebRuntime


class _RunResult(NamedTuple):
    aborted: bool
    sent_delta: int


@dataclass
class _SendContext:
    """Per-run state shared across per-item handlers."""
    sent: int
    total: int
    sock: object
    uplink_mode: str
    default_delay: int
    blackout_ms: int
    send_csp: object
    send_ax25: object

try:
    from mav_gss_lib.protocols.golay import _GR_RS_OK, build_asm_golay_frame
    GOLAY_OK = _GR_RS_OK
except ImportError:
    GOLAY_OK = False


class TxService:
    """Own the TX side of the web runtime: queue, send state, and history."""

    def __init__(self, runtime: "WebRuntime") -> None:
        self.runtime = runtime
        self.clients: list = []
        self.lock = threading.Lock()
        self.log = None
        self.count = 0
        self.zmq_ctx = None
        self.zmq_sock = None
        self.zmq_monitor = None
        self.queue: list[QueueItem] = []
        self.history: list = []
        self.sending = {"active": False, "idx": -1, "total": 0, "guarding": False, "sent_at": 0, "waiting": False}
        self.abort = asyncio.Event()
        self.guard_ok = asyncio.Event()
        self.send_lock = threading.Lock()
        self.send_task = None

    def queue_file(self):
        """Return the queue persistence file path used by this runtime."""
        return self.runtime.queue_file()

    def restart_pub(self, addr: str) -> None:
        """Recreate the TX PUB socket at *addr*."""
        if self.zmq_sock:
            try:
                zmq_cleanup(self.zmq_monitor, PUB_STATUS, self.status.get(), self.zmq_sock, self.zmq_ctx)
            except Exception:
                pass
        self.zmq_ctx = self.zmq_sock = self.zmq_monitor = None
        try:
            self.zmq_ctx, self.zmq_sock, self.zmq_monitor = init_zmq_pub(addr)
            self.status.set("BOUND")
        except Exception as exc:
            self.status.set("OFFLINE")
            logging.error("TX ZMQ PUB init failed: %s", exc)

    @property
    def status(self):
        return self.runtime.tx_status

    def save_queue(self) -> None:
        """Persist the current queue to disk as JSONL."""
        from . import tx_queue as _tq
        _tq.save_queue(self.queue, self.queue_file())

    def load_queue(self):
        """Load any persisted queue items from disk."""
        from . import tx_queue as _tq
        return _tq.load_queue(self.queue_file(), runtime=self.runtime)

    def renumber_queue(self) -> None:
        """Assign sequential display numbers to queued command items."""
        from . import tx_queue as _tq
        _tq.renumber_queue(self.queue)

    def queue_summary(self):
        """Summarize queue size, guard count, and rough execution time."""
        from . import tx_queue as _tq
        return _tq.queue_summary(self.queue, self.runtime.cfg)

    def queue_items_json(self):
        """Project the current queue into the websocket/API JSON shape."""
        from . import tx_queue as _tq
        return _tq.queue_items_json(self.queue)

    async def broadcast(self, msg):
        """Broadcast one JSON-serializable message to all TX websocket clients."""
        text = json.dumps(msg) if isinstance(msg, dict) else msg
        await broadcast_safe(self.clients, self.lock, text)

    async def send_queue_update(self):
        """Broadcast the current queue plus send-state snapshot."""
        await self.broadcast({"type": "queue_update", "items": self.queue_items_json(), "summary": self.queue_summary(), "sending": self.sending.copy()})

    # ── run_send helpers ──────────────────────────────────────────────

    def _pop_unnumbered_note(self) -> None:
        """Drop the front item without renumbering. Only valid for ``note`` items."""
        with self.send_lock:
            if self.queue:
                if self.queue[0]["type"] != "note":
                    raise TypeError(
                        f"_pop_unnumbered_note called on {self.queue[0]['type']!r}"
                    )
                self.queue.pop(0)
            self.save_queue()

    def _pop_and_renumber(self) -> None:
        """Drop the front item and renumber surviving commands.

        Not valid for ``note`` items — notes are unnumbered and do not
        participate in the mission-cmd numbering sequence.
        """
        with self.send_lock:
            if self.queue:
                if self.queue[0]["type"] == "note":
                    raise TypeError("_pop_and_renumber called on note item")
                self.queue.pop(0)
            self.renumber_queue()
            self.save_queue()

    async def _wait_ms(self, ms: int) -> bool:
        """Sleep up to *ms* milliseconds or until abort fires. Returns True if aborted."""
        if ms <= 0:
            return self.abort.is_set()
        if self.abort.is_set():
            return True
        try:
            await asyncio.wait_for(self.abort.wait(), timeout=ms / 1000.0)
            return True
        except asyncio.TimeoutError:
            return False

    async def _run_note_item(self, item, ctx: _SendContext) -> _RunResult:
        """Drop a front-of-queue ``note`` item without numbering impact."""
        self._pop_unnumbered_note()
        return _RunResult(aborted=False, sent_delta=0)

    async def _run_delay_item(self, item, ctx: _SendContext) -> _RunResult:
        """Execute a ``delay`` queue item."""
        with self.send_lock:
            self.sending["sent_at"] = 0
            self.sending["waiting"] = True  # Flag MUST be set before the broadcast below — tests observing the broadcast assume the flag is already True.
        await self.broadcast({
            "type": "send_progress", "sent": ctx.sent, "total": ctx.total,
            "current": f"delay {item['delay_ms']}ms", "waiting": True,
        })
        aborted = await self._wait_ms(item["delay_ms"])
        with self.send_lock:
            self.sending["waiting"] = False
        if aborted:
            return _RunResult(aborted=True, sent_delta=0)
        self._pop_and_renumber()
        return _RunResult(aborted=False, sent_delta=0)

    async def _run_guard_wait(self, item) -> bool:
        """Broadcast guard prompt and block until approved or aborted.

        Uses asyncio.wait on both events so either approval or abort wakes
        the waiter immediately, without the previous 100 ms polling loop.
        """
        with self.send_lock:
            self.sending["guarding"] = True  # Flag MUST be set before the broadcast below — tests observing the broadcast assume the flag is already True.
        self.guard_ok.clear()
        await self.broadcast({
            "type": "guard_confirm", "index": 0,
            "display": item.get("display", {}),
        })
        guard_task = asyncio.ensure_future(self.guard_ok.wait())
        abort_task = asyncio.ensure_future(self.abort.wait())
        try:
            await asyncio.wait(
                {guard_task, abort_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in (guard_task, abort_task):
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            with self.send_lock:
                self.sending["guarding"] = False
        return self.abort.is_set()

    def _build_frame(self, raw_cmd: bytes, uplink_mode: str, send_csp, send_ax25) -> bytes:
        """Wrap a raw command in CSP + the configured uplink framing."""
        csp_packet = send_csp.wrap(raw_cmd)
        if uplink_mode == "ASM+Golay":
            if not GOLAY_OK:
                raise RuntimeError(
                    "ASM+Golay selected but libfec RS encoder is unavailable in this "
                    "environment. Install libfec (e.g. `sudo apt install libfec-dev && "
                    "sudo ldconfig`, `conda install -c ryanvolz libfec`, or build from "
                    "https://github.com/quiet/libfec) or switch tx.uplink_mode to AX.25."
                )
            return build_asm_golay_frame(csp_packet)
        ax25_frame = send_ax25.wrap(csp_packet)
        return build_ax25_gfsk_frame(ax25_frame)

    def _record_sent(self, item, raw_cmd: bytes, payload: bytes, send_csp, send_ax25, uplink_mode: str) -> dict:
        """Write the TX log entry and append a history item; return the history entry."""
        if self.log:
            try:
                self.log.write_mission_command(
                    self.count,
                    item.get("display", {}),
                    item.get("payload", {}),
                    raw_cmd, payload, send_ax25, send_csp,
                    uplink_mode=uplink_mode,
                    operator=self.runtime.operator,
                    station=self.runtime.station,
                )
            except Exception as exc:
                logging.warning("TX log write failed: %s", exc)

        hist_entry = {
            "n": self.count,
            "ts": datetime.now().strftime("%H:%M:%S"),
            "type": "mission_cmd",
            "operator": self.runtime.operator,
            "station": self.runtime.station,
            "display": item.get("display", {}),
            "payload": item.get("payload", {}),
            "size": len(payload),
        }
        self.history.append(hist_entry)
        if len(self.history) > self.runtime.max_history:
            del self.history[: len(self.history) - self.runtime.max_history]
        return hist_entry

    async def _finalize_send(self, sent: int) -> None:
        """Common cleanup path for send_complete / send_aborted."""
        with self.send_lock:
            self.save_queue()
            self.sending.update(active=False, idx=-1, total=0, guarding=False, sent_at=0, waiting=False)

        remaining = len(self.queue)
        if self.abort.is_set():
            await self.broadcast({"type": "send_aborted", "sent": sent, "remaining": remaining})
        else:
            await self.broadcast({"type": "send_complete", "sent": sent})

        await self.send_queue_update()
        await self.broadcast({"type": "history", "items": self.history[-self.runtime.max_history :]})

    async def _run_mission_cmd_item(self, item, ctx: _SendContext) -> _RunResult:
        """Execute one ``mission_cmd`` queue item end-to-end: optional guard,
        frame build, ZMQ send, blackout arm, history record, post-send dwell."""
        if item.get("guard"):
            if await self._run_guard_wait(item):
                return _RunResult(aborted=True, sent_delta=0)

        raw_cmd = item.get("raw_cmd", b"")
        if not raw_cmd:
            await self.broadcast({"type": "send_error", "error": f"empty raw_cmd for {item.get('display', {}).get('title', '?')}"})
            self._pop_and_renumber()
            return _RunResult(aborted=True, sent_delta=0)

        try:
            payload = self._build_frame(raw_cmd, ctx.uplink_mode, ctx.send_csp, ctx.send_ax25)
        except Exception as exc:
            logging.error("Frame build failed for %s: %s", item.get("cmd", "?"), exc)
            await self.broadcast({"type": "send_error", "error": f"frame build failed: {exc}"})
            self._pop_and_renumber()
            return _RunResult(aborted=True, sent_delta=0)

        if not send_pdu(ctx.sock, payload):
            logging.error("ZMQ send failed for %s", item.get("cmd", "?"))
            await self.broadcast({"type": "send_error", "error": "ZMQ send failed"})
            self._pop_and_renumber()
            return _RunResult(aborted=True, sent_delta=0)

        # Arm (or clear) the TX→RX blackout window so RxService drops
        # packets arriving while the simulated radio is transmitting.
        if ctx.blackout_ms > 0:
            self.runtime.tx_blackout_until = time.time() + ctx.blackout_ms / 1000.0
            await self.runtime.rx.broadcast({"type": "blackout", "ms": ctx.blackout_ms})
        else:
            # Feature disabled at send time. If a prior batch armed a
            # deadline that is still in the future, emit an explicit
            # clear (ms=0) so every connected RX view — main dashboard
            # and pop-out alike — hides its indicator deterministically
            # instead of waiting for the old timer to drain.
            if self.runtime.tx_blackout_until > time.time():
                await self.runtime.rx.broadcast({"type": "blackout", "ms": 0})
            self.runtime.tx_blackout_until = 0.0

        with self.send_lock:
            self.sending["sent_at"] = time.time()
        self.count += 1

        hist_entry = self._record_sent(item, raw_cmd, payload, ctx.send_csp, ctx.send_ax25, ctx.uplink_mode)

        new_sent = ctx.sent + 1
        await self.broadcast({"type": "sent", "data": hist_entry})
        current_label = item.get("display", {}).get("title", "?")
        await self.broadcast({"type": "send_progress", "sent": new_sent, "total": ctx.total, "current": current_label, "waiting": False})

        # Post-send visible dwell. The sent item stays at queue-front for
        # `tx.delay_ms` so operators see the SENDING animation and the
        # "— delay" indicator; aborts wake immediately. `delay_ms=0` skips
        # the dwell for zero-overhead back-to-back sends.
        dwell_aborted = False
        if ctx.default_delay > 0:
            with self.send_lock:
                self.sending["waiting"] = True
            await self.broadcast({
                "type": "send_progress", "sent": new_sent, "total": ctx.total,
                "current": current_label, "waiting": True,
            })
            dwell_aborted = await self._wait_ms(ctx.default_delay)
            with self.send_lock:
                self.sending["waiting"] = False

        with self.send_lock:
            if self.queue:
                self.queue.pop(0)
            self.sending["sent_at"] = 0
            self.renumber_queue()
            self.save_queue()
        return _RunResult(aborted=dwell_aborted, sent_delta=1)

    async def run_send(self):
        """Run the serialized TX send loop until queue exhaustion or abort."""
        if self.zmq_sock is None:
            await self.broadcast({"type": "send_error", "error": "TX ZMQ socket not initialized"})
            with self.send_lock:
                self.sending.update(active=False, idx=-1, total=0, guarding=False, sent_at=0, waiting=False)
            await self.send_queue_update()
            return

        with self.runtime.cfg_lock:
            uplink_mode = self.runtime.cfg.get("tx", {}).get("uplink_mode", "AX.25")
            default_delay = self.runtime.cfg.get("tx", {}).get("delay_ms", 500)
            blackout_ms = int(self.runtime.cfg.get("rx", {}).get("tx_blackout_ms", 0) or 0)
            send_csp = copy.copy(self.runtime.csp)
            send_ax25 = copy.copy(self.runtime.ax25)

        ctx = _SendContext(
            sent=0,
            total=self.sending.get("total", len(self.queue)),
            sock=self.zmq_sock,
            uplink_mode=uplink_mode,
            default_delay=default_delay,
            blackout_ms=blackout_ms,
            send_csp=send_csp,
            send_ax25=send_ax25,
        )

        try:
            while not self.abort.is_set():
                with self.send_lock:
                    if not self.queue:
                        break
                    item = self.queue[0]
                    self.sending["idx"] = 0
                    self.sending["waiting"] = False

                await self.send_queue_update()

                handler = _ITEM_DISPATCH.get(item["type"])
                if handler is None:
                    logging.error("Unknown queue item type: %r", item.get("type"))
                    break
                result = await handler(self, item, ctx)
                ctx.sent += result.sent_delta
                if result.aborted:
                    break
        finally:
            await self._finalize_send(ctx.sent)


_ItemHandler = Callable[[TxService, dict, _SendContext], Awaitable[_RunResult]]
_ITEM_DISPATCH: dict[str, _ItemHandler] = {
    "note":        TxService._run_note_item,
    "delay":       TxService._run_delay_item,
    "mission_cmd": TxService._run_mission_cmd_item,
}
