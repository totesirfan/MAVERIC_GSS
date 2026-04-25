"""
mav_gss_lib.server.app -- FastAPI App Assembly

Creates the FastAPI application, wires in the shared runtime, mounts
the built frontend assets, and manages backend startup/shutdown tasks
such as queue restore, logging setup, TX socket initialization, and RX
broadcast lifetime.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

if TYPE_CHECKING:
    from .state import WebRuntime

from mav_gss_lib.config import get_rx_zmq_addr, get_tx_zmq_addr
from mav_gss_lib.logging import SessionLog, TXLog

from .api import router as api_router
from .ws.rx import router as rx_router
from .tx.queue import sanitize_queue_items
from .ws.session import router as session_router
from .ws.preflight import (
    router as preflight_router,
    run_preflight_and_broadcast,
)
from .ws.update import schedule_update_check
from .ws.tx import router as tx_router
from .telemetry.api import get_telemetry_router
from mav_gss_lib.transport import PUB_STATUS, zmq_cleanup
from .state import WEB_DIR, create_runtime, get_runtime
from ._task_utils import log_task_exception


# =============================================================================
#  APP LIFESPAN
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> "AsyncIterator[None]":
    """Manage backend startup and shutdown for one FastAPI app instance."""
    runtime = get_runtime(app)
    runtime.tx.queue, skipped = sanitize_queue_items(runtime.tx.load_queue(), runtime=runtime)
    runtime.tx.renumber_queue()
    if skipped:
        logging.warning("Dropped %d invalid queued item(s) during startup restore", skipped)

    import time as _time
    runtime.platform.restore_verifiers(
        path=str(Path(runtime.log_dir) / ".pending_instances.jsonl"),
        now_ms=int(_time.time() * 1000),
    )

    tx_addr = get_tx_zmq_addr(runtime.platform_cfg)
    runtime.tx.restart_pub(tx_addr)

    rx_addr = get_rx_zmq_addr(runtime.platform_cfg)
    runtime.rx.log = SessionLog(
        runtime.log_dir, rx_addr, runtime.version,
        mission_name=runtime.mission_name, mission_id=runtime.mission_id,
        station=runtime.station, operator=runtime.operator, host=runtime.host,
    )
    runtime.tx.log = TXLog(
        runtime.log_dir, tx_addr, version=runtime.version,
        mission_name=runtime.mission_name, mission_id=runtime.mission_id,
        station=runtime.station, operator=runtime.operator, host=runtime.host,
    )
    print(f"RX logging → {runtime.rx.log.jsonl_path}")
    print(f"TX logging → {runtime.tx.log.jsonl_path}")

    runtime.rx.start_receiver()
    runtime.rx.broadcast_task = asyncio.create_task(runtime.rx.broadcast_loop())
    runtime.rx.broadcast_task.add_done_callback(log_task_exception("rx-broadcast"))

    # Kick off the update check on a worker thread so it overlaps with the
    # mission checks streaming over the preflight WS. Resolved at the end of
    # run_preflight_and_broadcast via _build_updates_event.
    schedule_update_check(runtime)

    # Schedule preflight to run AFTER server starts serving.
    # create_task() queues the coroutine; it executes once lifespan yields
    # and uvicorn begins accepting connections.
    runtime.preflight_task = asyncio.create_task(run_preflight_and_broadcast(runtime))
    runtime.preflight_task.add_done_callback(log_task_exception("preflight"))

    # Periodic verifier sweep — drives window_expired + timed_out transitions
    # when no RX traffic is arriving (e.g., no flight connected during ground
    # testing). Without this, stage stays 'released' forever and the UI
    # never turns red on timeout.
    runtime.verifier_sweep_task = asyncio.create_task(_verifier_sweep_loop(runtime))
    runtime.verifier_sweep_task.add_done_callback(log_task_exception("verifier-sweep"))
    yield

    await _shutdown_runtime(runtime)


async def _shutdown_runtime(runtime: "WebRuntime") -> None:
    """Tear down RX/TX/preflight state during lifespan shutdown."""
    runtime.rx.broadcast_stop = True
    runtime.rx.stop.set()
    if runtime.rx.thread_handle:
        runtime.rx.thread_handle.join(timeout=1.0)
    if runtime.rx.broadcast_task:
        try:
            await asyncio.wait_for(runtime.rx.broadcast_task, timeout=3.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
    preflight_task = getattr(runtime, "preflight_task", None)
    if preflight_task and not preflight_task.done():
        preflight_task.cancel()
        try:
            await asyncio.wait_for(preflight_task, timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
    sweep_task = getattr(runtime, "verifier_sweep_task", None)
    if sweep_task and not sweep_task.done():
        sweep_task.cancel()
        try:
            await asyncio.wait_for(sweep_task, timeout=1.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
    if runtime.rx.log:
        try:
            runtime.rx.log.close()
        except Exception:
            pass
    if runtime.tx.log:
        try:
            runtime.tx.log.close()
        except Exception:
            pass
    if runtime.tx.zmq_sock:
        try:
            zmq_cleanup(runtime.tx.zmq_monitor, PUB_STATUS, "OFFLINE", runtime.tx.zmq_sock, runtime.tx.zmq_ctx)
        except Exception:
            pass


async def _verifier_sweep_loop(runtime: "WebRuntime") -> None:
    """Fire the verifier registry's sweep() once per second.

    Inside the sweep, any pending verifier whose CheckWindow has elapsed
    transitions to window_expired; stage is re-derived and may advance to
    timed_out. Dirty instances get broadcast to /ws/tx clients so the UI
    rail + tick strip update promptly even with zero inbound packets.
    """
    import time as _time
    while True:
        try:
            await asyncio.sleep(1.0)
            now_ms = int(_time.time() * 1000)
            runtime.platform.verifiers.sweep(now_ms=now_ms)
            for inst in runtime.platform.verifiers.consume_dirty():
                asyncio.create_task(runtime.tx.broadcast_verifier_instance(inst))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.warning("verifier sweep tick failed: %s", exc)


# =============================================================================
#  APP FACTORY
# =============================================================================

def create_app() -> FastAPI:
    """Create the configured FastAPI application and attach a WebRuntime."""
    runtime = create_runtime()
    app = FastAPI(title=f"{runtime.mission_name} GSS Web", lifespan=lifespan)
    app.state.runtime = runtime

    if WEB_DIR.exists() and (WEB_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

    app.include_router(api_router)
    app.include_router(rx_router)
    app.include_router(tx_router)
    app.include_router(session_router)
    app.include_router(preflight_router)
    app.include_router(get_telemetry_router())

    if runtime.mission.http is not None:
        for router in runtime.mission.http.routers:
            app.include_router(router)
            logging.info("Mounted mission router: %s", router.prefix)

    if WEB_DIR.exists():

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str) -> FileResponse:
            file_path = WEB_DIR / full_path
            if file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(
                WEB_DIR / "index.html",
                headers={"Cache-Control": "no-cache"},
            )

    return app
