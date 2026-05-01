import unittest
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mav_gss_lib.server.api.tracking_ws import register_tracking_ws
from mav_gss_lib.server.tracking._tick import DopplerBroadcaster


class _State:
    def __init__(self) -> None:
        self.broadcaster = DopplerBroadcaster()
        self.tracking = MagicMock()
        self.tracking.status.return_value = {
            "mode": "disconnected",
            "last_error": "",
            "last_tick_ms": 0,
        }


class TrackingWsTests(unittest.TestCase):
    def test_status_snapshot_then_replays_latest_doppler(self) -> None:
        # Pre-seed the broadcaster's latest snapshot so the new subscriber
        # receives it immediately on connect — exercises the same replay
        # path used in production for late-joining UI clients.
        state = _State()
        state.broadcaster._latest = {
            "type": "doppler",
            "doppler": {"mode": "connected", "rx_tune_hz": 437_499_900.0},
            "ts_ms": 1_700_000_000_000,
        }

        app = FastAPI()
        register_tracking_ws(app, lambda: state.broadcaster, lambda: state.tracking)

        with TestClient(app) as client:
            with client.websocket_connect("/ws/tracking") as ws:
                snapshot = ws.receive_json()
                self.assertEqual(snapshot["type"], "status")
                self.assertEqual(snapshot["mode"], "disconnected")

                msg = ws.receive_json()
                self.assertEqual(msg["type"], "doppler")
                self.assertEqual(msg["doppler"]["rx_tune_hz"], 437_499_900.0)


if __name__ == "__main__":
    unittest.main()
