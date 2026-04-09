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

import secrets
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from mav_gss_lib.config import (
    apply_ax25,
    apply_csp,
    get_generated_commands_dir,
    load_gss_config,
)
from mav_gss_lib.mission_adapter import load_mission_adapter
from mav_gss_lib.protocols.ax25 import AX25Config
from mav_gss_lib.protocols.csp import CSPConfig
from .services import RxService, TxService

WEB_DIR = Path(__file__).resolve().parents[1] / "web" / "dist"
HOST = "127.0.0.1"
PORT = 8080
MAX_PACKETS = 500
MAX_HISTORY = 500
MAX_QUEUE = 200
SHUTDOWN_DELAY = 15


@dataclass
class Session:
    session_id: str
    tag: str
    started_at: str
    generation: int


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
        self.adapter = load_mission_adapter(self.cfg)
        self.cmd_defs = self.adapter.cmd_defs

        self.rx_status = ["OFFLINE"]
        self.tx_status = ["OFFLINE"]

        self.csp = CSPConfig()
        self.ax25 = AX25Config()
        apply_csp(self.cfg, self.csp)
        apply_ax25(self.cfg, self.ax25)

        self.shutdown_task = None
        self.had_clients = False
        self.cfg_lock = threading.Lock()
        self.session = Session(
            session_id=uuid.uuid4().hex,
            tag="untitled",
            started_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            generation=1,
        )
        self.session_clients: list = []
        self.session_lock = threading.Lock()

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


def get_runtime(holder) -> WebRuntime:
    """Extract the attached WebRuntime from a FastAPI app/request/websocket."""
    app = holder if hasattr(holder, "state") and hasattr(holder.state, "runtime") else getattr(holder, "app", None)
    if app is None or not hasattr(app.state, "runtime"):
        raise RuntimeError("web runtime is not attached to app.state")
    return app.state.runtime
