from __future__ import annotations

import threading
import time
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mav_gss_lib.platform.tracking import (
    default_tracking_config,
    default_tracking_config_dict,
    normalize_tracking_config,
    tracking_state,
)
from mav_gss_lib.server.api.tracking import router as tracking_router
from mav_gss_lib.server.tracking import TrackingService
from mav_gss_lib.server.tracking._tick import DopplerBroadcaster


class TestTrackingDomain(unittest.TestCase):
    def test_default_config_normalizes_to_usc_station(self):
        cfg = normalize_tracking_config({})

        self.assertEqual(cfg.selected_station_id, "usc")
        self.assertEqual(cfg.selected_station.name, "USC / Southern California")
        self.assertEqual(cfg.tle.name, "MAVERIC")
        self.assertGreater(cfg.frequencies.rx_hz, 0)
        self.assertGreater(cfg.frequencies.tx_hz, 0)

    def test_tracking_state_contains_doppler_and_passes(self):
        state = tracking_state(
            default_tracking_config(),
            time_ms=int(time.time() * 1000),
            pass_count=2,
        )

        self.assertEqual(state.doppler.satellite, "MAVERIC")
        self.assertEqual(state.doppler.rx_tune_hz, state.doppler.rx_hz + state.doppler.rx_shift_hz)
        self.assertEqual(state.doppler.tx_tune_hz, state.doppler.tx_hz + state.doppler.tx_shift_hz)
        self.assertGreater(state.footprint.radius_deg, 0)
        self.assertLessEqual(len(state.upcoming_passes), 2)


class _CaptureSink:
    def __init__(self):
        self.items = []

    def publish(self, correction):
        self.items.append(correction)


class _Runtime:
    def __init__(self):
        self.platform_cfg = {"tracking": default_tracking_config_dict()}
        self.cfg_lock = threading.RLock()
        self.session_token = "token"
        self.tracking = TrackingService(self)
        self.doppler_broadcaster = DopplerBroadcaster()


class TestTrackingService(unittest.TestCase):
    def test_connected_mode_publishes_to_sink(self):
        runtime = _Runtime()
        sink = _CaptureSink()
        runtime.tracking = TrackingService(runtime, sink_factory=lambda **_: sink)

        runtime.tracking.set_doppler_connected(True)
        correction = runtime.tracking.doppler()

        self.assertEqual(correction["mode"], "connected")
        self.assertEqual(len(sink.items), 1)
        self.assertEqual(sink.items[0].mode, "connected")

    def test_tracking_api_returns_state_and_accepts_doppler_connection(self):
        runtime = _Runtime()
        app = FastAPI()
        app.state.runtime = runtime
        app.include_router(tracking_router)
        client = TestClient(app)

        mode = client.post(
            "/api/tracking/doppler/connection/connect",
            headers={"x-gss-token": "token"},
        )
        self.assertEqual(mode.status_code, 200)
        self.assertEqual(mode.json(), {"connected": True, "mode": "connected"})

        response = client.get("/api/tracking/state?pass_count=1")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["doppler"]["mode"], "connected")
        self.assertIn("ground_track", body)
        self.assertLessEqual(len(body["upcoming_passes"]), 1)


if __name__ == "__main__":
    unittest.main()
