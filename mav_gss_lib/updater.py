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

import hashlib
import importlib.util
import os
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
REQUIREMENTS_HASH_PATH = REPO_ROOT / ".mav_requirements_hash"
VENV_DIR = REPO_ROOT / ".venv"

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
    "httpx",      # httpx
    "yaml",       # PyYAML
    "zmq",        # pyzmq
    "crcmod",     # crcmod
    "PIL",        # Pillow
    "rich",       # rich
    "textual",    # textual
]


# =============================================================================
#  EXCEPTIONS
# =============================================================================

class PipBlockedError(Exception):
    """Raised when pip exits non-zero AND stderr matches a PEP 668 / permission /
    externally-managed marker. Signals the caller to attempt venv fallback."""


class SubprocessFailed(Exception):
    """Raised on non-zero exit that isn't a pip block. Carries the last 10
    stderr lines as the exception message."""


class VenvUnavailableError(Exception):
    """Raised by _ensure_venv when `python -m venv` fails due to missing
    ensurepip / python3-venv package. The updater cannot auto-recover."""


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
    requirements_changed: bool = False
    requirements_out_of_sync: bool = False
    fetch_failed: bool = False
    fetch_error: Optional[str] = None
    update_applied_sha: Optional[str] = None


@dataclass
class Phase:
    name: Literal["bootstrap_venv", "pip_install", "git_pull", "restart"]
    status: Literal["pending", "running", "ok", "fail"]
    detail: Optional[str] = None


# =============================================================================
#  REQUIREMENTS HASH TRACKING
# =============================================================================

def _compute_requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS_PATH.read_bytes()).hexdigest()


def _read_persisted_hash() -> Optional[str]:
    try:
        return REQUIREMENTS_HASH_PATH.read_text().strip() or None
    except FileNotFoundError:
        return None


