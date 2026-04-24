"""bootstrap_dependencies — pre-import environment check.

Stdlib-only. Called from MAV_WEB.py before any non-stdlib import; any
transitive non-stdlib import here would defeat the bootstrap guard.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

from . import _helpers
from . import status as _status


def bootstrap_dependencies() -> None:
    """Pre-import environment check. Called at the top of MAV_WEB.py.

    Two jobs:
      1. Auto-heal a zip-extracted tree into a real clone of REPO_URL so the
         self-updater keeps working on GitHub "Download ZIP" installs.
      2. Verify all pip-installable runtime modules import. If anything is
         missing, print a one-line pip command and exit — the operator runs
         it from their conda env and relaunches. This replaces the old
         auto-install flow; keeping dep management out of the updater makes
         the running process's Python stable (no mid-session interpreter
         swaps, no PEP 668 edge cases, no venv bookkeeping).
    """
    # Zip-extract auto-heal. Runs before any non-stdlib import so a fresh
    # zip install becomes a real clone on its very first launch.
    if not _status.DEV_SENTINEL_PATH.exists():
        needs_heal = not (_status.REPO_ROOT / ".git").exists()
        if not needs_heal:
            try:
                r = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=str(_status.REPO_ROOT),
                    capture_output=True,
                    text=True,
                    timeout=5.0,
                    env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                )
                needs_heal = r.returncode != 0
            except Exception:
                needs_heal = True
        if needs_heal:
            print(
                "[MAV GSS] initializing git repository from zip extract (first launch)...",
                flush=True,
            )
            err = _helpers._ensure_git_repo(timeout_s=60.0)
            if err:
                print(f"[MAV GSS] git init failed: {err}", file=sys.stderr, flush=True)
                print(
                    "[MAV GSS] self-updater disabled; reinstall via `git clone` to enable updates.",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                print("[MAV GSS] git repository initialized.", flush=True)

    # Hard prerequisites (GNU Radio / pmt) — no recovery path.
    for module, instructions in _status._HARD_PREREQUISITES:
        if importlib.util.find_spec(module) is None:
            print(f"[MAV GSS] {instructions}", file=sys.stderr, flush=True)
            sys.exit(3)

    # Soft prerequisites (pip-installable).
    missing = [m for m in _status._CRITICAL_MODULES if importlib.util.find_spec(m) is None]
    if not missing:
        return

    print(
        f"[MAV GSS] missing Python packages: {', '.join(missing)}\n"
        f"          Install them with:\n"
        f"              pip install -r {_status.REQUIREMENTS_PATH}\n"
        f"          (run inside your radioconda env, then relaunch)",
        file=sys.stderr,
        flush=True,
    )
    sys.exit(2)
