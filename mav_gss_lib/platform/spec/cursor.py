"""Cursors — encapsulate the layout dispatch.

BitCursor: byte-aligned reads for normal ParameterType decoding (parser
rejects non-byte-multiple size_bits on scalars), plus sub-byte
`read_bits(n)` for the bitfield decoder. LSB-first relative to the
underlying byte.

TokenCursor: ASCII-tokens layout. `read_token()` returns the next
whitespace-delimited token; `read_remaining_bytes()` returns the bytes
past the last whitespace boundary (for ascii_tokens + trailing binary
blob — `img_get_chunks`).
"""

from __future__ import annotations


class BitCursor:
    __slots__ = ("_buf", "_byte_pos", "_bit_remainder", "_bit_remainder_size")

    def __init__(self, buf: bytes) -> None:
        self._buf = buf
        self._byte_pos = 0
        self._bit_remainder = 0
        self._bit_remainder_size = 0

    def read_bytes(self, n: int) -> bytes:
        if self._bit_remainder_size:
            raise ValueError(
                "BitCursor.read_bytes requires byte alignment "
                f"(have {self._bit_remainder_size} bits buffered)"
            )
        if self._byte_pos + n > len(self._buf):
            raise IndexError(
                f"BitCursor underrun: need {n} bytes, have {self.remaining_bytes()}"
            )
        out = self._buf[self._byte_pos:self._byte_pos + n]
        self._byte_pos += n
        return bytes(out)

    def read_bits(self, n: int) -> int:
        value = 0
        bits_collected = 0
        while bits_collected < n:
            if self._bit_remainder_size == 0:
                if self._byte_pos >= len(self._buf):
                    raise IndexError(
                        f"BitCursor underrun: need {n - bits_collected} more bit(s)"
                    )
                self._bit_remainder = self._buf[self._byte_pos]
                self._bit_remainder_size = 8
                self._byte_pos += 1
            take = min(n - bits_collected, self._bit_remainder_size)
            mask = (1 << take) - 1
            chunk = self._bit_remainder & mask
            value |= chunk << bits_collected
            self._bit_remainder >>= take
            self._bit_remainder_size -= take
            bits_collected += take
        return value

    def remaining_bytes(self) -> int:
        if self._bit_remainder_size:
            return 0
        return len(self._buf) - self._byte_pos

    def remaining_bits(self) -> int:
        return (
            self._bit_remainder_size
            + (len(self._buf) - self._byte_pos) * 8
        )


class TokenCursor:
    __slots__ = ("_buf", "_tokens", "_idx", "_post_whitespace_offset")

    def __init__(self, buf: bytes) -> None:
        self._buf = buf
        text = buf.decode("ascii", errors="replace")
        self._tokens = text.split()
        self._idx = 0
        self._post_whitespace_offset = 0

    def read_token(self) -> str:
        if self._idx >= len(self._tokens):
            raise IndexError(
                f"TokenCursor underrun: no more tokens (read {self._idx})"
            )
        token = self._tokens[self._idx]
        self._idx += 1
        # Advance the post-whitespace offset to right after this token's bytes
        encoded = token.encode("ascii", errors="replace")
        idx = self._buf.find(encoded, self._post_whitespace_offset)
        if idx >= 0:
            self._post_whitespace_offset = idx + len(encoded)
        return token

    def read_remaining_bytes(self) -> bytes:
        # Return everything after the last whitespace boundary that follows
        # the most recently read token.
        offset = self._post_whitespace_offset
        # Skip whitespace bytes
        while offset < len(self._buf) and self._buf[offset:offset + 1] in (b" ", b"\t", b"\n", b"\r"):
            offset += 1
        out = self._buf[offset:]
        self._post_whitespace_offset = len(self._buf)
        self._idx = len(self._tokens)
        return bytes(out)

    def remaining_tokens(self) -> int:
        return len(self._tokens) - self._idx


__all__ = ["BitCursor", "TokenCursor"]
