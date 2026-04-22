"""Merge policies for DomainState.

Platform ships exactly one policy: `lww_by_ts`. Missions that need
different semantics (event-time ordering, sequence-number gating,
TTL expiry, source priority, compound merges, ...) register a
domain with their own callable of the same signature.

Platform contract for the returned entry dict: it MUST contain a
numeric `t` (ms since epoch) for merge/replay ordering. Every other
field — `v` by the default `lww_by_ts` convention, or anything the
mission chooses to include in a custom policy — is opaque to the
platform. The backend persists/serves the dict as-is; no backend
code path reads entry fields other than `t`.
"""
from __future__ import annotations

from typing import Callable, Optional

from .fragment import TelemetryFragment

MergePolicy = Callable[[Optional[dict], TelemetryFragment], Optional[dict]]


def lww_by_ts(prev: Optional[dict], frag: TelemetryFragment) -> Optional[dict]:
    """Last-write-wins by receive timestamp.

    Drops fragments strictly older than the stored entry; ties
    overwrite. This policy's on-wire and on-disk per-entry shape is
    {"v", "t"}; `t` is the platform-required ordering field, `v` is
    this policy's convention for the payload. Custom policies are
    free to return richer shapes provided they still include `t`.
    """
    if prev is not None and frag.ts_ms < prev["t"]:
        return None
    return {"v": frag.value, "t": frag.ts_ms}
