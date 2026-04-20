"""
mav_gss_lib.updater -- Self-Updater and Bootstrap

Pulls the latest commit from `origin` and installs any new Python
dependencies, fully driven from the existing preflight screen. Also
provides a pre-import bootstrap step that self-installs critical
runtime deps on a fresh clone, so `python3 MAV_WEB.py` is the only
command an operator ever runs.

This module MUST import only stdlib. It is called from MAV_WEB.py
before any non-stdlib import; any transitive non-stdlib import here
would defeat the bootstrap guard.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Optional


# =============================================================================
#  PATHS & CONSTANTS
# =============================================================================

REPO_ROOT = Path(__file__).resolve().parents[1]
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


# =============================================================================
#  GIT HELPERS
# =============================================================================

def _run_git(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    # GIT_TERMINAL_PROMPT=0 prevents the credential helper from blocking on an
    # interactive prompt when a private repo needs auth — we want a fast,
    # capturable failure, not a hung subprocess.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        ["git", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _ensure_git_repo(timeout_s: float) -> Optional[str]:
    """Auto-heal a zip-extracted tree into a real clone of REPO_URL.

    GitHub's "Download ZIP" produces a source snapshot with no .git directory,
    so the updater's git commands fail downstream with "not a git repository"
    and the preflight row renders as "could not reach origin". This helper
    detects that state and bootstraps a working clone in place: init, add
    origin, fetch DEFAULT_BRANCH, then force-checkout so the local branch
    tracks origin. Tracked files are overwritten (they match the zip anyway
    on first launch, or get updated to latest if the zip is stale). Untracked
    operator files (gss.yml, commands.yml, .mav_dev, logs) are gitignored
    and therefore absent from origin/main's tree, so they are preserved.

    If a prior run left a partial .git (e.g., init succeeded but checkout
    bailed on untracked files), rev-parse HEAD will fail — in that case we
    wipe .git and retry the full sequence rather than silently skipping.

    Returns None on success or when .git already resolves HEAD (idempotent).
    On any failure returns a short error string suitable for
    UpdateStatus.fetch_error.
    """
    git_dir = REPO_ROOT / ".git"
    if git_dir.exists():
        # Validate — a half-initialized .git from a prior failed heal has no
        # HEAD commit, and leaving it in place would dead-lock every future
        # launch at "could not reach origin".
        try:
            r = _run_git(["rev-parse", "HEAD"], timeout=5.0)
            if r.returncode == 0:
                return None
        except Exception:
            pass
        try:
            shutil.rmtree(git_dir)
        except Exception as exc:
            return f"could not remove partial .git: {exc}"

    # --force on checkout bypasses the "untracked working tree files would
    # be overwritten" guard. Necessary here because the zip's files are all
    # untracked until the first commit lands, and they collide with every
    # path in origin/main's tree.
    steps: list[tuple[list[str], float]] = [
        (["init"], 5.0),
        (["remote", "add", "origin", REPO_URL], 5.0),
        (["fetch", "origin", DEFAULT_BRANCH], timeout_s),
        (["checkout", "--force", "-B", DEFAULT_BRANCH, f"origin/{DEFAULT_BRANCH}"], 10.0),
        (["branch", f"--set-upstream-to=origin/{DEFAULT_BRANCH}", DEFAULT_BRANCH], 5.0),
    ]
    for args, tmo in steps:
        try:
            r = _run_git(args, timeout=tmo)
        except subprocess.TimeoutExpired:
            return f"git {args[0]} timeout during repo init"
        except Exception as exc:
            return f"git {args[0]} failed: {exc}"
        if r.returncode != 0:
            stderr = (r.stderr or "").strip()
            return f"git {args[0]} failed: {stderr or 'non-zero exit'}"
    return None


def _clean_dist_strays() -> None:
    """Delete untracked files under `mav_gss_lib/web/dist/assets/`.

    Vite writes content-hashed bundle filenames (e.g. `index-Djcvb32_.js`).
    When a remote commit changes the hash, `git pull --ff-only` on a machine
    that happens to have a differently-hashed leftover refuses to proceed,
    and even when it does, the stray file leaves `git status --porcelain`
    non-empty — which flips `working_tree_dirty` and disables the APPLY
    UPDATE button ("commit or stash local changes to enable").

    `dist/assets/` is purely build output — nothing operator-editable lives
    there — so pruning strays is always safe. `git clean -f` only touches
    untracked files; tracked and modified files are left alone. Scope is
    tight to `dist/assets/` so this can't reach anything else.

    Silent no-op on any failure: the caller still runs its dirty check
    afterwards, so a failed clean just surfaces as "dirty" as before.
    """
    try:
        _run_git(["clean", "-f", "mav_gss_lib/web/dist/assets/"], timeout=5.0)
    except Exception:
        pass


def _scan_missing_pip_deps() -> list[str]:
    """Return the subset of _ALL_PIP_MODULES currently not importable.

    This is the runtime drift detector — it scans the full requirements.txt set,
    not just the bootstrap-critical four, so non-critical package drift (e.g.,
    `crcmod` deleted from site-packages) is still surfaced in the updates check.
    Bootstrap uses _CRITICAL_MODULES directly for a narrower pre-FastAPI check.
    """
    missing: list[str] = []
    for mod in _ALL_PIP_MODULES:
        if importlib.util.find_spec(mod) is None:
            missing.append(mod)
    return missing


# =============================================================================
#  PUBLIC: check_for_updates
# =============================================================================

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
    # This is the developer escape hatch: `touch .mav_dev` at the repo root
    # permanently disables the updater for this checkout without editing code.
    if DEV_SENTINEL_PATH.exists():
        status.fetch_failed = True
        status.fetch_error = "dev mode (.mav_dev present)"
        return status

    # Zip-extract auto-heal — if .git is missing, bootstrap a clone from the
    # canonical upstream so a GitHub "Download ZIP" install becomes a real
    # git checkout on first launch. No-op when .git already exists.
    init_err = _ensure_git_repo(timeout_s)
    if init_err:
        status.fetch_failed = True
        status.fetch_error = init_err
        return status

    # Missing pip deps — surfaced to the operator as a warning in preflight.
    # Purely informational: the updater no longer installs Python packages.
    try:
        status.missing_pip_deps = _scan_missing_pip_deps()
    except Exception:
        status.missing_pip_deps = []

    # Update-applied marker (set by child process after an os.execv restart)
    status.update_applied_sha = os.environ.pop("MAV_UPDATE_APPLIED", None)

    # Branch
    try:
        r = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], timeout=5.0)
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
        r = _run_git(["rev-parse", "HEAD"], timeout=5.0)
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
    # Prune stale hashed bundles in dist/assets/ first so orphan files from
    # a prior build on this (or another) machine don't masquerade as real
    # local changes and block the updater.
    _clean_dist_strays()
    try:
        r = _run_git(["status", "--porcelain"], timeout=5.0)
        if r.returncode == 0:
            status.working_tree_dirty = bool((r.stdout or "").strip())
    except Exception:
        pass  # non-fatal; leave working_tree_dirty=False

    # Fetch
    try:
        r = _run_git(
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
        r = _run_git(["rev-list", "--count", f"HEAD..origin/{branch}"], timeout=5.0)
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
            r = _run_git(
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
            r = _run_git(
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


# =============================================================================
#  SUBPROCESS STREAMING
# =============================================================================

def _stream_subprocess(
    cmd: list[str],
    broadcast: Callable[[dict], None],
    phase: str,
    timeout: float,
) -> None:
    """Run subprocess, stream stdout line-by-line, coalesce broadcasts to <=1/s.

    NEVER broadcasts 'ok' or 'fail' — only 'running' updates. Caller is
    responsible for terminal state broadcasts.

    Wall-clock timeout protection: a daemon watchdog thread kills the process
    if it runs longer than `timeout` seconds. This is required because
    `for line in proc.stdout` blocks indefinitely when the subprocess produces
    no output — an in-loop time check cannot fire inside a blocking read.
    """
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    # Watchdog: guarantees the subprocess cannot outlive `timeout` seconds even
    # if it silently hangs without producing any output. The flag lets us
    # distinguish a watchdog kill from a normal non-zero exit.
    timed_out = threading.Event()

    def _watchdog() -> None:
        if proc.poll() is None:  # still running
            timed_out.set()
            try:
                proc.kill()
            except Exception:
                pass

    watchdog = threading.Timer(timeout, _watchdog)
    watchdog.daemon = True
    watchdog.start()

    stderr_tail: list[str] = []
    last_broadcast = 0.0
    latest_line = ""

    assert proc.stdout is not None
    try:
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                if not line:
                    continue
                # Tee to controlling tty so verbose pip output is visible.
                print(line, flush=True)
                stderr_tail.append(line)
                if len(stderr_tail) > 200:
                    stderr_tail = stderr_tail[-200:]
                latest_line = line
                now = time.monotonic()
                if now - last_broadcast >= 1.0:
                    last_broadcast = now
                    try:
                        broadcast({
                            "type": "update_phase",
                            "phase": phase,
                            "status": "running",
                            "detail": latest_line,
                        })
                    except Exception:
                        pass
        finally:
            try:
                proc.stdout.close()
            except Exception:
                pass

        # stdout loop exited — either the process finished or the watchdog
        # killed it. wait() settles the final exit code either way.
        proc.wait()
    finally:
        watchdog.cancel()

    if timed_out.is_set():
        raise subprocess.TimeoutExpired(cmd, timeout)

    if proc.returncode == 0:
        return

    tail = "\n".join(stderr_tail[-10:])
    raise SubprocessFailed(tail or f"{cmd[0]} exited with code {proc.returncode}")


# =============================================================================
#  RE-EXEC
# =============================================================================

def _reexec(
    python: "str | Path | None" = None,
    extra_env: Optional[dict[str, str]] = None,
) -> None:
    """Replace current process with a fresh invocation of MAV_WEB.py. Never returns."""
    if extra_env:
        for k, v in extra_env.items():
            os.environ[k] = v
    interpreter = str(python) if python is not None else sys.executable
    argv = [interpreter, *sys.argv]
    os.execv(interpreter, argv)


# =============================================================================
#  PUBLIC: apply_update
# =============================================================================

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
    # Re-prune dist/assets/ strays so a build that raced between the cached
    # status snapshot and now doesn't spuriously trip the gate.
    _clean_dist_strays()
    try:
        r = _run_git(["status", "--porcelain"], timeout=5.0)
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
    # Dependency installs are out of scope: operators run `pip install -r
    # requirements.txt` themselves from their conda env. Preflight surfaces
    # any missing modules as a warning on the next launch.
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
        _stream_subprocess(cmd, broadcast, phase="git_pull", timeout=60.0)
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
        r = _run_git(["rev-parse", "HEAD"], timeout=5.0)
        if r.returncode == 0:
            captured = (r.stdout or "").strip()
            if captured:
                new_sha = captured
    except Exception:
        pass

    # Phase 2: countdown — tick once per second so the UI can render a live
    # restart countdown before the process is replaced.
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
    _reexec(extra_env={"MAV_UPDATE_APPLIED": new_sha})
    # unreachable


# =============================================================================
#  PUBLIC: bootstrap_dependencies
# =============================================================================

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
    #
    # A prior run that bailed mid-heal leaves a .git with no HEAD commit;
    # detect that via rev-parse and retry, so the laptop doesn't dead-lock
    # at "could not reach origin" until the operator manually `rm -rf .git`s.
    if not DEV_SENTINEL_PATH.exists():
        needs_heal = not (REPO_ROOT / ".git").exists()
        if not needs_heal:
            try:
                r = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=str(REPO_ROOT),
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
            err = _ensure_git_repo(timeout_s=60.0)
            if err:
                print(f"[MAV GSS] git init failed: {err}", file=sys.stderr, flush=True)
                print(
                    "[MAV GSS] self-updater disabled; reinstall via `git clone` to enable updates.",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                print("[MAV GSS] git repository initialized.", flush=True)

    # Hard prerequisites (GNU Radio / pmt) — no recovery path, give the apt/conda
    # instructions and exit.
    for module, instructions in _HARD_PREREQUISITES:
        if importlib.util.find_spec(module) is None:
            print(f"[MAV GSS] {instructions}", file=sys.stderr, flush=True)
            sys.exit(3)

    # Soft prerequisites (pip-installable). Inside the radioconda base env
    # `pip install -r requirements.txt` is a single command with no flags,
    # so we defer to the operator instead of carrying auto-install logic.
    missing = [m for m in _CRITICAL_MODULES if importlib.util.find_spec(m) is None]
    if not missing:
        return

    print(
        f"[MAV GSS] missing Python packages: {', '.join(missing)}\n"
        f"          Install them with:\n"
        f"              pip install -r {REQUIREMENTS_PATH}\n"
        f"          (run inside your radioconda env, then relaunch)",
        file=sys.stderr,
        flush=True,
    )
    sys.exit(2)
