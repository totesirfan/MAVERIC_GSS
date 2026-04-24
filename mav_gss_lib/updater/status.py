"""Updater data model — constants, exceptions, status dataclass.

Stdlib-only. Imported by bootstrap, check, apply, and the package facade.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional


# =============================================================================
#  PATHS & CONSTANTS
# =============================================================================

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS_PATH = REPO_ROOT / "requirements.txt"

# Canonical upstream — baked in so a GitHub zip extract can self-heal into a
# real clone on first launch. GitHub zip archives carry no .git metadata, so
# without this the updater would permanently report "could not reach origin"
# on any operator laptop that wasn't set up with `git clone`.
REPO_URL = "https://github.com/totesirfan/MAVERIC_GSS.git"
DEFAULT_BRANCH = "main"

# Developer opt-out sentinel. If this file exists at the repo root, the updater
# refuses to fetch or apply anything — the Updates check renders as a skip with
# "dev mode" as the reason, and the APPLY UPDATE button never appears. Create
# with `touch .mav_dev`. Gitignored so it doesn't leak to operator clones.
DEV_SENTINEL_PATH = REPO_ROOT / ".mav_dev"


# Hard prerequisites — cannot be auto-installed. If missing, print instructions
# and exit. The operator must resolve these one-time, then relaunch.
_HARD_PREREQUISITES: list[tuple[str, str]] = [
    (
        "pmt",
        "GNU Radio / pmt not found.\n"
        "          Install radioconda and activate it: conda activate gnuradio\n"
        "          https://github.com/ryanvolz/radioconda",
    ),
]

# Soft prerequisites — pip-installable leaves. These can be auto-recovered.
#
# _CRITICAL_MODULES is the set that the pre-import bootstrap checks. If any of
# these are missing, MAV_WEB.py cannot reach FastAPI startup at all, so the
# bootstrap self-installs them before importing anything non-stdlib. Kept short
# because pre-import bootstrap runs before any UI exists.
#
# _ALL_PIP_MODULES is the FULL set of every pip-installable import listed in
# requirements.txt. Used at runtime (not at bootstrap) to detect drift for any
# package, not just the critical four. Must be updated whenever requirements.txt
# gains or loses an entry.
#
# Names are the IMPORT name, not the pip package name (PyYAML → yaml, Pillow → PIL).
_CRITICAL_MODULES: list[str] = ["fastapi", "uvicorn", "yaml", "zmq"]

_ALL_PIP_MODULES: list[str] = [
    "fastapi",    # fastapi
    "uvicorn",    # uvicorn
    "websockets", # websockets
    "yaml",       # PyYAML
    "zmq",        # pyzmq
    "crcmod",     # crcmod
    "PIL",        # Pillow
]


# =============================================================================
#  EXCEPTIONS
# =============================================================================

class SubprocessFailed(Exception):
    """Raised on non-zero subprocess exit. Carries the last 10 stderr lines
    as the exception message."""


class DirtyTreeError(Exception):
    """Raised by apply_update's final gate when `git status --porcelain` is
    non-empty. Prevents clobbering uncommitted local work."""


class PreflightError(Exception):
    """Raised by apply_update for any other pre-flight validation failure
    (e.g., cached status is None, no work to do, concurrent update)."""


# =============================================================================
#  DATA MODEL
# =============================================================================

@dataclass
class Commit:
    sha: str
    subject: str


@dataclass
class UpdateStatus:
    current_sha: str = ""
    branch: str = ""
    behind_count: int = 0
    commits: list[Commit] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    working_tree_dirty: bool = False
    missing_pip_deps: list[str] = field(default_factory=list)
    fetch_failed: bool = False
    fetch_error: Optional[str] = None
    update_applied_sha: Optional[str] = None


@dataclass
class Phase:
    name: Literal["git_pull", "countdown", "restart"]
    status: Literal["pending", "running", "ok", "fail"]
    detail: Optional[str] = None
