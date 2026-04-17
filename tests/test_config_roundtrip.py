"""Round-trip tests for mav_gss_lib.config load/save."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mav_gss_lib import config as cfg_mod


class TestConfigRoundTrip(unittest.TestCase):
    def test_load_missing_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            missing = os.path.join(td, "does-not-exist.yml")
            loaded = cfg_mod.load_gss_config(missing)
            self.assertEqual(loaded["tx"]["zmq_addr"], "tcp://127.0.0.1:52002")
            self.assertEqual(loaded["rx"]["zmq_addr"], "tcp://127.0.0.1:52001")
            self.assertEqual(loaded["general"]["mission"], "maveric")

    def test_user_value_overrides_default(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "gss.yml")
            initial = cfg_mod.load_gss_config("/tmp/does-not-exist-guaranteed")
            initial["tx"]["zmq_addr"] = "tcp://127.0.0.1:59999"
            initial["rx"]["tx_blackout_ms"] = 250
            cfg_mod.save_gss_config(initial, path)

            reloaded = cfg_mod.load_gss_config(path)
            self.assertEqual(reloaded["tx"]["zmq_addr"], "tcp://127.0.0.1:59999")
            self.assertEqual(reloaded["rx"]["tx_blackout_ms"], 250)
            # Unchanged keys still carry defaults
            self.assertEqual(reloaded["general"]["mission"], "maveric")

    def test_round_trip_preserves_nested_structure(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "gss.yml")
            value = {
                "tx": {"zmq_addr": "tcp://x:1", "delay_ms": 100},
                "rx": {"zmq_addr": "tcp://y:2", "tx_blackout_ms": 5},
                "general": {"mission": "echo", "log_dir": "logs-test"},
            }
            cfg_mod.save_gss_config(value, path)
            reloaded = cfg_mod.load_gss_config(path)
            self.assertEqual(reloaded["tx"]["zmq_addr"], "tcp://x:1")
            self.assertEqual(reloaded["tx"]["delay_ms"], 100)
            self.assertEqual(reloaded["rx"]["zmq_addr"], "tcp://y:2")
            self.assertEqual(reloaded["rx"]["tx_blackout_ms"], 5)
            self.assertEqual(reloaded["general"]["mission"], "echo")
            self.assertEqual(reloaded["general"]["log_dir"], "logs-test")

    def test_save_is_atomic_replace(self):
        """Partial write scenario — temp file shouldn't leak into real path."""
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "gss.yml")
            good = {"general": {"mission": "maveric", "log_dir": "logs"}}
            cfg_mod.save_gss_config(good, path)
            # Verify file exists and no .tmp files linger.
            entries = os.listdir(td)
            self.assertIn("gss.yml", entries)
            for name in entries:
                self.assertFalse(name.endswith(".tmp"), f"leftover temp file: {name}")

    def test_deep_merge_does_not_drop_platform_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "gss.yml")
            # User only sets one key; everything else should deep-merge
            partial = {"tx": {"delay_ms": 250}}
            cfg_mod.save_gss_config(partial, path)
            reloaded = cfg_mod.load_gss_config(path)
            self.assertEqual(reloaded["tx"]["delay_ms"], 250)
            # These came from defaults
            self.assertEqual(reloaded["tx"]["zmq_addr"], "tcp://127.0.0.1:52002")
            self.assertEqual(reloaded["rx"]["zmq_addr"], "tcp://127.0.0.1:52001")


if __name__ == "__main__":
    unittest.main()
