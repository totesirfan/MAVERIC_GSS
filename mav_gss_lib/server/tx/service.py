"""
mav_gss_lib.server.tx.service -- TX Service

Owns the TX side of the web runtime: queue, send state, history, and ZMQ PUB.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Awaitable, Callable, NamedTuple

from mav_gss_lib.platform import EncodedCommand, FramedCommand, tx_log_record
from mav_gss_lib.transport import PUB_STATUS, init_zmq_pub, send_pdu, zmq_cleanup

from .._broadcast import broadcast_safe
from .queue import QueueItem

if TYPE_CHECKING:
    from ..state import WebRuntime


class AdmitResult(Enum):
    ACCEPTED = "accepted"
    REJECTED_SEND_ACTIVE = "rejected_send_active"
    REJECTED_WINDOW_OPEN = "rejected_window_open"


class _RunResult(NamedTuple):
    aborted: bool
    sent_delta: int


@dataclass
class _SendContext:
    """Per-run state shared across per-item handlers."""
    sent: int
    total: int
    sock: object
    default_delay: int
    blackout_ms: int


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
        from . import queue as _tq
        _tq.save_queue(self.queue, self.queue_file())

    def load_queue(self):
        """Load any persisted queue items from disk."""
        from . import queue as _tq
        return _tq.load_queue(self.queue_file(), runtime=self.runtime)

    def renumber_queue(self) -> None:
        """Assign sequential display numbers to queued command items."""
        from . import queue as _tq
        _tq.renumber_queue(self.queue)

    def queue_summary(self):
        """Summarize queue size, guard count, and rough execution time."""
        from . import queue as _tq
        return _tq.queue_summary(self.queue, self.runtime.tx_delay_ms)

    def admit(self, item: dict) -> tuple[AdmitResult, dict]:
        """Admission gate.

        Rule 1: active send → reject all additions (incl. notes/delays;
                the operator's current batch should run without interference).
        Rule 2: mission_cmd + same (cmd_id, dest) as an open CheckWindow
                instance → reject (temporal correlation invariant — responses
                carry only cmd_id+src+ptype, args are not distinguishable).
        Rule 3: accept.

        Queue items are flat dicts: item["payload"] carries the mission
        payload with cmd_id/dest keys directly (see server/tx/queue.py::
        make_mission_cmd: `"payload": mission_payload.get("payload", payload)`).
        `args` is present in the payload but deliberately ignored for keying.
        """
        if self.sending.get("active"):
            return AdmitResult.REJECTED_SEND_ACTIVE, {}
        if item.get("type") != "mission_cmd":
            return AdmitResult.ACCEPTED, {}
        payload = item.get("payload") or {}
        cmd_id = payload.get("cmd_id", "")
        dest = payload.get("dest", "")
        key = (cmd_id, dest)
        open_inst = self.runtime.platform.verifiers.lookup_open(key)
        if open_inst is not None:
            now_ms = int(time.time() * 1000)
            elapsed = now_ms - open_inst.t0_ms
            max_stop = max(
                (v.check_window.stop_ms for v in open_inst.verifier_set.verifiers),
                default=0,
            )
            remaining = max(max_stop - elapsed, 0)
            return AdmitResult.REJECTED_WINDOW_OPEN, {
                "cmd_id": cmd_id,
                "remaining_ms": remaining,
            }
        return AdmitResult.ACCEPTED, {}

    def queue_items_json(self):
        """Project the current queue into the websocket/API JSON shape."""
        from . import queue as _tq
        return _tq.queue_items_json(self.queue)

    async def broadcast(self, msg: dict[str, Any] | str) -> None:
        """Broadcast one JSON-serializable message to all TX websocket clients."""
        text = json.dumps(msg) if isinstance(msg, dict) else msg
        await broadcast_safe(self.clients, self.lock, text)

    async def send_queue_update(self):
        """Broadcast the current queue plus send-state snapshot."""
        await self.broadcast({"type": "queue_update", "items": self.queue_items_json(), "summary": self.queue_summary(), "sending": self.sending.copy()})

    async def broadcast_verifier_instance(self, instance) -> None:
        """Send a per-instance state snapshot to all /ws/tx clients.

        Shape:
          {"type": "verification_update",
           "instance": {
             "instance_id": ..., "correlation_key": [...],
             "t0_ms": ..., "cmd_event_id": ...,
             "stage": ..., "outcomes": {vid: {state, matched_at_ms, match_event_id}},
             "verifier_set": {"verifiers": [{...}]}
           }}
        """
        from mav_gss_lib.platform.tx.verifiers import serialize_instance
        obj = json.loads(serialize_instance(instance))
        await self.broadcast({"type": "verification_update", "instance": obj})

    async def send_verification_restore(self, websocket) -> None:
        """One-shot snapshot to a freshly connected /ws/tx client."""
        from mav_gss_lib.platform.tx.verifiers import serialize_instance
        instances = [
            json.loads(serialize_instance(i))
            for i in self.runtime.platform.verifiers.open_instances()
        ]
        await websocket.send_text(json.dumps({
            "type": "verification_restore",
            "instances": instances,
        }))

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

    async def _wait_for_pending_verifications_clear(
        self, *, poll_ms: int = 250, max_wait_ms: int = 35_000,
    ) -> bool:
        """Block until no non-terminal verifier instance is open, or abort.

        Honors spec §3 invariant ("no two sends to the same (cmd_id, dest) in
        flight or within CheckWindow simultaneously") via the simpler global
        rule operators expect: at most one verification window is open at a
        time. The next mission_cmd waits until the prior instance reaches a
        terminal stage (complete / failed / timed_out) before publishing.

        Cross-target batches serialize too — accepted tradeoff for predictable
        per-row UI: each row's rail/dots tell a clean story without overlap.

        Hard cap of `max_wait_ms` (default 35s, slightly past the longest
        MAVERIC CheckWindow = 30s) prevents the queue from stalling forever
        if the periodic sweeper somehow fails to advance an instance to
        terminal — proceed with the next send rather than freeze.

        Returns True if aborted.
        """
        from mav_gss_lib.platform.tx.verifiers import _TERMINAL
        if self.abort.is_set():
            return True
        registry = self.runtime.platform.verifiers
        deadline = time.time() + max_wait_ms / 1000.0
        while any(inst.stage not in _TERMINAL for inst in registry.open_instances()):
            if time.time() >= deadline:
                logging.warning(
                    "verifier wait timed out after %dms — proceeding with next send",
                    max_wait_ms,
                )
                return False
            try:
                await asyncio.wait_for(self.abort.wait(), timeout=poll_ms / 1000.0)
                return True
            except asyncio.TimeoutError:
                continue
        return False

    async def _run_note_item(self, item: QueueItem, ctx: _SendContext) -> _RunResult:
        """Drop a front-of-queue ``note`` item without numbering impact."""
        self._pop_unnumbered_note()
        return _RunResult(aborted=False, sent_delta=0)

    async def _run_delay_item(self, item: QueueItem, ctx: _SendContext) -> _RunResult:
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

    async def _run_guard_wait(self, item: QueueItem) -> bool:
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

    def _frame_mission_cmd(self, item: QueueItem) -> FramedCommand:
        """Ask the active mission to frame the command's encoded bytes.

        Queue items persist mission-opaque bytes only, not the EncodedCommand
        object. We rebuild it through the mission command pipeline, then
        prefer the persisted raw bytes if present so guard-time rendering
        stays stable even if the mission encoder is non-deterministic.
        """
        encoded_raw = item.get("raw_cmd", b"")
        encoded = self.runtime.mission.commands.encode(
            self.runtime.mission.commands.parse_input({**(item.get("payload") or {})})
        )
        if encoded_raw and encoded.raw != encoded_raw:
            encoded = EncodedCommand(
                raw=encoded_raw,
                guard=encoded.guard,
                mission_payload=encoded.mission_payload,
            )
        return self.runtime.mission.commands.frame(encoded)

    def _record_sent(
        self,
        item: QueueItem,
        raw_cmd: bytes,
        framed: FramedCommand,
        *,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        """Write the TX log entry and append a history item; return the history entry.

        ``event_id`` (if provided) is threaded through to ``tx_log_record`` and
        stamped onto ``hist_entry["event_id"]`` so callers can link history rows
        to verifier instances (the frontend joins on ``cmd_event_id``).
        """
        assert self.count > 0, "TX seq counter not incremented before _record_sent"
        assert len(raw_cmd) > 0, "TX record: raw_cmd is empty"
        assert len(framed.wire) > 0, "TX record: framed.wire is empty"
        assert framed.frame_label, "TX record: framed.frame_label is empty"

        if self.log:
            try:
                record = tx_log_record(
                    self.count,
                    item.get("display", {}),
                    item.get("payload", {}),
                    raw_cmd,
                    framed.wire,
                    session_id=self.log.session_id,
                    ts_ms=int(time.time() * 1000),
                    version=self.runtime.version,
                    mission_id=self.runtime.mission_id,
                    operator=self.runtime.operator,
                    station=self.runtime.station,
                    frame_label=framed.frame_label,
                    log_fields=framed.log_fields,
                    event_id=event_id,
                )
                self.log.write_mission_command(
                    record,
                    raw_cmd=raw_cmd,
                    wire=framed.wire,
                    log_text=framed.log_text,
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
            "size": len(framed.wire),
            "event_id": event_id or "",
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

    async def _run_mission_cmd_item(self, item: QueueItem, ctx: _SendContext) -> _RunResult:
        """Execute one ``mission_cmd`` queue item end-to-end: optional guard,
        same-target wait, frame build, ZMQ send, blackout arm, history record,
        post-send dwell."""
        if item.get("guard"):
            if await self._run_guard_wait(item):
                return _RunResult(aborted=True, sent_delta=0)

        raw_cmd = item.get("raw_cmd", b"")
        if not raw_cmd:
            await self.broadcast({"type": "send_error", "error": f"empty raw_cmd for {item.get('display', {}).get('title', '?')}"})
            self._pop_and_renumber()
            return _RunResult(aborted=True, sent_delta=0)

        try:
            framed = self._frame_mission_cmd(item)
        except Exception as exc:
            logging.error("Frame build failed for %s: %s", item.get("cmd", "?"), exc)
            await self.broadcast({"type": "send_error", "error": f"frame build failed: {exc}"})
            self._pop_and_renumber()
            return _RunResult(aborted=True, sent_delta=0)

        # Sequential-verification gate: only one command's CheckWindow is open
        # at a time. Block here if any prior instance is still non-terminal,
        # so the next send only fires after the previous command is confirmed
        # / failed / timed_out. The visible "waiting" state mirrors
        # `_run_delay_item` so the operator sees the queue is paced, not stuck.
        #
        # The wait is gated on the periodic sweeper actually being live —
        # without it, non-terminal instances never advance and the wait would
        # block forever. The lifespan startup attaches `verifier_sweep_task`;
        # unit-test runtimes (which skip lifespan) don't, and so bypass the
        # wait entirely.
        if getattr(self.runtime, "verifier_sweep_task", None) is not None:
            from mav_gss_lib.platform.tx.verifiers import _TERMINAL
            if any(inst.stage not in _TERMINAL
                   for inst in self.runtime.platform.verifiers.open_instances()):
                self.sending["waiting"] = True
                await self.send_queue_update()
                try:
                    if await self._wait_for_pending_verifications_clear():
                        return _RunResult(aborted=True, sent_delta=0)
                finally:
                    self.sending["waiting"] = False
                    await self.send_queue_update()

        if not send_pdu(ctx.sock, framed.wire):
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

        # Generate ONE shared event_id for the tx_command log record, the
        # CommandInstance back-pointer, and the WS history broadcast so the
        # frontend (Task 26) can join verifier rows to history rows.
        from pathlib import Path as _Path
        import uuid as _uuid
        from mav_gss_lib.platform._log_envelope import new_event_id
        from mav_gss_lib.platform.tx.verifiers import (
            CommandInstance,
            VerifierOutcome,
            write_instances,
        )

        tx_event_id = new_event_id()

        # Re-encode the queue payload to recover the mission's canonical
        # ``mission_payload`` (with header sub-dict, args, etc.) so the
        # mission's verifier_set / correlation_key see the same shape
        # the encode pipeline produced. Mission encode is deterministic;
        # we keep the persisted raw bytes as the authoritative wire.
        try:
            replay = self.runtime.mission.commands.encode(
                self.runtime.mission.commands.parse_input({**(item.get("payload") or {})})
            )
            encoded_for_verifier = EncodedCommand(
                raw=raw_cmd,
                guard=bool(item.get("guard", False)),
                mission_payload=replay.mission_payload,
            )
        except Exception:
            # Fall back to a legacy-shaped envelope so verifier lookup
            # missions that ignore mission_payload still keep working.
            encoded_for_verifier = EncodedCommand(
                raw=raw_cmd,
                guard=bool(item.get("guard", False)),
                mission_payload={
                    "payload": item.get("payload", {}),
                    "display": item.get("display", {}),
                },
            )
        vset = self.runtime.mission.commands.verifier_set(encoded_for_verifier)

        instance: CommandInstance | None = None
        if vset.verifiers:  # skip register when mission declares "verification disabled"
            key = self.runtime.mission.commands.correlation_key(encoded_for_verifier)
            instance = CommandInstance(
                instance_id=_uuid.uuid4().hex,
                correlation_key=key,
                t0_ms=int(time.time() * 1000),
                cmd_event_id=tx_event_id,
                verifier_set=vset,
                outcomes={v.verifier_id: VerifierOutcome.pending() for v in vset.verifiers},
                stage="released",
            )
            self.runtime.platform.verifiers.register(instance)
            try:
                write_instances(
                    _Path(self.runtime.log_dir) / ".pending_instances.jsonl",
                    self.runtime.platform.verifiers.open_instances(),
                )
            except Exception as exc:
                logging.warning("pending_instances write failed: %s", exc)

        # Broadcast everything dirty — register() marked the new instance dirty,
        # so consume_dirty() returns exactly the just-registered instance here.
        # Using consume_dirty() (rather than an explicit broadcast) keeps
        # `_dirty` as the single source of truth for "needs broadcasting" so
        # the next RX tick's consume_dirty() doesn't re-broadcast it.
        for _inst in self.runtime.platform.verifiers.consume_dirty():
            asyncio.create_task(self.broadcast_verifier_instance(_inst))

        # Stamp the shared event_id onto the still-queued item so the
        # frontend can render the verifier tick strip immediately, while the
        # row is in 'sending' state. Without this the dots stay empty until
        # the item transitions to history. Push a fresh queue_update so
        # clients pick up the new id without waiting for the post-send dwell.
        if instance is not None:
            item["event_id"] = tx_event_id
            await self.send_queue_update()

        hist_entry = self._record_sent(item, raw_cmd, framed, event_id=tx_event_id)

        if instance is not None and self.log:
            try:
                self.log.write_cmd_verifier({
                    "seq": self.count,
                    "cmd_event_id": instance.cmd_event_id,
                    "instance_id": instance.instance_id,
                    "stage": "released",
                    "verifier_id": "",
                    "outcome": "pass",
                    "elapsed_ms": 0,
                    "match_event_id": None,
                })
            except Exception as exc:
                logging.warning("cmd_verifier release log failed: %s", exc)

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
            default_delay = self.runtime.tx_delay_ms
            blackout_ms = self.runtime.tx_blackout_ms

        ctx = _SendContext(
            sent=0,
            total=self.sending.get("total", len(self.queue)),
            sock=self.zmq_sock,
            default_delay=default_delay,
            blackout_ms=blackout_ms,
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

            # Last-item verification trail: hold `sending` true until the final
            # command's verifier instance reaches terminal. Without this the
            # TxBuilder collapse-to-progress block re-expands the moment the
            # ZMQ publish completes (~100ms), well before the ~30s verification
            # finishes. Gated on the periodic sweeper actually running so unit
            # tests (which skip lifespan) don't hang.
            if (not self.abort.is_set()
                    and getattr(self.runtime, "verifier_sweep_task", None) is not None):
                from mav_gss_lib.platform.tx.verifiers import _TERMINAL
                if any(inst.stage not in _TERMINAL
                       for inst in self.runtime.platform.verifiers.open_instances()):
                    self.sending["waiting"] = True
                    await self.send_queue_update()
                    await self._wait_for_pending_verifications_clear()
                    self.sending["waiting"] = False
        finally:
            await self._finalize_send(ctx.sent)

    async def clear_sent(self) -> int:
        """Drop all in-memory TX history and broadcast the empty list.

        Returns the count of cleared entries.

        Today this is unconditional. When command-verification ships,
        callers should reject with a structured error if any sent entry
        still has an open CheckWindow; that logic lives above this layer.
        """
        n = len(self.history)
        self.history.clear()
        await self.broadcast({
            "type": "history",
            "items": self.history[-self.runtime.max_history:],
        })
        return n


_ItemHandler = Callable[[TxService, dict, _SendContext], Awaitable[_RunResult]]
_ITEM_DISPATCH: dict[str, _ItemHandler] = {
    "note":        TxService._run_note_item,
    "delay":       TxService._run_delay_item,
    "mission_cmd": TxService._run_mission_cmd_item,
}
