"""TelemetryRouter — platform-owned telemetry dispatch + per-domain registry.

Missions register domains at startup (name + merge policy + optional
entry loader + optional catalog provider). The router owns canonical
state I/O and websocket-message shaping; it has no compile-time
knowledge of mission vocabulary.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .fragment import TelemetryFragment
from .policy import MergePolicy, lww_by_ts
from .state import DomainState, EntryLoader

CatalogProvider = Callable[[], Any]


class TelemetryRouter:
    """Platform-owned telemetry dispatch + registry.

    Domains are registered by the active mission at init. The platform
    has no compile-time knowledge of which domains exist, what merge
    policy they want, or what metadata they expose. Every extension
    point is supplied by the mission at registration time.
    """

    def __init__(self, root_dir: Path) -> None:
        self.root = Path(root_dir)
        self._states: dict[str, DomainState] = {}
        self._catalogs: dict[str, CatalogProvider] = {}

    def register_domain(
        self,
        name: str,
        *,
        merge: MergePolicy = lww_by_ts,
        load_entries: Optional[EntryLoader] = None,
        catalog: Optional[CatalogProvider] = None,
    ) -> None:
        """Register a domain with its merge policy, optional persisted-entry
        loader, and optional catalog.

        `merge` defaults to last-write-wins by receive timestamp. Pass
        a different callable for event-time ordering, sequence gating,
        TTL, source priority, etc.

        `load_entries`, if supplied, receives the raw per-key dict
        read from disk on startup and returns the dict to install as
        initial state. Use this to validate, version-gate, or migrate
        entries produced by an earlier incarnation of the merge
        policy. Default is identity — fine for the LWW shape since
        the next fragment overwrites anything stale.

        `catalog`, if supplied, is a zero-arg callable returning
        JSON-serializable mission metadata for the domain. Served
        verbatim at GET /api/telemetry/{name}/catalog. Platform does
        not inspect the shape.
        """
        if name in self._states:
            return
        self._states[name] = DomainState(
            self.root / f"{name}.json",
            merge=merge,
            load_entries=load_entries,
        )
        if catalog is not None:
            self._catalogs[name] = catalog

    def ingest(self, fragments: Iterable[TelemetryFragment]) -> list[dict]:
        by_domain: dict[str, list[TelemetryFragment]] = {}
        for f in fragments:
            if f.display_only:
                # Display-only fragments feed rendering + logs but do
                # not contribute to canonical domain state.
                continue
            if f.domain in self._states:
                by_domain.setdefault(f.domain, []).append(f)
        out: list[dict] = []
        for domain, frags in by_domain.items():
            changes = self._states[domain].apply(frags)
            if changes:
                out.append({"type": "telemetry", "domain": domain, "changes": changes})
        return out

    def replay(self) -> list[dict]:
        msgs: list[dict] = []
        for domain, state in self._states.items():
            snap = state.snapshot()
            if snap:
                msgs.append({
                    "type": "telemetry", "domain": domain,
                    "changes": snap, "replay": True,
                })
        return msgs

    def clear(self, domain: str) -> dict | None:
        state = self._states.get(domain)
        if state is None:
            return None
        state.clear()
        return {"type": "telemetry", "domain": domain, "cleared": True}

    def get_catalog(self, domain: str) -> Any:
        """Return mission-supplied catalog for `domain`, or None."""
        fn = self._catalogs.get(domain)
        return fn() if fn else None

    def has_domain(self, domain: str) -> bool:
        return domain in self._states
