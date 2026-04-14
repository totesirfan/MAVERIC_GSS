"""Unit tests for imaging pair-derivation helpers."""
import pytest

from mav_gss_lib.missions.maveric.imaging import (
    derive_thumb_filename,
    derive_full_filename,
)


class TestDeriveThumbFilename:
    def test_prefix_prepended(self):
        assert derive_thumb_filename("limb_003.jpg", "thumb_") == "thumb_limb_003.jpg"

    def test_empty_prefix_returns_none(self):
        assert derive_thumb_filename("limb_003.jpg", "") is None

    def test_none_prefix_returns_none(self):
        assert derive_thumb_filename("limb_003.jpg", None) is None

    def test_works_with_non_jpg_names(self):
        assert derive_thumb_filename("data.bin", "t_") == "t_data.bin"


class TestDeriveFullFilename:
    def test_prefix_stripped(self):
        assert derive_full_filename("thumb_limb_003.jpg", "thumb_") == "limb_003.jpg"

    def test_empty_prefix_returns_none(self):
        assert derive_full_filename("thumb_limb_003.jpg", "") is None

    def test_no_prefix_match_returns_none(self):
        # Filename doesn't start with the prefix — not a thumb.
        assert derive_full_filename("limb_003.jpg", "thumb_") is None

    def test_partial_match_returns_none(self):
        # "thum_" is not "thumb_"
        assert derive_full_filename("thum_limb_003.jpg", "thumb_") is None


from mav_gss_lib.missions.maveric.imaging import ImageAssembler


def _seed_assembler(tmp_path, totals):
    """Build an ImageAssembler with the given {filename: total} mapping."""
    asm = ImageAssembler(output_dir=str(tmp_path))
    for fn, total in totals.items():
        asm.set_total(fn, total)
    return asm


class TestPairedStatus:
    def test_full_and_thumb_grouped_into_one_pair(self, tmp_path):
        asm = _seed_assembler(tmp_path, {
            "limb_003.jpg": 84,
            "thumb_limb_003.jpg": 12,
        })
        result = asm.paired_status(prefix="thumb_")
        pairs = result["files"]
        assert len(pairs) == 1
        pair = pairs[0]
        assert pair["stem"] == "limb_003.jpg"
        assert pair["full"]["filename"] == "limb_003.jpg"
        assert pair["full"]["total"] == 84
        assert pair["thumb"]["filename"] == "thumb_limb_003.jpg"
        assert pair["thumb"]["total"] == 12

    def test_orphan_full_gets_thumb_placeholder(self, tmp_path):
        """With prefix set, a lone full gets a derived thumb placeholder leaf."""
        asm = _seed_assembler(tmp_path, {"limb_003.jpg": 84})
        pairs = asm.paired_status(prefix="thumb_")["files"]
        assert len(pairs) == 1
        assert pairs[0]["stem"] == "limb_003.jpg"
        assert pairs[0]["full"] is not None
        assert pairs[0]["full"]["total"] == 84
        # Thumb is a placeholder, not None
        assert pairs[0]["thumb"] is not None
        assert pairs[0]["thumb"]["filename"] == "thumb_limb_003.jpg"
        assert pairs[0]["thumb"]["total"] is None
        assert pairs[0]["thumb"]["received"] == 0
        assert pairs[0]["thumb"]["complete"] is False

    def test_orphan_thumb_gets_full_placeholder(self, tmp_path):
        """With prefix set, a lone thumb gets a derived full placeholder leaf."""
        asm = _seed_assembler(tmp_path, {"thumb_limb_003.jpg": 12})
        pairs = asm.paired_status(prefix="thumb_")["files"]
        assert len(pairs) == 1
        assert pairs[0]["stem"] == "limb_003.jpg"
        assert pairs[0]["thumb"] is not None
        assert pairs[0]["thumb"]["total"] == 12
        # Full is a placeholder
        assert pairs[0]["full"] is not None
        assert pairs[0]["full"]["filename"] == "limb_003.jpg"
        assert pairs[0]["full"]["total"] is None
        assert pairs[0]["full"]["received"] == 0

    def test_empty_prefix_disables_pairing(self, tmp_path):
        """With prefix empty, every file is an unpaired single-file entry with thumb=None."""
        asm = _seed_assembler(tmp_path, {
            "limb_003.jpg": 84,
            "thumb_limb_003.jpg": 12,
        })
        pairs = asm.paired_status(prefix="")["files"]
        assert len(pairs) == 2
        for p in pairs:
            assert p["thumb"] is None
            assert p["full"] is not None

    def test_scheduled_capture_recovery(self, tmp_path):
        """Operator runs img_cnt_chunks on a never-before-seen file; grouping
        exposes both sides via placeholder — the scheduled-capture recovery
        path from spec §6.3."""
        asm = _seed_assembler(tmp_path, {"scheduled_007.jpg": 60})
        pairs = asm.paired_status(prefix="thumb_")["files"]
        assert len(pairs) == 1
        pair = pairs[0]
        assert pair["stem"] == "scheduled_007.jpg"
        assert pair["full"]["total"] == 60
        assert pair["thumb"]["filename"] == "thumb_scheduled_007.jpg"
        assert pair["thumb"]["total"] is None

    def test_multiple_pairs_sorted_by_stem(self, tmp_path):
        asm = _seed_assembler(tmp_path, {
            "limb_003.jpg": 84,
            "thumb_limb_003.jpg": 12,
            "city_002.jpg": 120,
            "thumb_city_002.jpg": 18,
        })
        pairs = asm.paired_status(prefix="thumb_")["files"]
        assert len(pairs) == 2
        stems = [p["stem"] for p in pairs]
        assert stems == sorted(stems)

    def test_leaf_includes_chunk_size(self, tmp_path):
        """Leaves expose chunk_size from assembler state (None if not set)."""
        asm = _seed_assembler(tmp_path, {"limb_003.jpg": 84})
        asm.chunk_sizes["limb_003.jpg"] = 150
        pairs = asm.paired_status(prefix="thumb_")["files"]
        assert pairs[0]["full"]["chunk_size"] == 150
        # Placeholder thumb has no chunk_size
        assert pairs[0]["thumb"]["chunk_size"] is None
