"""WebSocket endpoint handshake tests using FastAPI TestClient."""

from __future__ import annotations

import json
import sys
import threading
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mav_gss_lib.platform import ColumnDef, EventOps
from mav_gss_lib.server.ws.rx import router as rx_router
from mav_gss_lib.server.ws.tx import router as tx_router
from mav_gss_lib.server.ws.session import router as session_router
from mav_gss_lib.server.state import PORT


def _build_stub_runtime():
    """Minimal runtime that satisfies the three WS handlers."""
    runtime = MagicMock()
    runtime.session_token = "test-token"
    runtime.had_clients = False
    runtime.shutdown_task = None
    runtime.operator = "test-op"
    runtime.host = "test-host"
    runtime.station = "GS-TEST"

    # RX stubs
    runtime.rx.clients = []
    runtime.rx.lock = threading.Lock()
    runtime.rx.packets = deque()
    runtime.rx.last_rx_at = 0.0

    # TX stubs
    runtime.tx.clients = []
    runtime.tx.lock = threading.Lock()
    runtime.tx.send_lock = threading.Lock()
    runtime.tx.sending = {"active": False, "guarding": False}
    runtime.tx.queue = []
    runtime.tx.history = []
    runtime.tx.queue_items_json.return_value = []
    runtime.tx.queue_summary.return_value = {"total": 0}
    runtime.tx.send_verification_restore = AsyncMock()

    # Session stubs
    runtime.session.session_id = "sess-123"
    runtime.session.session_tag = "untitled"
    runtime.session.started_at = "2026-04-17T00:00:00Z"
    runtime.session.session_generation = 1
    runtime.session.operator = "test-op"
    runtime.session.host = "test-host"
    runtime.session.station = "GS-TEST"
    runtime.session_clients = []
    runtime.session_lock = threading.Lock()

    runtime.mission.ui.packet_columns.return_value = [
        ColumnDef(id="num", label="#", width="40px"),
    ]
    runtime.mission.events = EventOps()

    return runtime


def _build_app():
    app = FastAPI()
    app.state.runtime = _build_stub_runtime()
    app.include_router(rx_router)
    app.include_router(tx_router)
    app.include_router(session_router)
    return app


class TestWsRxHandshake(unittest.TestCase):
    def test_connect_then_disconnect_clean(self):
        app = _build_app()
        with TestClient(app) as client:
            url = f"/ws/rx?token={app.state.runtime.session_token}"
            with client.websocket_connect(url) as ws:
                env = ws.receive_json()
                self.assertEqual(env["type"], "columns")
                self.assertIsInstance(env["data"], list)

    def test_bad_token_is_rejected(self):
        app = _build_app()
        with TestClient(app) as client:
            from starlette.websockets import WebSocketDisconnect
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect("/ws/rx?token=wrong") as ws:
                    ws.receive_text()

    def test_client_registered_then_removed(self):
        app = _build_app()
        runtime = app.state.runtime
        with TestClient(app) as client:
            url = f"/ws/rx?token={runtime.session_token}"
            with client.websocket_connect(url):
                # Registered during the with-block
                self.assertEqual(len(runtime.rx.clients), 1)
            # Removed after disconnect
            self.assertEqual(len(runtime.rx.clients), 0)

    def test_connect_replays_telemetry_snapshots(self):
        """EPS/GNC dashboards repopulate after a browser reload because
        /ws/rx replays persisted telemetry snapshots on connect.
        Regression guard for a bug where TelemetryRouter.replay() was
        defined but never wired into the handshake."""
        app = _build_app()
        runtime = app.state.runtime
        runtime.telemetry.replay.return_value = [
            {"type": "telemetry", "domain": "eps",
             "changes": {"V_BUS": {"v": 7.4, "t": 1_700_000_000_000}},
             "replay": True},
            {"type": "telemetry", "domain": "gnc",
             "changes": {"GNC_MODE": {"v": 2, "t": 1_700_000_000_000}},
             "replay": True},
        ]
        with TestClient(app) as client:
            url = f"/ws/rx?token={runtime.session_token}"
            with client.websocket_connect(url) as ws:
                self.assertEqual(ws.receive_json()["type"], "columns")
                eps_msg = ws.receive_json()
                gnc_msg = ws.receive_json()
        self.assertEqual(eps_msg["domain"], "eps")
        self.assertTrue(eps_msg["replay"])
        self.assertEqual(eps_msg["changes"]["V_BUS"]["v"], 7.4)
        self.assertEqual(gnc_msg["domain"], "gnc")
        self.assertTrue(gnc_msg["replay"])


class TestWsTxHandshake(unittest.TestCase):
    def test_connect_sends_queue_update_and_history(self):
        app = _build_app()
        runtime = app.state.runtime
        with TestClient(app) as client:
            url = f"/ws/tx?token={runtime.session_token}"
            with client.websocket_connect(url) as ws:
                first = ws.receive_json()
                second = ws.receive_json()
                self.assertEqual(first["type"], "queue_update")
                self.assertIn("items", first)
                self.assertIn("summary", first)
                self.assertIn("sending", first)
                self.assertEqual(second["type"], "history")
                self.assertIn("items", second)

    def test_unknown_action_returns_error(self):
        app = _build_app()
        runtime = app.state.runtime
        with TestClient(app) as client:
            url = f"/ws/tx?token={runtime.session_token}"
            with client.websocket_connect(url) as ws:
                ws.receive_json()  # queue_update
                ws.receive_json()  # history
                ws.send_json({"action": "does-not-exist"})
                err = ws.receive_json()
                self.assertEqual(err["type"], "error")
                self.assertIn("unknown action", err["error"])

    def test_invalid_json_returns_error(self):
        app = _build_app()
        runtime = app.state.runtime
        with TestClient(app) as client:
            url = f"/ws/tx?token={runtime.session_token}"
            with client.websocket_connect(url) as ws:
                ws.receive_json()  # queue_update
                ws.receive_json()  # history
                ws.send_text("{not json")
                err = ws.receive_json()
                self.assertEqual(err["type"], "error")
                self.assertEqual(err["error"], "invalid JSON")


class TestWsSessionHandshake(unittest.TestCase):
    def test_connect_sends_session_info_and_traffic_status(self):
        app = _build_app()
        runtime = app.state.runtime
        with TestClient(app) as client:
            url = f"/ws/session?token={runtime.session_token}"
            with client.websocket_connect(url) as ws:
                info = ws.receive_json()
                traffic = ws.receive_json()
                self.assertEqual(info["type"], "session_info")
                self.assertEqual(info["session_id"], "sess-123")
                self.assertEqual(info["session_tag"], "untitled")
                self.assertEqual(info["session_generation"], 1)
                self.assertEqual(traffic["type"], "traffic_status")
                self.assertIn("active", traffic)
                self.assertFalse(traffic["active"])  # last_rx_at == 0


if __name__ == "__main__":
    unittest.main()
