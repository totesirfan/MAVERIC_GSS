from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .fragment import TelemetryFragment
from .policy import MergePolicy, lww_by_ts

# Mission-owned hook: given the raw per-key dict read from disk,
# return the dict to install as initial state. Filter invalid rows,
# migrate old schema versions, drop expired entries, whatever the
# mission's merge policy requires. Default (None) installs the raw
# dict untouched — fine for the default LWW policy since its shape
# is trivial and the next fragment overwrites any garbage.
EntryLoader = Callable[[dict[str, dict[str, Any]]], dict[str, dict[str, Any]]]


class DomainState:
    """Per-domain canonical state, merge + load policies supplied by the caller.

    Persists atomically on every apply() that produced a change. Load
    is tolerant: a missing or malformed file yields empty state and is
    left on disk untouched until the next successful apply rewrites it.

    The merge policy owns the per-entry shape. Platform code reads
    exactly one field from an entry — `t: int` (ms since epoch) — for
    ordering and replay; everything else is opaque to the platform
    and must remain JSON-serializable. The default policy is
    last-write-wins by receive timestamp, which produces {"v", "t"}
    entries. Custom policies may return any shape they like so long as
    they keep a numeric `t`.

    The load_entries hook is the mission's paired entry-point for
    validating, versioning, or migrating persisted entries before
    they re-enter live state. Missions with a richer policy-specific
    shape should supply both — mismatched pairs are a mission bug,
    not a platform concern.
    """

    def __init__(
        self,
        path: str | Path,
        merge: MergePolicy = lww_by_ts,
        load_entries: Optional[EntryLoader] = None,
    ):
        self.path = Path(path)
        self._merge = merge
        self._load_entries = load_entries
        self._state: dict[str, dict[str, Any]] = {}
        self._load()

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {k: dict(v) for k, v in self._state.items()}

    def apply(self, fragments: Iterable[TelemetryFragment]) -> dict[str, dict[str, Any]]:
        changes: dict[str, dict[str, Any]] = {}
        for f in fragments:
            prev = self._state.get(f.key)
            entry = self._merge(prev, f)
            if entry is None:
                continue
            self._state[f.key] = entry
            changes[f.key] = entry
        if changes:
            self._save()
        return changes

    def clear(self) -> None:
        self._state = {}
        self.path.unlink(missing_ok=True)

    def _load(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.unlink(missing_ok=True)
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
            logging.warning("DomainState: ignoring malformed %s (%s)", self.path, e)
            return
        if not isinstance(data, dict):
            return
        raw = {k: v for k, v in data.items() if isinstance(v, dict)}
        if self._load_entries is not None:
            try:
                self._state = self._load_entries(raw)
            except Exception as e:
                # Mission loader failure — start empty and let the next
                # apply() rewrite the file. Do NOT propagate; a broken
                # load hook should not take down the whole runtime.
                logging.warning(
                    "DomainState[%s]: load_entries raised %s; starting empty",
                    self.path.name, e,
                )
                self._state = {}
        else:
            self._state = raw

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._state, separators=(",", ":")))
        tmp.replace(self.path)
