"""MissionSpec.preflight hook.

Verifies:
- The platform preflight driver calls MissionSpec.preflight() and streams
  the mission-specific CheckResults inline.
- Platform preflight no longer string-compares mission id or uplink mode —
  enforced by a guardrail test that scans mav_gss_lib/preflight.py.
- MAVERIC's preflight hook covers the command-schema and libfec checks that
  previously lived on the platform side.
"""
from __future__ import annotations

import os
import pathlib
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mav_gss_lib.platform import MissionConfigSpec, MissionSpec  # noqa: E402
from mav_gss_lib.platform.contract.rendering import PacketRendering  # noqa: E402
from mav_gss_lib.preflight import CheckResult, run_preflight  # noqa: E402


class _Ui:
    def packet_columns(self): return []
    def tx_columns(self): return []
    def render_packet(self, packet): return PacketRendering(columns=[], row={})
    def render_log_data(self, packet): return {}
    def format_text_log(self, packet): return []


def _fixture_spec(preflight=None) -> MissionSpec:
    return MissionSpec(
        id="maveric",
        name="MAVERIC",
        packets=None,
        ui=_Ui(),
        config=MissionConfigSpec(),
        preflight=preflight,
    )


class TestPreflightRunsMissionHook(unittest.TestCase):
    def test_mission_hook_checks_are_streamed_inline(self):
        hook_called = []

        def _hook():
            hook_called.append(True)
            yield CheckResult("mission_fixture", "Fixture check", "ok")
            yield CheckResult("mission_fixture", "Another fixture check", "warn", detail="partial")

        spec = _fixture_spec(preflight=_hook)
        with tempfile.TemporaryDirectory() as tmp:
            lib_dir = Path(tmp)
            (lib_dir / "missions" / "maveric").mkdir(parents=True)
            (lib_dir / "web" / "dist").mkdir(parents=True)
            (lib_dir / "web" / "dist" / "index.html").write_text("<html></html>")
            (lib_dir / "gss.yml").write_text("")
            results = list(run_preflight(
                cfg={"general": {"mission": "maveric"}, "tx": {}, "rx": {}},
                mission_cfg={},
                mission=spec,
                lib_dir=lib_dir,
                operator="test", host="host", station="station",
            ))

        self.assertEqual(hook_called, [True])
        labels = [r.label for r in results]
        self.assertIn("Fixture check", labels)
        self.assertIn("Another fixture check", labels)

    def test_hook_exception_is_reported_not_swallowed(self):
        def _hook():
            raise RuntimeError("hook exploded")
            yield  # pragma: no cover — needed so Python recognizes this as a generator

        spec = _fixture_spec(preflight=_hook)
        with tempfile.TemporaryDirectory() as tmp:
            lib_dir = Path(tmp)
            (lib_dir / "missions" / "maveric").mkdir(parents=True)
            (lib_dir / "web" / "dist").mkdir(parents=True)
            (lib_dir / "web" / "dist" / "index.html").write_text("<html></html>")
            (lib_dir / "gss.yml").write_text("")
            results = list(run_preflight(
                cfg={"general": {"mission": "maveric"}, "tx": {}, "rx": {}},
                mission_cfg={},
                mission=spec,
                lib_dir=lib_dir,
                operator="test", host="host", station="station",
            ))

        fails = [r for r in results if r.status == "fail" and "preflight" in r.label.lower()]
        self.assertTrue(fails, "expected a mission preflight failure row")
        self.assertIn("hook exploded", fails[0].detail)


class TestPlatformPreflightIsMissionNeutral(unittest.TestCase):
    """Guardrail — the platform preflight module must not branch on mission id
    or import mission-specific primitives.
    """

    def test_no_maveric_or_uplink_mode_branches(self):
        path = pathlib.Path(__file__).resolve().parent.parent / "mav_gss_lib" / "preflight.py"
        text = path.read_text()
        # Platform preflight must not import mission-specific modules.
        self.assertNotRegex(
            text,
            r"from\s+mav_gss_lib\.missions\.maveric|import\s+mav_gss_lib\.missions\.maveric",
        )
        # Platform preflight must not reach into specific framers directly —
        # ASM+Golay capability is a mission-owned radio concern.
        self.assertNotRegex(text, r"mav_gss_lib\.platform\.framing\.asm_golay")
        # Platform preflight must not branch on uplink mode strings like
        # "ASM+Golay" (MAVERIC-specific).
        self.assertNotIn("ASM+Golay", text)
        self.assertNotIn('"maveric"', text)
        self.assertNotIn("'maveric'", text)


class TestMavericPreflightHook(unittest.TestCase):
    def test_maveric_mission_spec_exposes_a_preflight_callable(self):
        from mav_gss_lib.server.state import create_runtime
        rt = create_runtime()
        self.assertIsNotNone(rt.mission.preflight)
        # Invoking the hook yields at least the command-schema and uplink
        # checks — both CheckResult-shaped.
        results = list(rt.mission.preflight())
        self.assertTrue(results)
        labels = {r.label for r in results}
        self.assertTrue(any("Mission schema" in label for label in labels))
        self.assertTrue(any("libfec" in label for label in labels))


if __name__ == "__main__":
    unittest.main()
