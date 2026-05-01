"""Tests for AiiKindAdapter — JSON inventory file behavior."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from mav_gss_lib.missions.maveric.files.adapters import AiiKindAdapter
from mav_gss_lib.missions.maveric.files.store import ChunkFileStore, FileRef


class AiiKindAdapterTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.store = ChunkFileStore(self.root)
        self.adapter = AiiKindAdapter()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_seed_from_cnt_yields_single_pair(self):
        seeds = list(self.adapter.seed_from_cnt({
            "status": "0", "filename": "inventory.json", "num_chunks": "5",
        }))
        self.assertEqual(seeds, [("inventory.json", 5)])

    def test_seed_from_capture_yields_nothing(self):
        seeds = list(self.adapter.seed_from_capture({"filename": "x.json", "num_chunks": "1"}))
        self.assertEqual(seeds, [])

    def test_partial_repair_is_noop(self):
        path = os.path.join(self.root, "test.json")
        with open(path, "wb") as f:
            f.write(b'{"partial":')
        self.adapter.partial_repair(path)
        self.assertEqual(open(path, "rb").read(), b'{"partial":')

    def test_on_complete_validates_well_formed_json(self):
        path = os.path.join(self.root, "good.json")
        with open(path, "w") as f:
            f.write('{"items": [1, 2, 3]}')
        self.assertEqual(self.adapter.on_complete(path), {"valid": True})

    def test_on_complete_flags_malformed_json(self):
        path = os.path.join(self.root, "bad.json")
        with open(path, "w") as f:
            f.write('{"items": [1, 2, 3')
        self.assertEqual(self.adapter.on_complete(path), {"valid": False})

    def test_status_view_reads_cached_valid_from_extras(self):
        # Caller (events watcher) is responsible for writing extras after
        # on_complete fires. status_view itself never re-parses files.
        ref = FileRef(kind="aii", source="HLNV", filename="i.json")
        self.store.set_total(ref, 1)
        self.store.feed_chunk(ref, 0, b'{"ok":true}')
        self.store.set_extras(ref, valid=True)
        view = self.adapter.status_view(self.store)
        leaf = view["files"][0]
        self.assertEqual(leaf["filename"], "i.json")
        self.assertTrue(leaf["complete"])
        self.assertTrue(leaf["valid"])

    def test_status_view_valid_none_when_extras_absent(self):
        ref = FileRef(kind="aii", source="HLNV", filename="i.json")
        self.store.set_total(ref, 1)
        view = self.adapter.status_view(self.store)
        self.assertIsNone(view["files"][0]["valid"])


if __name__ == "__main__":
    unittest.main()
