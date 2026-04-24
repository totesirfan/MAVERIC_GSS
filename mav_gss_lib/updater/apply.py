"""apply_update — runs git pull, countdown, then os.execv restart.

Stdlib-only.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import subprocess
import time
from typing import Callable

from . import _helpers
from .status import DirtyTreeError, PreflightError, SubprocessFailed, UpdateStatus


def apply_update(
    broadcast: Callable[[dict], None],
    status: UpdateStatus,
) -> None:
    """Runs phases in order, pushing update_phase events via broadcast, then os.execv.

    Never returns on success (process replaced). Raises DirtyTreeError if the
    working tree became dirty since check_for_updates cached it. Raises
    PreflightError on any other pre-flight validation failure.
    """
    if status is None:
        raise PreflightError("no cached update status")

    # Final dirty-tree gate: re-check right before running any phase.
    _helpers._clean_dist_strays()
    try:
        r = _helpers._run_git(["status", "--porcelain"], timeout=5.0)
    except Exception as exc:
        raise PreflightError(f"git status failed at apply time: {exc}")
    if r.returncode != 0:
        raise PreflightError(
            (r.stderr or "git status failed").strip() or "git status failed"
        )
    if (r.stdout or "").strip():
        raise DirtyTreeError("working tree is dirty")

    new_sha = status.current_sha

    # Phase 1: git_pull — only phase that touches the filesystem now.
    if status.behind_count <= 0:
        raise PreflightError("nothing to update")

    broadcast({
        "type": "update_phase",
        "phase": "git_pull",
        "status": "running",
        "detail": f"git pull --ff-only origin {status.branch}",
    })
    cmd = ["git", "pull", "--ff-only", "origin", status.branch]
    try:
        _helpers._stream_subprocess(cmd, broadcast, phase="git_pull", timeout=60.0)
    except SubprocessFailed as exc:
        broadcast({
            "type": "update_phase",
            "phase": "git_pull",
            "status": "fail",
            "detail": str(exc),
        })
        raise
    except subprocess.TimeoutExpired:
        broadcast({
            "type": "update_phase",
            "phase": "git_pull",
            "status": "fail",
            "detail": "timeout after 60s",
        })
        raise
    broadcast({
        "type": "update_phase",
        "phase": "git_pull",
        "status": "ok",
        "detail": None,
    })

    # Capture the newly-pulled SHA for MAV_UPDATE_APPLIED.
    try:
        r = _helpers._run_git(["rev-parse", "HEAD"], timeout=5.0)
        if r.returncode == 0:
            captured = (r.stdout or "").strip()
            if captured:
                new_sha = captured
    except Exception:
        pass

    # Phase 2: countdown
    for remaining in (5, 4, 3, 2, 1):
        broadcast({
            "type": "update_phase",
            "phase": "countdown",
            "status": "running",
            "detail": str(remaining),
        })
        time.sleep(1)
    broadcast({
        "type": "update_phase",
        "phase": "countdown",
        "status": "ok",
        "detail": None,
    })

    # Phase 3: restart
    broadcast({
        "type": "update_phase",
        "phase": "restart",
        "status": "running",
        "detail": "restarting MAV_WEB.py...",
    })
    _helpers._reexec(extra_env={"MAV_UPDATE_APPLIED": new_sha})
    # unreachable
