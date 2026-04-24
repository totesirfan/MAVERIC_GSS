"""Shared envelope helpers for RX/TX log-record builders.

The unified JSONL envelope (see CLAUDE.md "Logging schema") is built in two
sibling modules: ``platform/rx/logging.py`` for inbound packets and
``platform/tx/logging.py`` for outbound commands. Both need the same
``event_id`` generator and the same UTC-ISO timestamp formatter. This module
is their shared, package-private home so neither side has to import from the
other.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def new_event_id() -> str:
    """Opaque 32-hex-char primary key for SQL ingest. Uniqueness-only."""
    return uuid.uuid4().hex


def ts_iso(ms: int) -> str:
    """UTC ISO-8601 with millisecond precision and explicit offset."""
    return (
        datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
    )
