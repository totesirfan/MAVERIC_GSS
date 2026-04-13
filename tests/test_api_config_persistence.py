"""Verify PUT /api/config strips derived junk and preserves operator overrides."""
import copy
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mav_gss_lib.web_runtime.api.config import _strip_persisted_junk  # noqa: E402


class TestStripPersistedJunk(unittest.TestCase):
    def test_strips_strictly_mission_owned_top_level(self):
        update = {
            "nodes": {"1": "LPPM"},
            "ptypes": {"1": "CMD"},
            "node_descriptions": {"LPPM": "Lower PPM"},
            "ax25": {"src_call": "WM2XBB"},
            "csp": {"priority": 2},
        }
        cleaned = _strip_persisted_junk(copy.deepcopy(update))
        self.assertNotIn("nodes", cleaned)
        self.assertNotIn("ptypes", cleaned)
        self.assertNotIn("node_descriptions", cleaned)
        self.assertEqual(cleaned["ax25"], {"src_call": "WM2XBB"})
        self.assertEqual(cleaned["csp"], {"priority": 2})

    def test_strips_runtime_derived_and_platform_general_keys(self):
        update = {
            "general": {
                "mission": "maveric",
                "log_dir": "logs",
                "version": "5.0.0",
                "ui_scale": 100,
                "mission_name": "MAVERIC",
                "gs_node": "GS",
                "command_defs": "commands.yml",
                "command_defs_resolved": "/abs/path/commands.yml",
                "command_defs_warning": "",
                "rx_title": "RX DOWNLINK",
                "tx_title": "TX UPLINK",
                "splash_subtitle": "Mission Ground Station",
            },
        }
        cleaned = _strip_persisted_junk(copy.deepcopy(update))
        self.assertEqual(
            cleaned["general"],
            {"mission": "maveric", "log_dir": "logs", "ui_scale": 100},
        )
        self.assertNotIn("version", cleaned["general"])

    def test_preserves_operator_keys(self):
        update = {
            "tx": {"zmq_addr": "tcp://127.0.0.1:52002", "frequency": "437.6 MHz", "uplink_mode": "ASM+Golay"},
            "rx": {"zmq_addr": "tcp://127.0.0.1:52001"},
            "ax25": {"src_call": "WM2XBB", "src_ssid": 97},
            "csp": {"priority": 2, "destination": 8},
            "general": {"mission": "maveric", "log_dir": "logs"},
        }
        cleaned = _strip_persisted_junk(copy.deepcopy(update))
        self.assertEqual(cleaned, update)


class _FakeService:
    def __init__(self):
        self.sending = {"active": False}
        self.status = ("ok",)
        self.log = None
    def restart_pub(self, *_a, **_k): pass
    def restart_receiver(self): pass


class _FakeRuntime:
    def __init__(self, cfg):
        import threading
        self.cfg = cfg
        self.cfg_lock = threading.RLock()
        self.session_token = "test-token"
        self.tx = _FakeService()
        self.rx = _FakeService()
        self.csp = None
        self.ax25 = None


