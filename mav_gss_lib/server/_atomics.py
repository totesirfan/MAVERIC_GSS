"""
mav_gss_lib.server._atomics -- Thread-safe small-state primitives.

Author: Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import threading


class AtomicStatus:
    """Lock-guarded single-string status.

    Always call .get() to read; never serialize the instance directly
    (not JSON-compatible). Callers that need a plain string for logging
    or API responses must do `.get()` explicitly.

    NOT HASHABLE -- the underlying value mutates, so hash would too,
    breaking set/dict-key invariants.
    """
    __slots__ = ("_value", "_lock")

    def __init__(self, initial: str = "OFFLINE"):
        self._value = initial
        self._lock = threading.Lock()

    def get(self) -> str:
        with self._lock:
            return self._value

    def set(self, value: str) -> None:
        with self._lock:
            self._value = value

    def __str__(self) -> str:
        return self.get()

    def __eq__(self, other: object) -> bool:
        return self.get() == (other.get() if isinstance(other, AtomicStatus) else other)

    # Disable hashing -- a mutable value cannot provide a stable hash.
    __hash__ = None
