"""Self-updater + dependency bootstrap.

Stdlib-only by contract (MAV_WEB.py imports this before any non-stdlib
module), so any transitive non-stdlib import into this subpackage would
defeat the bootstrap guard.

    status.py    — UpdateStatus + Phase + Commit + exceptions + constants
    _helpers.py  — _run_git, _ensure_git_repo, _clean_dist_strays,
                   _scan_missing_pip_deps, _stream_subprocess, _reexec
    check.py     — check_for_updates (git fetch + diff + dep scan)
    apply.py     — apply_update (git pull, countdown, os.execv restart)
    bootstrap.py — bootstrap_dependencies (pre-import environment check)

Public surface:
    from mav_gss_lib.updater import (
        bootstrap_dependencies, check_for_updates, apply_update,
        UpdateStatus, Commit, Phase,
        DirtyTreeError, PreflightError, SubprocessFailed,
    )

Author:  Irfan Annuar - USC ISI SERC
"""

from .apply import apply_update
from .bootstrap import bootstrap_dependencies
from .check import check_for_updates
from .status import (
    DEFAULT_BRANCH,
    DEV_SENTINEL_PATH,
    REPO_ROOT,
    REPO_URL,
    REQUIREMENTS_PATH,
    Commit,
    DirtyTreeError,
    Phase,
    PreflightError,
    SubprocessFailed,
    UpdateStatus,
)

__all__ = [
    "Commit",
    "DEFAULT_BRANCH",
    "DEV_SENTINEL_PATH",
    "DirtyTreeError",
    "Phase",
    "PreflightError",
    "REPO_ROOT",
    "REPO_URL",
    "REQUIREMENTS_PATH",
    "SubprocessFailed",
    "UpdateStatus",
    "apply_update",
    "bootstrap_dependencies",
    "check_for_updates",
]
