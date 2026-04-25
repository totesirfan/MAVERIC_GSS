import unittest

from mav_gss_lib.platform.spec.cursor import BitCursor, TokenCursor


class TestBitCursor(unittest.TestCase):
    def test_read_bytes_advances_byte_aligned(self):
        c = BitCursor(b"\x01\x02\x03\x04")
        self.assertEqual(c.read_bytes(2), b"\x01\x02")
        self.assertEqual(c.remaining_bytes(), 2)
        self.assertEqual(c.read_bytes(2), b"\x03\x04")
        self.assertEqual(c.remaining_bytes(), 0)

    def test_read_bits_lsb_first(self):
        # 0b10110001 — read LSB first 3 bits → 0b001 = 1, then 5 bits → 0b10110 = 22
        c = BitCursor(b"\xb1")
        self.assertEqual(c.read_bits(3), 0b001)
        self.assertEqual(c.read_bits(5), 0b10110)

    def test_remaining_bits_after_read_bytes(self):
        c = BitCursor(b"\x01\x02\x03")
        c.read_bytes(1)
        self.assertEqual(c.remaining_bits(), 16)


class TestTokenCursor(unittest.TestCase):
    def test_read_token_splits_on_whitespace(self):
        c = TokenCursor(b"alpha 12 3.14")
        self.assertEqual(c.read_token(), "alpha")
        self.assertEqual(c.read_token(), "12")
        self.assertEqual(c.read_token(), "3.14")
        self.assertEqual(c.remaining_tokens(), 0)

    def test_read_remaining_bytes_returns_post_whitespace_blob(self):
        c = TokenCursor(b"file.bin 4 \x01\x02\x03\x04")
        self.assertEqual(c.read_token(), "file.bin")
        self.assertEqual(c.read_token(), "4")
        self.assertEqual(c.read_remaining_bytes(), b"\x01\x02\x03\x04")

    def test_remaining_tokens_counts_unread(self):
        c = TokenCursor(b"a b c")
        self.assertEqual(c.remaining_tokens(), 3)
        c.read_token()
        self.assertEqual(c.remaining_tokens(), 2)


if __name__ == "__main__":
    unittest.main()
