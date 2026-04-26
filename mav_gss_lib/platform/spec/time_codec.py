"""AbsoluteTime millis_u64 codec.

Decodes 8 LE bytes (u64 ms since Unix epoch) into a JSON-safe dict so
ParamUpdate values can be persisted via json.dumps without crashing.
Shape matches today's MAVERIC `_spacecraft_time` exactly.
"""

from __future__ import annotations

import struct
from datetime import datetime, timezone
from typing import Any


def encode_millis_u64(value: int | datetime) -> bytes:
    if isinstance(value, datetime):
        value = int(value.timestamp() * 1000)
    return struct.pack("<Q", int(value))


def decode_millis_u64(wire: bytes) -> dict[str, Any]:
    unix_ms = struct.unpack("<Q", wire)[0]
    try:
        dt = datetime.fromtimestamp(unix_ms / 1000.0, tz=timezone.utc)
        iso = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        return {"unix_ms": unix_ms, "iso_utc": iso, "display": iso}
    except (OverflowError, ValueError, OSError):
        return {"unix_ms": unix_ms, "iso_utc": None, "display": f"raw={unix_ms}"}


__all__ = ["encode_millis_u64", "decode_millis_u64"]
