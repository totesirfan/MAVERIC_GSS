"""Tests for the format-agnostic ChunkFileStore.

Covers chunk persistence, progress tracking, restore-on-startup, dedup,
auto-assembly, completion cleanup, source/kind keying, and the
adapter-private ``extras`` channel. No format hooks are exercised
here — those live in adapter tests.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

from mav_gss_lib.missions.maveric.files.store import ChunkFileStore, FileRef


class ChunkFileStoreTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _ref(self, kind="image", source="HLNV", filename="capture.jpg"):
        return FileRef(kind=kind, source=source, filename=filename)

    def test_set_total_creates_placeholder_and_meta(self):
        store = ChunkFileStore(self.root)
        ref = self._ref()
        store.set_total(ref, 3)
        path = store.file_path(ref)
        meta_path = store.meta_path(ref)
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(os.path.getsize(path), 0)
        self.assertTrue(os.path.isfile(meta_path))
        meta = json.loads(open(meta_path).read())
        self.assertEqual(meta["total"], 3)
        self.assertEqual(meta["kind"], "image")
        self.assertEqual(meta["source"], "HLNV")

    def test_feed_chunk_assembles_in_order(self):
        store = ChunkFileStore(self.root)
        ref = self._ref()
        store.set_total(ref, 3)
        result = None
        for idx, payload in enumerate([b"ABC", b"DEF", b"GHI"]):
            result = store.feed_chunk(ref, idx, payload)
        assert result is not None
        self.assertTrue(result.complete)
        self.assertEqual(result.received, 3)
        self.assertEqual(result.total, 3)
        self.assertEqual(open(store.file_path(ref), "rb").read(), b"ABCDEFGHI")

    def test_feed_chunk_dedup_is_idempotent(self):
        store = ChunkFileStore(self.root)
        ref = self._ref()
        store.set_total(ref, 2)
        store.feed_chunk(ref, 0, b"ABC")
        result = store.feed_chunk(ref, 0, b"ABC")
        self.assertFalse(result.complete)
        self.assertEqual(result.received, 1)

    def test_partial_assembly_stops_at_gap(self):
        store = ChunkFileStore(self.root)
        ref = self._ref()
        store.set_total(ref, 3)
        store.feed_chunk(ref, 0, b"ABC")
        store.feed_chunk(ref, 2, b"GHI")
        # Only chunk 0 is contiguous; assembled file contains only "ABC".
        self.assertEqual(open(store.file_path(ref), "rb").read(), b"ABC")

    def test_kind_namespacing_keeps_image_and_aii_separate(self):
        store = ChunkFileStore(self.root)
        image_ref = self._ref(kind="image", filename="capture.jpg")
        aii_ref = self._ref(kind="aii", filename="capture.jpg")  # SAME filename
        store.set_total(image_ref, 1)
        store.set_total(aii_ref, 1)
        store.feed_chunk(image_ref, 0, b"JPEG")
        store.feed_chunk(aii_ref, 0, b"JSON")
        self.assertEqual(open(store.file_path(image_ref), "rb").read(), b"JPEG")
        self.assertEqual(open(store.file_path(aii_ref), "rb").read(), b"JSON")

    def test_source_namespacing_within_one_kind(self):
        store = ChunkFileStore(self.root)
        hlnv = self._ref(source="HLNV")
        astr = self._ref(source="ASTR")
        store.set_total(hlnv, 1)
        store.set_total(astr, 1)
        store.feed_chunk(hlnv, 0, b"FROM_HLNV")
        store.feed_chunk(astr, 0, b"FROM_ASTR")
        self.assertEqual(open(store.file_path(hlnv), "rb").read(), b"FROM_HLNV")
        self.assertEqual(open(store.file_path(astr), "rb").read(), b"FROM_ASTR")

    def test_completion_cleans_chunks_dir(self):
        store = ChunkFileStore(self.root)
        ref = self._ref()
        store.set_total(ref, 1)
        store.feed_chunk(ref, 0, b"DATA")
        self.assertFalse(os.path.isdir(store.chunks_dir_for(ref)))

    def test_restore_after_restart(self):
        store = ChunkFileStore(self.root)
        ref = self._ref()
        store.set_total(ref, 3)
        store.feed_chunk(ref, 0, b"ABC")
        store.feed_chunk(ref, 2, b"GHI")  # gap
        store2 = ChunkFileStore(self.root)
        received, total = store2.progress(ref)
        self.assertEqual(received, 2)
        self.assertEqual(total, 3)
        self.assertFalse(store2.is_complete(ref))

    def test_set_total_resets_on_total_change(self):
        store = ChunkFileStore(self.root)
        ref = self._ref()
        store.set_total(ref, 3)
        store.feed_chunk(ref, 0, b"OLD")
        store.set_total(ref, 5)  # new transfer for same name
        received, total = store.progress(ref)
        self.assertEqual(received, 0)
        self.assertEqual(total, 5)

    def test_known_files_filtered_by_kind(self):
        store = ChunkFileStore(self.root)
        store.set_total(self._ref(kind="image", filename="a.jpg"), 1)
        store.set_total(self._ref(kind="aii", filename="b.json"), 1)
        store.set_total(self._ref(kind="mag", filename="c.nvg"), 1)
        self.assertEqual(len(store.known_files()), 3)
        self.assertEqual(len(store.known_files(kind="image")), 1)
        self.assertEqual(store.known_files(kind="image")[0].filename, "a.jpg")

    def test_delete_file_removes_state_and_disk(self):
        store = ChunkFileStore(self.root)
        ref = self._ref()
        store.set_total(ref, 1)
        store.feed_chunk(ref, 0, b"DATA")
        store.delete_file(ref)
        self.assertFalse(os.path.exists(store.file_path(ref)))
        self.assertEqual(store.progress(ref), (0, None))

    def test_extras_round_trip_in_meta(self):
        store = ChunkFileStore(self.root)
        ref = self._ref(kind="aii", filename="i.json")
        store.set_total(ref, 1)
        store.set_extras(ref, valid=True, foo="bar")
        self.assertEqual(store.get_extras(ref), {"valid": True, "foo": "bar"})
        # Survives restart.
        store2 = ChunkFileStore(self.root)
        self.assertEqual(store2.get_extras(ref), {"valid": True, "foo": "bar"})

    def test_extras_cleared_when_total_changes(self):
        store = ChunkFileStore(self.root)
        ref = self._ref(kind="aii", filename="i.json")
        store.set_total(ref, 1)
        store.set_extras(ref, valid=True)
        store.set_total(ref, 2)  # new transfer
        self.assertEqual(store.get_extras(ref), {})

    def test_duplicate_chunk_after_completion_is_idempotent(self):
        """Late duplicate chunks must not corrupt a completed transfer."""
        store = ChunkFileStore(self.root)
        ref = self._ref()
        store.set_total(ref, 3)
        store.feed_chunk(ref, 0, b"AAA")
        store.feed_chunk(ref, 1, b"BBB")
        result = store.feed_chunk(ref, 2, b"CCC")
        self.assertTrue(result.complete)
        original = open(store.file_path(ref), "rb").read()
        self.assertEqual(original, b"AAABBBCCC")
        # Replay an already-delivered chunk after completion.
        late = store.feed_chunk(ref, 0, b"ZZZ")
        self.assertTrue(late.complete)
        self.assertEqual(late.received, 3)
        self.assertEqual(late.total, 3)
        # File on disk must be unchanged.
        self.assertEqual(open(store.file_path(ref), "rb").read(), b"AAABBBCCC")

    def test_feed_chunk_rejects_negative_index(self):
        store = ChunkFileStore(self.root)
        ref = self._ref()
        store.set_total(ref, 2)
        with self.assertRaises(ValueError):
            store.feed_chunk(ref, -1, b"X")
        # State is unchanged.
        self.assertEqual(store.progress(ref), (0, 2))

    def test_feed_chunk_rejects_index_at_or_above_total(self):
        store = ChunkFileStore(self.root)
        ref = self._ref()
        store.set_total(ref, 2)
        with self.assertRaises(ValueError):
            store.feed_chunk(ref, 2, b"X")
        with self.assertRaises(ValueError):
            store.feed_chunk(ref, 5, b"X")
        self.assertEqual(store.progress(ref), (0, 2))

    def test_completion_requires_contiguous_coverage(self):
        """Right count, wrong coverage must NOT mark complete.

        The store enforces this even though the events watcher already
        rejects out-of-range indices — defense in depth.
        """
        store = ChunkFileStore(self.root)
        ref = self._ref()
        store.set_total(ref, 3)
        # Inject indices via the public API. With out-of-range rejected,
        # the only way to land here legitimately is to feed 0..total-1.
        # We seed via the internal received[] to assert the invariant.
        store._validate_ref(ref)
        store.received[ref] = {1, 2}
        self.assertFalse(store._is_complete(ref))
        store.received[ref] = {0, 1, 2}
        self.assertTrue(store._is_complete(ref))



class StoreHasNoMavericImportsTests(unittest.TestCase):
    """Guardrail: store.py must not import any maveric module.

    The store is the only piece of the redesign that's intentionally
    mission-decoupled. If a future change adds `from
    mav_gss_lib.missions.maveric.foo import bar` here, this test fails.
    """

    def test_store_module_has_no_maveric_imports(self):
        # Force a clean import.
        modname = "mav_gss_lib.missions.maveric.files.store"
        sys.modules.pop(modname, None)
        import mav_gss_lib.missions.maveric.files.store as store_module  # noqa: F401
        loaded = [
            name for name in sys.modules
            if name.startswith("mav_gss_lib.missions.maveric.")
            and name != "mav_gss_lib.missions.maveric.files"
            and name != "mav_gss_lib.missions.maveric.files.store"
        ]
        # Side-effects of test discovery may load other maveric modules
        # before this test runs. We only care about the transitive closure
        # of store.py itself — re-import in a fresh module context.
        import importlib.util
        spec = importlib.util.find_spec(modname)
        assert spec is not None and spec.origin
        with open(spec.origin) as f:
            source = f.read()
        # Static check: literal forbidden import substrings.
        for pattern in (
            "from mav_gss_lib.missions.maveric",
            "import mav_gss_lib.missions.maveric",
        ):
            self.assertNotIn(
                pattern, source,
                f"store.py must not contain {pattern!r} — keep it mission-decoupled",
            )


if __name__ == "__main__":
    unittest.main()
