"""Tests for Mission.parse_warnings forwarding through the platform loader
and /ws/preflight payload builder.

Author:  Irfan Annuar - USC ISI SERC
"""

import logging
import unittest
from unittest.mock import MagicMock

from mav_gss_lib.platform.spec.argument_types import BUILT_IN_ARGUMENT_TYPES
from mav_gss_lib.platform.spec.mission import (
    ContainerShadow,
    Mission,
    MissionHeader,
)


class TestParseWarningForwarding(unittest.TestCase):
    def test_loader_logs_each_warning(self):
        # Build a Mission with synthetic warnings; verify the loader's
        # forwarding helper logs them.
        from mav_gss_lib.platform.loader import _forward_parse_warnings

        m = Mission(
            id="m", name="m",
            header=MissionHeader(version="1.0.0", date="2026-04-25"),
            parameter_types={},
            argument_types=dict(BUILT_IN_ARGUMENT_TYPES),
            parameters={}, bitfield_types={},
            sequence_containers={}, meta_commands={},
            parse_warnings=(
                ContainerShadow(broader="A", specific="B"),
                ContainerShadow(broader="C", specific="D"),
            ),
        )
        with self.assertLogs("mav_gss_lib.platform.spec", level="WARNING") as cm:
            _forward_parse_warnings(m)
        self.assertEqual(len(cm.output), 2)
        self.assertIn("A", cm.output[0])
        self.assertIn("C", cm.output[1])

    def test_preflight_payload_includes_mission_parse_warnings(self):
        from mav_gss_lib.server.ws.preflight import _build_preflight_payload

        runtime = MagicMock()
        runtime.parse_warnings = (
            ContainerShadow(broader="A", specific="B"),
        )
        runtime.preflight_status = "passed"
        runtime.preflight_results = []
        runtime.update_status = None
        payload = _build_preflight_payload(runtime)
        self.assertIn("mission_parse_warnings", payload)
        self.assertEqual(len(payload["mission_parse_warnings"]), 1)
        self.assertIn("A", payload["mission_parse_warnings"][0])


class TestParseWarningEndToEnd(unittest.TestCase):
    def test_mission_spec_with_parse_warnings_surfaces_in_runtime(self):
        """Loader populates WebRuntime.parse_warnings from MissionSpec."""
        from mav_gss_lib.platform.contract.mission import MissionSpec
        from mav_gss_lib.platform.spec.mission import ContainerShadow

        ms = MissionSpec(
            id="test_mission",
            name="Test Mission",
            packets=MagicMock(),
            config=MagicMock(),
            parse_warnings=(ContainerShadow(broader="A", specific="B"),),
        )
        self.assertEqual(len(ms.parse_warnings), 1)
        self.assertIn("A", str(ms.parse_warnings[0]))

    def test_mission_spec_default_parse_warnings_is_empty(self):
        """MissionSpec.parse_warnings defaults to an empty tuple."""
        from mav_gss_lib.platform.contract.mission import MissionSpec

        ms = MissionSpec(
            id="test_mission",
            name="Test Mission",
            packets=MagicMock(),
            config=MagicMock(),
        )
        self.assertEqual(ms.parse_warnings, ())

    def test_forward_parse_warnings_reads_from_mission_spec(self):
        """_forward_parse_warnings works with MissionSpec (not just spec.Mission)."""
        from mav_gss_lib.platform.contract.mission import MissionSpec
        from mav_gss_lib.platform.loader import _forward_parse_warnings
        from mav_gss_lib.platform.spec.mission import ContainerShadow

        ms = MissionSpec(
            id="test_mission",
            name="Test Mission",
            packets=MagicMock(),
            config=MagicMock(),
            parse_warnings=(ContainerShadow(broader="X", specific="Y"),),
        )
        with self.assertLogs("mav_gss_lib.platform.spec", level="WARNING") as cm:
            _forward_parse_warnings(ms)
        self.assertEqual(len(cm.output), 1)
        self.assertIn("X", cm.output[0])


if __name__ == "__main__":
    unittest.main()
