"""Server-side telemetry endpoints + one-shot legacy-snapshot cleanup.

Type and router live in `mav_gss_lib.platform.telemetry`.
"""
import logging
from pathlib import Path

_LEGACY_V1_FILES = (".eps_snapshot.json", ".gnc_snapshot.json")


def reset_legacy_snapshots(log_dir: str | Path) -> list[str]:
    """Remove pre-split-state snapshot files from <log_dir>.

    Returns the list of paths that were removed, for logging.
    Intended to run exactly once per host on first startup after the
    split-state upgrade; idempotent (a clean host returns []).
    """
    removed: list[str] = []
    for name in _LEGACY_V1_FILES:
        p = Path(log_dir) / name
        if p.exists():
            try:
                p.unlink()
                removed.append(str(p))
            except OSError as e:
                logging.warning("legacy snapshot reset: could not unlink %s (%s)", p, e)
    return removed


__all__ = ["reset_legacy_snapshots"]
