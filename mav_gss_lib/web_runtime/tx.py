"""TX queue management, send task, and websocket handling."""

from __future__ import annotations

import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .state import MAX_HISTORY, MAX_QUEUE, WebRuntime, get_runtime
from .runtime import make_delay, schedule_shutdown_check, validate_cmd_item
from .security import authorize_websocket
from .services import item_to_json

router = APIRouter()


@router.websocket("/ws/tx")
async def ws_tx(websocket: WebSocket):
    runtime = get_runtime(websocket)
    if not await authorize_websocket(websocket):
        return
    await websocket.accept()
    runtime.had_clients = True

    try:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "queue_update",
                    "items": runtime.tx.queue_items_json(),
                    "summary": runtime.tx.queue_summary(),
                    "sending": runtime.tx.sending.copy(),
                }
            )
        )
        await websocket.send_text(json.dumps({"type": "history", "items": runtime.tx.history[-MAX_HISTORY:]}))
    except Exception:
        return

    with runtime.tx.lock:
        runtime.tx.clients.append(websocket)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "error": "invalid JSON"}))
                continue

            action = msg.get("action", "")

            def sending():
                return runtime.tx.sending["active"]

            if action == "queue":
                if sending():
                    await websocket.send_text(json.dumps({"type": "error", "error": "cannot modify queue during send"}))
                    continue
                if len(runtime.tx.queue) >= MAX_QUEUE:
                    await websocket.send_text(
                        json.dumps({"type": "error", "error": f"queue full ({MAX_QUEUE} items max)"})
                    )
                    continue
                line = msg.get("input", "").strip()
                if not line:
                    await websocket.send_text(json.dumps({"type": "error", "error": "empty input"}))
                    continue
                try:
                    parts = line.split()
                    candidate = parts[0].lower()
                    defn = runtime.cmd_defs.get(candidate)
                    if defn and not defn.get("rx_only") and defn.get("dest") is not None:
                        cmd_id = candidate
                        args = " ".join(parts[1:])
                        src, dest = runtime.adapter.gs_node, defn["dest"]
                        echo, ptype_val = defn["echo"], defn["ptype"]
                    else:
                        src, dest, echo, ptype_val, cmd_id, args = runtime.adapter.parse_cmd_line(line)
                    item = validate_cmd_item(src, dest, echo, ptype_val, cmd_id, args, runtime=runtime)
                    runtime.tx.queue.append(item)
                    runtime.tx.renumber_queue()
                    runtime.tx.save_queue()
                    await runtime.tx.send_queue_update()
                except ValueError as exc:
                    await websocket.send_text(json.dumps({"type": "error", "error": str(exc)}))

            elif action == "queue_built":
                if sending():
                    await websocket.send_text(json.dumps({"type": "error", "error": "cannot modify queue during send"}))
                    continue
                if len(runtime.tx.queue) >= MAX_QUEUE:
                    await websocket.send_text(
                        json.dumps({"type": "error", "error": f"queue full ({MAX_QUEUE} items max)"})
                    )
                    continue
                try:
                    cmd_id = msg["cmd"].lower()
                    defn = runtime.cmd_defs.get(cmd_id, {})
                    if runtime.cmd_defs and cmd_id not in runtime.cmd_defs:
                        raise ValueError(f"'{cmd_id}' not in schema")
                    if defn.get("rx_only"):
                        raise ValueError(f"{cmd_id} is rx_only (downlink only)")
                    src = runtime.adapter.resolve_node(str(msg.get("src", "GS")))
                    dest = runtime.adapter.resolve_node(str(msg["dest"]))
                    echo = runtime.adapter.resolve_node(str(msg.get("echo", "NONE")))
                    ptype_val = runtime.adapter.resolve_ptype(str(msg.get("ptype", "CMD")))
                    if None in (src, dest, echo, ptype_val):
                        raise ValueError("unresolvable node/ptype")
                    item = validate_cmd_item(
                        src,
                        dest,
                        echo,
                        ptype_val,
                        cmd_id,
                        msg.get("args", ""),
                        guard=bool(msg.get("guard", False)),
                        runtime=runtime,
                    )
                    runtime.tx.queue.append(item)
                    runtime.tx.renumber_queue()
                    runtime.tx.save_queue()
                    await runtime.tx.send_queue_update()
                except (ValueError, KeyError) as exc:
                    await websocket.send_text(json.dumps({"type": "error", "error": str(exc)}))

            elif action == "queue_mission_cmd":
                if sending():
                    await websocket.send_text(json.dumps({"type": "error", "error": "cannot modify queue during send"}))
                    continue
                if len(runtime.tx.queue) >= MAX_QUEUE:
                    await websocket.send_text(
                        json.dumps({"type": "error", "error": f"queue full ({MAX_QUEUE} items max)"})
                    )
                    continue
                try:
                    from .runtime import validate_mission_cmd
                    payload = msg.get("payload", {})
                    item = validate_mission_cmd(payload, runtime=runtime)
                    runtime.tx.queue.append(item)
                    runtime.tx.renumber_queue()
                    runtime.tx.save_queue()
                    await runtime.tx.send_queue_update()
                except (ValueError, KeyError) as exc:
                    await websocket.send_text(json.dumps({"type": "error", "error": str(exc)}))

            elif action == "delete":
                if sending():
                    await websocket.send_text(json.dumps({"type": "error", "error": "cannot modify queue during send"}))
                    continue
                idx = msg.get("index")
                with runtime.tx.send_lock:
                    if isinstance(idx, int) and 0 <= idx < len(runtime.tx.queue):
                        runtime.tx.queue.pop(idx)
                        runtime.tx.renumber_queue()
                        runtime.tx.save_queue()
                await runtime.tx.send_queue_update()

            elif action == "clear":
                if sending():
                    await websocket.send_text(json.dumps({"type": "error", "error": "cannot modify queue during send"}))
                    continue
                with runtime.tx.send_lock:
                    runtime.tx.queue.clear()
                    runtime.tx.save_queue()
                await runtime.tx.send_queue_update()

            elif action == "undo":
                if sending():
                    await websocket.send_text(json.dumps({"type": "error", "error": "cannot modify queue during send"}))
                    continue
                with runtime.tx.send_lock:
                    if runtime.tx.queue:
                        runtime.tx.queue.pop()
                        runtime.tx.renumber_queue()
                        runtime.tx.save_queue()
                await runtime.tx.send_queue_update()

            elif action == "guard":
                if sending():
                    await websocket.send_text(json.dumps({"type": "error", "error": "cannot modify queue during send"}))
                    continue
                idx = msg.get("index")
                with runtime.tx.send_lock:
                    if isinstance(idx, int) and 0 <= idx < len(runtime.tx.queue):
                        item = runtime.tx.queue[idx]
                        if item["type"] == "cmd":
                            item["guard"] = not item.get("guard", False)
                            runtime.tx.save_queue()
                await runtime.tx.send_queue_update()

            elif action == "reorder":
                if sending():
                    await websocket.send_text(json.dumps({"type": "error", "error": "cannot modify queue during send"}))
                    continue
                order = msg.get("order", [])
                with runtime.tx.send_lock:
                    if isinstance(order, list) and len(order) == len(runtime.tx.queue):
                        try:
                            runtime.tx.queue[:] = [runtime.tx.queue[index] for index in order]
                            runtime.tx.renumber_queue()
                            runtime.tx.save_queue()
                        except (IndexError, TypeError):
                            pass
                await runtime.tx.send_queue_update()

            elif action == "add_delay":
                if sending():
                    await websocket.send_text(json.dumps({"type": "error", "error": "cannot modify queue during send"}))
                    continue
                if len(runtime.tx.queue) >= MAX_QUEUE:
                    await websocket.send_text(
                        json.dumps({"type": "error", "error": f"queue full ({MAX_QUEUE} items max)"})
                    )
                    continue
                delay_ms = max(0, min(300_000, int(msg.get("delay_ms", 1000))))
                idx = msg.get("index")
                item = make_delay(delay_ms)
                with runtime.tx.send_lock:
                    if isinstance(idx, int) and 0 <= idx <= len(runtime.tx.queue):
                        runtime.tx.queue.insert(idx, item)
                    else:
                        runtime.tx.queue.append(item)
                    runtime.tx.renumber_queue()
                    runtime.tx.save_queue()
                await runtime.tx.send_queue_update()

            elif action == "edit_delay":
                if sending():
                    await websocket.send_text(json.dumps({"type": "error", "error": "cannot modify queue during send"}))
                    continue
                idx = msg.get("index")
                delay_ms = msg.get("delay_ms")
                with runtime.tx.send_lock:
                    if (
                        isinstance(idx, int)
                        and 0 <= idx < len(runtime.tx.queue)
                        and runtime.tx.queue[idx]["type"] == "delay"
                        and isinstance(delay_ms, (int, float))
                    ):
                        runtime.tx.queue[idx]["delay_ms"] = max(0, min(300_000, int(delay_ms)))
                        runtime.tx.save_queue()
                await runtime.tx.send_queue_update()

            elif action == "send":
                with runtime.tx.send_lock:
                    if runtime.tx.sending["active"] and runtime.tx.send_task and runtime.tx.send_task.done():
                        runtime.tx.sending["active"] = False
                    if runtime.tx.sending["active"]:
                        await websocket.send_text(json.dumps({"type": "error", "error": "send already in progress"}))
                        continue
                    if not runtime.tx.queue:
                        await websocket.send_text(json.dumps({"type": "error", "error": "queue is empty"}))
                        continue
                    runtime.tx.abort.clear()
                    runtime.tx.guard_ok.clear()
                    runtime.tx.sending.update(active=True, total=len(runtime.tx.queue), idx=0, guarding=False, sent_at=0, waiting=False)
                runtime.tx.send_task = asyncio.create_task(runtime.tx.run_send())

            elif action == "abort":
                runtime.tx.abort.set()

            elif action == "guard_approve":
                runtime.tx.guard_ok.set()

            elif action == "guard_reject":
                runtime.tx.abort.set()

    except WebSocketDisconnect:
        pass
    finally:
        with runtime.tx.lock:
            if websocket in runtime.tx.clients:
                runtime.tx.clients.remove(websocket)
            no_tx_clients = len(runtime.tx.clients) == 0
        if no_tx_clients and runtime.tx.sending.get("guarding"):
            runtime.tx.abort.set()
        schedule_shutdown_check(runtime)