def _write_persisted_hash() -> None:
    REQUIREMENTS_HASH_PATH.write_text(_compute_requirements_hash())


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
    origin, fetch DEFAULT_BRANCH, then checkout -B so the local branch tracks
    origin. Tracked files are overwritten (they match the zip anyway on first
    launch, or get updated to latest if the zip is stale). Untracked operator
    files (gss.yml, commands.yml, .mav_dev, logs) are preserved.

    Returns None on success or when .git already exists (idempotent). On any
    failure returns a short error string suitable for UpdateStatus.fetch_error.
    """
    if (REPO_ROOT / ".git").exists():
        return None

    steps: list[tuple[list[str], float]] = [
        (["init"], 5.0),
        (["remote", "add", "origin", REPO_URL], 5.0),
        (["fetch", "origin", DEFAULT_BRANCH], timeout_s),
        (["checkout", "-B", DEFAULT_BRANCH, f"origin/{DEFAULT_BRANCH}"], 10.0),
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

    # Missing deps — independent of git fetch. Scan first so the hash-seeding
    # decision below can trust find_spec() results.
    try:
        status.missing_pip_deps = _scan_missing_pip_deps()
    except Exception:
        status.missing_pip_deps = []

    # Requirements hash — computed regardless of git state so the "retry partial
    # failure" path still fires even when offline.
    #
    # First-observation seeding: on a fresh clone onto a machine that already
    # has all pip deps installed (the typical developer case), .mav_requirements_hash
    # is missing but every import resolves. Without seeding, the Updates check
    # would show the misleading "retrying previously failed dependency install"
    # label on the first-ever launch of a perfectly healthy environment.
    # Seed the hash silently whenever we observe a matching-env state, so only
    # genuine drift (missing imports or stale hash after a new requirements.txt)
    # triggers the retry label.
    try:
        current_hash = _compute_requirements_hash()
        persisted_hash = _read_persisted_hash()
        if persisted_hash is None:
            # First observation — trust the current env if imports resolve.
            if not status.missing_pip_deps:
                try:
                    _write_persisted_hash()
                    status.requirements_out_of_sync = False
                except Exception:
                    # Hash write failed (read-only fs?) — fall back to flagging
                    # as out-of-sync so we still show something actionable.
                    status.requirements_out_of_sync = True
            else:
                # Missing deps on first observation → legitimate install needed.
                status.requirements_out_of_sync = True
        else:
            status.requirements_out_of_sync = persisted_hash != current_hash
    except Exception:
        # If requirements.txt itself is unreadable, flag out of sync so the
        # operator sees something rather than silently passing.
        status.requirements_out_of_sync = True

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

    # Dirty tree check — always run, independent of fetch success
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
                status.requirements_changed = "requirements.txt" in status.changed_files
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
    if _detect_pip_blocked(tail):
        exc = PipBlockedError(tail)
        raise exc
    raise SubprocessFailed(tail or f"{cmd[0]} exited with code {proc.returncode}")


def _detect_pip_blocked(stderr_tail: str) -> bool:
    """Parse pip stderr for signals that the target interpreter rejects writes."""
    markers = (
        "externally-managed-environment",
        "EXTERNALLY-MANAGED",
        "error: externally-managed-environment",
        "Permission denied",
        "[Errno 13]",
        "Could not install packages due to an OSError",
    )
    return any(m in stderr_tail for m in markers)


# =============================================================================
#  VENV FALLBACK
# =============================================================================

def _ensure_venv() -> Path:
    """Create .venv if missing, return absolute path to its python interpreter.

    Raises VenvUnavailableError if `python -m venv` fails with an ensurepip
    message (common on Debian/Ubuntu without python3-venv installed).
    """
    if not VENV_DIR.exists():
        result = subprocess.run(
            [sys.executable, "-m", "venv", "--system-site-packages", str(VENV_DIR)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "") + (result.stdout or "")
            ensurepip_markers = (
                "ensurepip is not available",
                "The virtual environment was not created successfully",
                "No module named 'ensurepip'",
            )
            if any(m in stderr for m in ensurepip_markers):
                last = stderr.strip().splitlines()[-1] if stderr.strip() else "venv module incomplete"
                raise VenvUnavailableError(last)
            raise RuntimeError(f"venv creation failed: {stderr.strip()}")
    python = VENV_DIR / "bin" / "python"
    if not python.exists():
        raise RuntimeError(f"venv created but {python} is missing")
    return python


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
#  PIP INSTALL (two variants: broadcast-driven + terminal-driven)
# =============================================================================

def _run_pip_install(broadcast: Callable[[dict], None]) -> None:
    """Run pip install -r requirements.txt, streaming updates via broadcast.

    On success, writes the requirements hash file. On PipBlockedError, triggers
    venv fallback + re-exec (never returns). On other failure, re-raises.
    """
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_PATH)]
    broadcast({
        "type": "update_phase",
        "phase": "pip_install",
        "status": "running",
        "detail": "resolving dependencies...",
    })
    try:
        _stream_subprocess(cmd, broadcast, phase="pip_install", timeout=180.0)
    except PipBlockedError:
        broadcast({
            "type": "update_phase",
            "phase": "bootstrap_venv",
            "status": "running",
            "detail": "creating .venv (system Python is protected)",
        })
        try:
            venv_python = _ensure_venv()
        except VenvUnavailableError as exc:
            broadcast({
                "type": "update_phase",
                "phase": "bootstrap_venv",
                "status": "fail",
                "detail": (
                    "python3-venv not installed. On Debian/Ubuntu, run: "
                    "sudo apt install python3-venv, then reload."
                ),
            })
            raise
        except Exception as exc:
            broadcast({
                "type": "update_phase",
                "phase": "bootstrap_venv",
                "status": "fail",
                "detail": f"venv creation failed: {exc}",
            })
            raise
        broadcast({
            "type": "update_phase",
            "phase": "bootstrap_venv",
            "status": "ok",
            "detail": str(venv_python),
        })
        _reexec(python=venv_python)  # never returns
        return
    except SubprocessFailed as exc:
        broadcast({
            "type": "update_phase",
            "phase": "pip_install",
            "status": "fail",
            "detail": str(exc),
        })
        raise
    except subprocess.TimeoutExpired:
        broadcast({
            "type": "update_phase",
            "phase": "pip_install",
            "status": "fail",
            "detail": "timeout after 180s",
        })
        raise

    # Success: only now write the hash file.
    try:
        _write_persisted_hash()
    except Exception:
        pass

    broadcast({
        "type": "update_phase",
        "phase": "pip_install",
        "status": "ok",
        "detail": None,
    })


def _run_pip_install_terminal() -> None:
    """Bootstrap-mode variant: writes pip output directly to stdout/stderr.

    Used during pre-import bootstrap when no WebSocket exists yet.
    Same PipBlockedError semantics as _stream_subprocess.
    """
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_PATH)]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("pip install timed out after 300s")

    output = result.stdout or ""
    # Tee to terminal so the operator sees progress.
    if output:
        print(output, flush=True)

    if result.returncode == 0:
        try:
            _write_persisted_hash()
        except Exception:
            pass
        return

    tail = "\n".join(output.splitlines()[-10:])
    if _detect_pip_blocked(tail):
        raise PipBlockedError(tail)
    raise RuntimeError(f"pip install failed:\n{tail}")


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
    ran_any = False

    # Phase 1: git_pull
    if status.behind_count > 0:
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
        ran_any = True

        # Capture the newly-pulled SHA for MAV_UPDATE_APPLIED.
        try:
            r = _run_git(["rev-parse", "HEAD"], timeout=5.0)
            if r.returncode == 0:
                captured = (r.stdout or "").strip()
                if captured:
                    new_sha = captured
        except Exception:
            pass

    # Phase 2: pip_install
    need_pip = (
        status.requirements_changed
        or bool(status.missing_pip_deps)
        or status.requirements_out_of_sync
    )
    if need_pip:
        _run_pip_install(broadcast)
        ran_any = True

    if not ran_any:
        raise PreflightError("nothing to update")

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
    """Pre-import critical-dep check. Called at the top of MAV_WEB.py.

    May os.execv if a re-install is needed. Guards against re-exec loops via
    MAV_BOOTSTRAP_ATTEMPTED env var. Prints terminal status on first bootstrap.
    """
    # Step 1: hard prerequisites — refuse to proceed if missing.
    for module, instructions in _HARD_PREREQUISITES:
        if importlib.util.find_spec(module) is None:
            print(f"[MAV GSS] {instructions}", file=sys.stderr, flush=True)
            sys.exit(3)

    # Step 2: soft prerequisites — try to auto-install.
    missing = [m for m in _CRITICAL_MODULES if importlib.util.find_spec(m) is None]
    if not missing:
        os.environ.pop("MAV_BOOTSTRAP_ATTEMPTED", None)
        return

    if os.environ.get("MAV_BOOTSTRAP_ATTEMPTED"):
        print(
            f"[MAV GSS] bootstrap retry still missing: {missing}\n"
            f"          python={sys.executable}\n"
            f"          Install manually and relaunch.",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(2)

    os.environ["MAV_BOOTSTRAP_ATTEMPTED"] = "1"
    print(
        f"[MAV GSS] bootstrapping dependencies ({', '.join(missing)}), one moment...",
        flush=True,
    )
    try:
        _run_pip_install_terminal()
    except PipBlockedError:
        try:
            venv_python = _ensure_venv()
        except VenvUnavailableError as exc:
            print(
                f"[MAV GSS] Python venv module unavailable (needed for "
                f"dependency fallback).\n"
                f"          On Debian/Ubuntu: sudo apt install python3-venv\n"
                f"          Detail: {exc}",
                file=sys.stderr,
                flush=True,
            )
            sys.exit(3)
        # Clear the attempt marker — the venv python is a DIFFERENT interpreter
        # and gets its own fresh bootstrap attempt.
        os.environ.pop("MAV_BOOTSTRAP_ATTEMPTED", None)
        _reexec(python=venv_python)  # never returns
    _reexec(python=sys.executable)  # never returns; second invocation retries
