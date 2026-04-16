"""Tests for the AX.25 noise filter (gr-satellites garbage-frame drop)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.protocols.frame_detect import is_noise_frame


class TestIsNoiseFrame(unittest.TestCase):
    """Unit tests for the pure detector."""

    def test_ax25_without_delimiter_is_noise(self):
        self.assertTrue(is_noise_frame("AX.25", b"\x01\x02\x03\x04\x05"))

    def test_ax25_with_delimiter_is_not_noise(self):
        payload = b"\xaa" * 14 + b"\x03\xf0" + b"payload"
        self.assertFalse(is_noise_frame("AX.25", payload))

    def test_ax25_with_delimiter_at_offset_zero_is_not_noise(self):
        self.assertFalse(is_noise_frame("AX.25", b"\x03\xf0" + b"whatever"))

    def test_asm_golay_without_delimiter_is_not_noise(self):
        self.assertFalse(is_noise_frame("ASM+GOLAY", b"\x01\x02\x03\x04\x05"))

    def test_unknown_frame_type_is_not_noise(self):
        self.assertFalse(is_noise_frame("UNKNOWN", b"\x01\x02\x03\x04"))

    def test_empty_ax25_payload_is_noise(self):
        self.assertTrue(is_noise_frame("AX.25", b""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
