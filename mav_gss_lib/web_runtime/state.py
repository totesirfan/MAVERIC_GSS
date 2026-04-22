"""
mav_gss_lib.web_runtime.state -- Web Runtime State Container

Owns the long-lived mutable backend state used by the FastAPI app:
active config, protocol objects, mission adapter, RX/TX services, and
queue/logging limits.

This module is the construction point for the web runtime and the
shared state accessors used across API routes, websocket handlers,
and background services.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import asyncio
import secrets
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from fastapi import FastAPI, Request, WebSocket

from mav_gss_lib.config import (
    apply_ax25,
    apply_csp,
    get_generated_commands_dir,
    load_gss_config,
)
from mav_gss_lib.identity import capture_host, capture_operator, capture_station
from mav_gss_lib.mission_adapter import load_mission_adapter
from mav_gss_lib.protocols.ax25 import AX25Config
from mav_gss_lib.protocols.csp import CSPConfig
from ._atomics import AtomicStatus
from .rx_service import RxService
from .telemetry.router import TelemetryRouter
from .tx_service import TxService

if TYPE_CHECKING:
    from mav_gss_lib.updater import UpdateStatus

WEB_DIR = Path(__file__).resolve().parents[1] / "web" / "dist"
HOST = "127.0.0.1"
PORT = 8080
MAX_PACKETS = 500
MAX_HISTORY = 500
MAX_QUEUE = 200


@dataclass
class Session:
    session_id: str
    session_tag: str
    started_at: str
    session_generation: int
    operator: str
    host: str
    station: str


# =============================================================================
#  RUNTIME CONTAINER
# =============================================================================

class WebRuntime:
    """Own mutable backend state for one FastAPI app instance."""

    def __init__(self) -> None:
        self.session_token = secrets.token_urlsafe(24)
        self.max_packets = MAX_PACKETS
        self.max_history = MAX_HISTORY
        self.max_queue = MAX_QUEUE

        self.cfg = load_gss_config()
        self.operator = capture_operator()
        self.host = capture_host()
        self.station = capture_station(self.cfg, self.host)
        self.adapter = load_mission_adapter(self.cfg)
        self.cmd_defs = self.adapter.cmd_defs

        log_dir = self.cfg.get("general", {}).get("log_dir", "logs")
        self.telemetry = TelemetryRouter(Path(log_dir) / ".telemetry")
        for name, spec in self.adapter.telemetry_manifest.items():
            self.telemetry.register_domain(name, **spec)
        # Aliases so the adapter can reach the router + its extractors
        # without a separate handoff step. Platform still owns construction;
        # adapter code just reads through these attrs.
        self.adapter.extractors = self.adapter.telemetry_extractors
        self.adapter.telemetry = self.telemetry

        self.tx_status = AtomicStatus()

        # tx_blackout_until: cross-thread float read/write. CPython float assign
        # is GIL-atomic; writer (TxService send loop) and reader (RX drop filter)
        # see a coherent value without a lock. Seconds since epoch.
        self.tx_blackout_until: float = 0.0

        self.csp = CSPConfig()
        self.ax25 = AX25Config()
        apply_csp(self.cfg, self.csp)
        apply_ax25(self.cfg, self.ax25)

        self.shutdown_task = None
        self.had_clients = False
        self.cfg_lock = threading.Lock()
        self.session = Session(
            session_id=uuid.uuid4().hex,
            session_tag="untitled",
            started_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            session_generation=1,
            operator=self.operator,
            host=self.host,
            station=self.station,
        )
        self.session_clients: list = []
        self.session_lock = threading.Lock()

        # Preflight state
        self.preflight_results: list[dict] = []
        self.preflight_done: bool = False
        self.preflight_running: bool = False   # single-run guard
        self.preflight_task = None             # asyncio.Task reference
        self.preflight_clients: list = []
        self.preflight_lock = threading.Lock()

        # Updater state — populated at lifespan start via schedule_update_check
        self.update_status_future: Optional[asyncio.Future] = None
        self.update_status: Optional["UpdateStatus"] = None
        self.update_lock = threading.Lock()
        self.update_in_progress: bool = False
        self.launched: bool = False

        self.rx = RxService(self)
        self.tx = TxService(self)

    def queue_file(self) -> Path:
        return Path(self.cfg.get("general", {}).get("log_dir", "logs")) / ".pending_queue.jsonl"

    def generated_commands_dir(self) -> Path:
        return get_generated_commands_dir(self.cfg)


# =============================================================================
#  RUNTIME FACTORIES / ACCESSORS
# =============================================================================

def create_runtime() -> WebRuntime:
    """Create a fresh WebRuntime with loaded config and initialized services."""
    return WebRuntime()


def ensure_runtime(runtime: WebRuntime | None) -> WebRuntime:
    """Return *runtime* if provided, otherwise create a new runtime."""
    return runtime if runtime is not None else create_runtime()


def get_runtime(holder: "FastAPI | Request | WebSocket") -> WebRuntime:
    """Extract the attached WebRuntime from a FastAPI app/request/websocket."""
    for candidate in (holder, getattr(holder, "app", None)):
        if candidate is not None \
           and hasattr(candidate, "state") \
           and hasattr(candidate.state, "runtime"):
            return candidate.state.runtime
    raise RuntimeError(
        f"web runtime is not attached to app.state (holder={type(holder).__name__})"
    )
