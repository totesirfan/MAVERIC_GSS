"""ColumnDef.toggle passes through to the frontend.

The shared RX packet list hides the `frame` and `echo` columns unless the
matching toggle (`showFrame` / `showEcho`) is enabled. That feature depends
on the `toggle` field surviving the trip through MAVERIC's UiOps mapping
and out the `/api/columns` endpoint.

Regression: earlier, `ColumnDef` had no `toggle` field, so the MAVERIC
`_column()` helper in ui_ops.py silently dropped `"toggle": "showFrame"` on
the way out. Column views lost their toggle semantics and the RX frame
column stopped hiding.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestColumnDefToggleSerializes(unittest.TestCase):
    def test_platform_columndef_serializes_toggle_when_set(self):
        from mav_gss_lib.platform.contract.rendering import ColumnDef
        col = ColumnDef(id="frame", label="frame", width="w-[72px]", toggle="showFrame")
        self.assertEqual(col.to_json().get("toggle"), "showFrame")

    def test_platform_columndef_omits_toggle_when_unset(self):
        from mav_gss_lib.platform.contract.rendering import ColumnDef
        col = ColumnDef(id="time", label="time")
        self.assertNotIn("toggle", col.to_json())


class TestMavericColumnsCarryToggle(unittest.TestCase):
    def test_maveric_packet_columns_include_frame_toggle(self):
        from mav_gss_lib.server.state import create_runtime
        rt = create_runtime()
        cols = rt.mission.ui.packet_columns()
        by_id = {c.id: c for c in cols}
        self.assertIn("frame", by_id)
        self.assertEqual(by_id["frame"].toggle, "showFrame")
        self.assertIn("echo", by_id)
        self.assertEqual(by_id["echo"].toggle, "showEcho")

    def test_api_columns_emits_toggle(self):
        from fastapi.testclient import TestClient
        from mav_gss_lib.server.app import create_app

        client = TestClient(create_app())
        cols = client.get("/api/columns").json()
        by_id = {c["id"]: c for c in cols}
        self.assertEqual(by_id.get("frame", {}).get("toggle"), "showFrame")
        self.assertEqual(by_id.get("echo", {}).get("toggle"), "showEcho")


if __name__ == "__main__":
    unittest.main()
