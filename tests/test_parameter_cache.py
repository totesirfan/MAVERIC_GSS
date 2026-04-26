"""ParameterCache — flat name-keyed parameter state with LWW merge.

Author: Irfan Annuar - USC ISI SERC
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mav_gss_lib.platform.contract.parameters import ParamUpdate
from mav_gss_lib.platform.parameters import ParameterCache


class ParameterCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "parameters.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_apply_inserts_new_entry(self) -> None:
        cache = ParameterCache(self.path)
        changes = cache.apply([ParamUpdate(name="gnc.RATE", value=[0.1, 0.2, 0.3], ts_ms=1000, unit="rad/s")])
        self.assertEqual(changes, [{"name": "gnc.RATE", "v": [0.1, 0.2, 0.3], "t": 1000}])

    def test_apply_lww_drops_older(self) -> None:
        cache = ParameterCache(self.path)
        cache.apply([ParamUpdate(name="eps.V_BUS", value=12.0, ts_ms=2000)])
        self.assertEqual(cache.apply([ParamUpdate(name="eps.V_BUS", value=11.0, ts_ms=1000)]), [])

    def test_apply_lww_overwrites_newer(self) -> None:
        cache = ParameterCache(self.path)
        cache.apply([ParamUpdate(name="eps.V_BUS", value=12.0, ts_ms=1000)])
        self.assertEqual(
            cache.apply([ParamUpdate(name="eps.V_BUS", value=11.5, ts_ms=2000)]),
            [{"name": "eps.V_BUS", "v": 11.5, "t": 2000}],
        )

    def test_display_only_bypasses_persist(self) -> None:
        cache = ParameterCache(self.path)
        changes = cache.apply([ParamUpdate(name="gnc.HEARTBEAT", value=1, ts_ms=1000, display_only=True)])
        self.assertEqual(changes, [{"name": "gnc.HEARTBEAT", "v": 1, "t": 1000, "display_only": True}])
        self.assertEqual(cache.replay(), [])
        self.assertFalse(self.path.exists())

    def test_replay_returns_persisted_state(self) -> None:
        cache = ParameterCache(self.path)
        cache.apply([
            ParamUpdate(name="gnc.RATE", value=[1, 2, 3], ts_ms=1000),
            ParamUpdate(name="eps.V_BUS", value=12.0, ts_ms=2000),
        ])
        names = {s["name"] for s in cache.replay()}
        self.assertEqual(names, {"gnc.RATE", "eps.V_BUS"})

    def test_persistence_roundtrip(self) -> None:
        cache = ParameterCache(self.path)
        cache.apply([ParamUpdate(name="eps.V_BUS", value=12.0, ts_ms=2000)])
        cache2 = ParameterCache(self.path)
        self.assertEqual(cache2.replay(), [{"name": "eps.V_BUS", "v": 12.0, "t": 2000}])

    def test_persistence_tolerates_malformed_file(self) -> None:
        self.path.write_text("not json")
        self.assertEqual(ParameterCache(self.path).replay(), [])

    def test_clear_group_removes_prefix(self) -> None:
        cache = ParameterCache(self.path)
        cache.apply([
            ParamUpdate(name="gnc.RATE", value=[1, 2, 3], ts_ms=1000),
            ParamUpdate(name="gnc.MAG", value=[4, 5, 6], ts_ms=1000),
            ParamUpdate(name="eps.V_BUS", value=12.0, ts_ms=1000),
        ])
        self.assertEqual(cache.clear_group("gnc"), 2)
        self.assertEqual({s["name"] for s in cache.replay()}, {"eps.V_BUS"})

    def test_clear_group_does_not_match_prefix_substring(self) -> None:
        cache = ParameterCache(self.path)
        cache.apply([
            ParamUpdate(name="gnc.RATE", value=1, ts_ms=1000),
            ParamUpdate(name="gncx.OTHER", value=2, ts_ms=1000),
        ])
        cache.clear_group("gnc")
        self.assertEqual({s["name"] for s in cache.replay()}, {"gncx.OTHER"})


if __name__ == "__main__":
    unittest.main()
