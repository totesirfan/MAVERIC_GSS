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
