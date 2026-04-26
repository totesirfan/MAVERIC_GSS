"""GET /api/config returns native split shape.

The endpoint returns `{platform, mission: {id, config}}` directly from
`WebRuntime`'s primary split state. No flat projection lives on the
backend; the frontend consumes the same shape the backend stores on disk.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestApiConfigGetReturnsNativeShape(unittest.TestCase):
    def _client(self):
        from fastapi.testclient import TestClient
        from mav_gss_lib.server.app import create_app
        return TestClient(create_app())

    def test_get_does_not_crash(self):
        client = self._client()
        resp = client.get("/api/config")
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_response_is_native_split_shape(self):
        client = self._client()
        body = client.get("/api/config").json()
        # Native split contract.
        self.assertIn("platform", body)
        self.assertIn("mission", body)
        self.assertIn("id", body["mission"])
        self.assertIn("config", body["mission"])

        platform = body["platform"]
        for key in ("tx", "rx", "general"):
            self.assertIn(key, platform, f"missing platform.{key}")
        # Runtime-derived fields surface on platform.general for the UI.
        self.assertIn("version", platform["general"])
        self.assertIn("log_dir", platform["general"])

        mission_cfg = body["mission"]["config"]
        # Operator-editable mission subtrees (ax25.*, csp.*, imaging.*) surface here.
        # Identity keys (mission_name, nodes, ptypes, …) live in the declarative
        # codec runtime now, not in mission_cfg.
        self.assertIsInstance(mission_cfg, dict)

    def test_response_reflects_mission_config_mutations(self):
        """Primary state lives on the split; GET must reflect runtime edits."""
        from fastapi.testclient import TestClient
        from mav_gss_lib.server.app import create_app

        app = create_app()
        client = TestClient(app)

        runtime = app.state.runtime
        runtime.mission_cfg.setdefault("ax25", {})["src_call"] = "ROUNDTRIP"
        runtime.platform_cfg.setdefault("tx", {})["delay_ms"] = 4242

        body = client.get("/api/config").json()
        self.assertEqual(body["mission"]["config"]["ax25"]["src_call"], "ROUNDTRIP")
        self.assertEqual(body["platform"]["tx"]["delay_ms"], 4242)


if __name__ == "__main__":
    unittest.main()
