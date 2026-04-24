"""check_for_updates — git fetch + diff + dep scan.

Stdlib-only. Safe to call from a thread.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import os
import subprocess

from . import _helpers
from . import status as _status
from .status import Commit, UpdateStatus


def check_for_updates(timeout_s: float = 10.0) -> UpdateStatus:
    """Lightweight: git fetch + compare + dep scan. Safe to call from a thread.

    Handles detached HEAD by returning fetch_failed=True with a clear reason.
    When HEAD already matches origin, skips the diff/log calls as optimization.

    Dev sentinel: if .mav_dev exists at the repo root, short-circuits with
    fetch_failed=True so the Updates check renders as a skip in dev mode.
    No git calls are made — developers stay on whatever commit they choose.
    """
    status = UpdateStatus()

    # Dev opt-out — short-circuit before touching git, pip, or the filesystem.
    if _status.DEV_SENTINEL_PATH.exists():
        status.fetch_failed = True
        status.fetch_error = "dev mode (.mav_dev present)"
        return status

    # Zip-extract auto-heal — if .git is missing, bootstrap a clone from the
    # canonical upstream so a GitHub "Download ZIP" install becomes a real
    # git checkout on first launch. No-op when .git already exists.
    init_err = _helpers._ensure_git_repo(timeout_s)
    if init_err:
        status.fetch_failed = True
        status.fetch_error = init_err
        return status

    # Missing pip deps — surfaced to the operator as a warning in preflight.
    try:
        status.missing_pip_deps = _helpers._scan_missing_pip_deps()
    except Exception:
        status.missing_pip_deps = []

    # Update-applied marker (set by child process after an os.execv restart)
    status.update_applied_sha = os.environ.pop("MAV_UPDATE_APPLIED", None)

    # Branch
    try:
        r = _helpers._run_git(["rev-parse", "--abbrev-ref", "HEAD"], timeout=5.0)
        if r.returncode != 0:
            status.fetch_failed = True
            status.fetch_error = (r.stderr or "git rev-parse failed").strip()
            return status
        branch = (r.stdout or "").strip()
    except Exception as exc:
        status.fetch_failed = True
        status.fetch_error = f"git rev-parse failed: {exc}"
        return status

    if branch == "HEAD" or not branch:
        status.fetch_failed = True
        status.fetch_error = "detached HEAD — not on a branch"
        return status
    status.branch = branch

    # Current SHA
    try:
        r = _helpers._run_git(["rev-parse", "HEAD"], timeout=5.0)
        if r.returncode != 0:
            status.fetch_failed = True
            status.fetch_error = (r.stderr or "").strip() or "git rev-parse HEAD failed"
            return status
        status.current_sha = (r.stdout or "").strip()
    except Exception as exc:
        status.fetch_failed = True
        status.fetch_error = f"git rev-parse HEAD failed: {exc}"
        return status

    # Dirty tree check — always run, independent of fetch success.
    _helpers._clean_dist_strays()
    try:
        r = _helpers._run_git(["status", "--porcelain"], timeout=5.0)
        if r.returncode == 0:
            status.working_tree_dirty = bool((r.stdout or "").strip())
    except Exception:
        pass  # non-fatal; leave working_tree_dirty=False

    # Fetch
    try:
        r = _helpers._run_git(
            ["fetch", "--quiet", "origin", branch],
            timeout=timeout_s,
        )
        if r.returncode != 0:
            status.fetch_failed = True
            status.fetch_error = (r.stderr or "git fetch failed").strip() or "git fetch failed"
            return status
    except subprocess.TimeoutExpired:
        status.fetch_failed = True
        status.fetch_error = "fetch timeout"
        return status
    except Exception as exc:
        status.fetch_failed = True
        status.fetch_error = f"git fetch failed: {exc}"
        return status

    # Behind count
    try:
        r = _helpers._run_git(["rev-list", "--count", f"HEAD..origin/{branch}"], timeout=5.0)
        if r.returncode != 0:
            status.fetch_failed = True
            status.fetch_error = (r.stderr or "rev-list failed").strip()
            return status
        status.behind_count = int((r.stdout or "0").strip() or "0")
    except Exception as exc:
        status.fetch_failed = True
        status.fetch_error = f"rev-list failed: {exc}"
        return status

    # Up-to-date optimization: skip log/diff if nothing to see
    if status.behind_count > 0:
        try:
            r = _helpers._run_git(
                ["log", f"HEAD..origin/{branch}", "--pretty=format:%h|%s"],
                timeout=5.0,
            )
            if r.returncode == 0:
                for line in (r.stdout or "").splitlines():
                    if "|" in line:
                        sha, _, subject = line.partition("|")
                        status.commits.append(Commit(sha=sha.strip(), subject=subject.strip()))
        except Exception:
            pass

        try:
            r = _helpers._run_git(
                ["diff", "--name-only", f"HEAD..origin/{branch}"],
                timeout=5.0,
            )
            if r.returncode == 0:
                status.changed_files = [
                    ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()
                ]
        except Exception:
            pass

    return status