class TestConfigEndpointRoundTrip(unittest.TestCase):
    """Hit the real FastAPI route so we catch regressions in auth gating,
    request handling, save_gss_config() behavior, and the strip helper."""

    def _build_app(self, runtime):
        from fastapi import FastAPI
        from mav_gss_lib.web_runtime.api.config import router
        app = FastAPI()
        app.state.runtime = runtime
        app.include_router(router)
        return app

    def test_put_persists_overrides_and_strips_junk(self):
        import yaml
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        import mav_gss_lib.config as _cfg_mod

        with tempfile.TemporaryDirectory() as tmp:
            gss_path = os.path.join(tmp, "gss.yml")
            with open(gss_path, "w") as f:
                yaml.safe_dump(
                    {
                        "tx": {"zmq_addr": "tcp://127.0.0.1:52002", "delay_ms": 500, "frequency": "437.25 MHz"},
                        "rx": {"zmq_addr": "tcp://127.0.0.1:52001"},
                        "general": {"mission": "maveric", "log_dir": "logs"},
                        "ax25": {"src_call": "WM2XBB", "src_ssid": 97},
                        "csp": {"priority": 2, "destination": 8},
                    },
                    f,
                )

            runtime = _FakeRuntime(cfg={
                "tx": {"zmq_addr": "tcp://127.0.0.1:52002", "delay_ms": 500, "frequency": "437.25 MHz"},
                "rx": {"zmq_addr": "tcp://127.0.0.1:52001"},
                "general": {"mission": "maveric", "log_dir": "logs"},
                "ax25": {"src_call": "WM2XBB", "src_ssid": 97},
                "csp": {"priority": 2, "destination": 8},
                "nodes": {"1": "LPPM"},
                "ptypes": {"1": "CMD"},
            })

            app = self._build_app(runtime)
            client = TestClient(app)

            update = {
                "ax25": {"src_call": "WM2XBC", "src_ssid": 98},
                "csp": {"priority": 3},
                # Sentinel values: if stripping fails, these would appear
                # in runtime.cfg and/or gss.yml.
                "nodes": {"99": "SENTINEL_NODE"},
                "ptypes": {"99": "SENTINEL_PTYPE"},
                "node_descriptions": {"SENTINEL_NODE": "should not persist"},
                "general": {
                    "mission": "maveric",
                    "version": "0.0.1-sentinel",
                    "command_defs_resolved": "/abs/commands.yml",
                    "command_defs_warning": "",
                    "mission_name": "SENTINEL_MISSION_NAME",
                    "gs_node": "SENTINEL_GS",
                    "rx_title": "SENTINEL_RX_TITLE",
                    "tx_title": "SENTINEL_TX_TITLE",
                    "splash_subtitle": "SENTINEL_SUBTITLE",
                },
            }

            with patch.object(_cfg_mod, "_DEFAULT_GSS_PATH", gss_path), \
                 patch("mav_gss_lib.web_runtime.api.config.apply_csp", lambda *_a, **_k: None), \
                 patch("mav_gss_lib.web_runtime.api.config.apply_ax25", lambda *_a, **_k: None):
                resp = client.put(
                    "/api/config",
                    json=update,
                    headers={"x-gss-token": "test-token"},
                )

            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertEqual(resp.json(), {"ok": True})

            with open(gss_path) as f:
                persisted = yaml.safe_load(f)

            # Operator overrides survived
            self.assertEqual(persisted["ax25"]["src_call"], "WM2XBC")
            self.assertEqual(persisted["ax25"]["src_ssid"], 98)
            self.assertEqual(persisted["csp"]["priority"], 3)
            self.assertEqual(persisted["csp"]["destination"], 8)
            self.assertEqual(persisted["tx"]["frequency"], "437.25 MHz")
            self.assertEqual(persisted["general"]["mission"], "maveric")
            self.assertEqual(persisted["general"]["log_dir"], "logs")

            # Mission-owned top-level keys stripped
            self.assertNotIn("nodes", persisted)
            self.assertNotIn("ptypes", persisted)
            self.assertNotIn("node_descriptions", persisted)

            # Runtime-derived, mission-only, and platform-derived general keys stripped
            for key in (
                "command_defs_resolved",
                "command_defs_warning",
                "mission_name",
                "gs_node",
                "rx_title",
                "tx_title",
                "splash_subtitle",
                "version",
            ):
                self.assertNotIn(key, persisted.get("general", {}))

            # In-memory runtime state must also be clean — client payload
            # must not pollute runtime.cfg with mission-owned or platform-
            # derived keys. Original runtime nodes/ptypes should be intact.
            self.assertEqual(runtime.cfg["nodes"], {"1": "LPPM"})
            self.assertEqual(runtime.cfg["ptypes"], {"1": "CMD"})
            self.assertNotIn("99", runtime.cfg.get("nodes", {}))
            self.assertNotIn("node_descriptions", runtime.cfg)
            for key in (
                "mission_name",
                "gs_node",
                "command_defs_resolved",
                "command_defs_warning",
                "rx_title",
                "tx_title",
                "splash_subtitle",
                "version",
            ):
                self.assertNotIn(key, runtime.cfg.get("general", {}))

    def test_put_rejects_missing_token(self):
        from fastapi.testclient import TestClient
        runtime = _FakeRuntime(cfg={"general": {"mission": "maveric"}, "rx": {}, "tx": {}})
        app = self._build_app(runtime)
        client = TestClient(app)
        resp = client.put("/api/config", json={"tx": {"delay_ms": 600}})
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
