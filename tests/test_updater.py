"""Unit tests for mav_gss_lib.updater — simplified self-updater + bootstrap.

The updater is a thin git-pull + restart driver: no pip install, no venv
fallback, no hash tracking. These tests cover the remaining surface —
check_for_updates state machine, bootstrap_dependencies prereq gating, and
apply_update's phase sequence including the countdown.

Mocks subprocess.run / Popen, os.execv, and importlib.util.find_spec so
no real git / network / filesystem writes happen.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

# Ensure mav_gss_lib is importable when run from the tests directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib import updater  # noqa: E402
from mav_gss_lib.updater import (  # noqa: E402
    Commit,
    DirtyTreeError,
    PreflightError,
    SubprocessFailed,
    UpdateStatus,
    apply_update,
    bootstrap_dependencies,
    check_for_updates,
)


def _cp(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# =============================================================================
#  check_for_updates
# =============================================================================

class TestCheckForUpdates(unittest.TestCase):
    """Exercise the happy, dirty-tree, fetch-error, and detached-HEAD branches."""

    def setUp(self):
        # Make sure the dev-sentinel short-circuit never fires in these tests.
        # (The real repo may have .mav_dev present in the working tree.)
        self._dev_patch = mock.patch("mav_gss_lib.updater.status.DEV_SENTINEL_PATH")
        sentinel = self._dev_patch.start()
        sentinel.exists.return_value = False
        self.addCleanup(self._dev_patch.stop)
        # `_clean_dist_strays` runs its own `_run_git(["clean", ...])` call —
        # neutralize it here so each test's side_effect sequence represents
        # only the real flow, not the prune step.
        self._clean_patch = mock.patch("mav_gss_lib.updater._helpers._clean_dist_strays")
        self._clean_patch.start()
        self.addCleanup(self._clean_patch.stop)

    def _run_git_responses(self, *responses):
        """Turn a sequence of CompletedProcess responses into a _run_git side_effect."""
        it = iter(responses)
        def side_effect(args, timeout):
            return next(it)
        return side_effect

    def test_up_to_date_skips_log_and_diff(self):
        with mock.patch("mav_gss_lib.updater._helpers._ensure_git_repo", return_value=None), \
             mock.patch("mav_gss_lib.updater._helpers._scan_missing_pip_deps", return_value=[]), \
             mock.patch("mav_gss_lib.updater._helpers._run_git") as rg:
            rg.side_effect = self._run_git_responses(
                _cp(stdout="main\n"),                   # rev-parse --abbrev-ref HEAD
                _cp(stdout="abcdef1234\n"),             # rev-parse HEAD
                _cp(stdout=""),                         # status --porcelain (clean)
                _cp(),                                  # fetch
                _cp(stdout="0\n"),                      # rev-list --count
            )
            status = check_for_updates()
        self.assertEqual(status.behind_count, 0)
        self.assertEqual(status.branch, "main")
        self.assertFalse(status.working_tree_dirty)
        self.assertFalse(status.fetch_failed)

    def test_behind_parses_commits(self):
        with mock.patch("mav_gss_lib.updater._helpers._ensure_git_repo", return_value=None), \
             mock.patch("mav_gss_lib.updater._helpers._scan_missing_pip_deps", return_value=[]), \
             mock.patch("mav_gss_lib.updater._helpers._run_git") as rg:
            rg.side_effect = self._run_git_responses(
                _cp(stdout="main\n"),
                _cp(stdout="abcdef1\n"),
                _cp(stdout=""),
                _cp(),
                _cp(stdout="2\n"),
                _cp(stdout="aaaaaaa|subject one\nbbbbbbb|subject two\n"),
                _cp(stdout="README.md\nmav_gss_lib/updater.py\n"),
            )
            status = check_for_updates()
        self.assertEqual(status.behind_count, 2)
        self.assertEqual([c.sha for c in status.commits], ["aaaaaaa", "bbbbbbb"])
        self.assertEqual(status.changed_files, ["README.md", "mav_gss_lib/updater.py"])

    def test_dirty_tree_is_flagged(self):
        with mock.patch("mav_gss_lib.updater._helpers._ensure_git_repo", return_value=None), \
             mock.patch("mav_gss_lib.updater._helpers._scan_missing_pip_deps", return_value=[]), \
             mock.patch("mav_gss_lib.updater._helpers._run_git") as rg:
            rg.side_effect = self._run_git_responses(
                _cp(stdout="main\n"),
                _cp(stdout="abc\n"),
                _cp(stdout=" M file.py\n"),   # dirty
                _cp(),
                _cp(stdout="0\n"),
            )
            status = check_for_updates()
        self.assertTrue(status.working_tree_dirty)

    def test_fetch_network_error_marks_failed(self):
        with mock.patch("mav_gss_lib.updater._helpers._ensure_git_repo", return_value=None), \
             mock.patch("mav_gss_lib.updater._helpers._scan_missing_pip_deps", return_value=[]), \
             mock.patch("mav_gss_lib.updater._helpers._run_git") as rg:
            rg.side_effect = self._run_git_responses(
                _cp(stdout="main\n"),
                _cp(stdout="abc\n"),
                _cp(stdout=""),
                _cp(returncode=1, stderr="host unreachable"),
            )
            status = check_for_updates()
        self.assertTrue(status.fetch_failed)
        self.assertIn("host unreachable", status.fetch_error or "")

    def test_detached_head_marks_failed(self):
        with mock.patch("mav_gss_lib.updater._helpers._ensure_git_repo", return_value=None), \
             mock.patch("mav_gss_lib.updater._helpers._scan_missing_pip_deps", return_value=[]), \
             mock.patch("mav_gss_lib.updater._helpers._run_git") as rg:
            rg.side_effect = self._run_git_responses(_cp(stdout="HEAD\n"))
            status = check_for_updates()
        self.assertTrue(status.fetch_failed)
        self.assertIn("detached HEAD", status.fetch_error or "")

    def test_dev_sentinel_short_circuits(self):
        # Flip the sentinel back to present for this one test.
        self._dev_patch.stop()
        with mock.patch("mav_gss_lib.updater.status.DEV_SENTINEL_PATH") as sentinel, \
             mock.patch("mav_gss_lib.updater._helpers._run_git") as rg:
            sentinel.exists.return_value = True
            status = check_for_updates()
        rg.assert_not_called()
        self.assertTrue(status.fetch_failed)
        self.assertIn(".mav_dev", status.fetch_error or "")
        # Restart the default patch so addCleanup doesn't double-stop.
        self._dev_patch = mock.patch("mav_gss_lib.updater.status.DEV_SENTINEL_PATH")
        self._dev_patch.start()


# =============================================================================
#  bootstrap_dependencies
# =============================================================================

class TestBootstrapDependencies(unittest.TestCase):
    """Simplified bootstrap: checks prereqs, prints install instructions if missing."""

    def setUp(self):
        # Skip the zip auto-heal branch in every test.
        self.dev_patch = mock.patch("mav_gss_lib.updater.status.DEV_SENTINEL_PATH")
        self.dev_sentinel = self.dev_patch.start()
        self.dev_sentinel.exists.return_value = True
        self.addCleanup(self.dev_patch.stop)

    def test_hard_prereq_missing_exits_3(self):
        with mock.patch("mav_gss_lib.updater.bootstrap.importlib.util.find_spec", return_value=None):
            with self.assertRaises(SystemExit) as ctx:
                bootstrap_dependencies()
        self.assertEqual(ctx.exception.code, 3)

    def test_all_deps_present_is_noop(self):
        fake_spec = object()
        with mock.patch("mav_gss_lib.updater.bootstrap.importlib.util.find_spec", return_value=fake_spec):
            # Should return without raising
            bootstrap_dependencies()

    def test_soft_prereq_missing_exits_2_with_instructions(self):
        # Hard prereqs present, critical soft module missing.
        def find_spec(name):
            if name in updater.status._CRITICAL_MODULES:
                return None
            return object()
        with mock.patch("mav_gss_lib.updater.bootstrap.importlib.util.find_spec", side_effect=find_spec), \
             mock.patch("sys.stderr"):
            with self.assertRaises(SystemExit) as ctx:
                bootstrap_dependencies()
        self.assertEqual(ctx.exception.code, 2)


# =============================================================================
#  _reexec
# =============================================================================

class TestReexec(unittest.TestCase):
    def test_applies_env_before_exec(self):
        with mock.patch("os.execv") as execv, \
             mock.patch.dict("os.environ", {}, clear=False):
            updater._helpers._reexec(extra_env={"MAV_UPDATE_APPLIED": "deadbee"})
            import os
            self.assertEqual(os.environ.get("MAV_UPDATE_APPLIED"), "deadbee")
            execv.assert_called_once()


# =============================================================================
#  apply_update
# =============================================================================

class TestApplyUpdate(unittest.TestCase):
    def setUp(self):
        self.events: list[dict] = []
        def broadcast(event: dict) -> None:
            self.events.append(event)
        self._broadcast = broadcast
        # `_clean_dist_strays` runs a `_run_git(["clean", ...])` call before
        # the dirty-tree gate — stub it out so each test's side_effect
        # sequence covers only the real flow.
        self._clean_patch = mock.patch("mav_gss_lib.updater._helpers._clean_dist_strays")
        self._clean_patch.start()
        self.addCleanup(self._clean_patch.stop)

    def _status(self, behind: int = 2, dirty: bool = False) -> UpdateStatus:
        return UpdateStatus(
            current_sha="oldsha1",
            branch="main",
            behind_count=behind,
            commits=[Commit(sha="a", subject="s1"), Commit(sha="b", subject="s2")],
            working_tree_dirty=dirty,
        )

    def test_happy_path_runs_git_pull_countdown_and_reexecs(self):
        status = self._status()
        with mock.patch("mav_gss_lib.updater._helpers._run_git") as rg, \
             mock.patch("mav_gss_lib.updater._helpers._stream_subprocess") as ss, \
             mock.patch("mav_gss_lib.updater._helpers._reexec") as rx, \
             mock.patch("mav_gss_lib.updater.apply.time.sleep"):
            rg.side_effect = [
                _cp(stdout=""),            # status --porcelain (clean)
                _cp(stdout="newsha2\n"),   # rev-parse HEAD after pull
            ]
            apply_update(self._broadcast, status)

        ss.assert_called_once()
        rx.assert_called_once()
        # reexec gets the new SHA as MAV_UPDATE_APPLIED.
        _, kwargs = rx.call_args
        self.assertEqual(kwargs.get("extra_env", {}).get("MAV_UPDATE_APPLIED"), "newsha2")

        # Countdown ticks 5..1 were broadcast.
        countdown_details = [
            e.get("detail") for e in self.events
            if e.get("phase") == "countdown" and e.get("status") == "running"
        ]
        self.assertEqual(countdown_details, ["5", "4", "3", "2", "1"])

    def test_dirty_tree_gate_blocks_apply(self):
        status = self._status()
        with mock.patch("mav_gss_lib.updater._helpers._run_git") as rg, \
             mock.patch("mav_gss_lib.updater._helpers._stream_subprocess") as ss, \
             mock.patch("mav_gss_lib.updater._helpers._reexec") as rx:
            rg.return_value = _cp(stdout=" M file.py\n")
            with self.assertRaises(DirtyTreeError):
                apply_update(self._broadcast, status)
        ss.assert_not_called()
        rx.assert_not_called()

    def test_nothing_to_update_raises_preflight_error(self):
        status = self._status(behind=0)
        with mock.patch("mav_gss_lib.updater._helpers._run_git", return_value=_cp(stdout="")), \
             mock.patch("mav_gss_lib.updater._helpers._stream_subprocess") as ss, \
             mock.patch("mav_gss_lib.updater._helpers._reexec") as rx:
            with self.assertRaises(PreflightError):
                apply_update(self._broadcast, status)
        ss.assert_not_called()
        rx.assert_not_called()

    def test_git_pull_failure_is_broadcast_and_raised(self):
        status = self._status()
        with mock.patch("mav_gss_lib.updater._helpers._run_git", return_value=_cp(stdout="")), \
             mock.patch("mav_gss_lib.updater._helpers._stream_subprocess",
                               side_effect=SubprocessFailed("fast-forward refused")), \
             mock.patch("mav_gss_lib.updater._helpers._reexec") as rx:
            with self.assertRaises(SubprocessFailed):
                apply_update(self._broadcast, status)
        rx.assert_not_called()
        fail_events = [e for e in self.events if e.get("status") == "fail"]
        self.assertTrue(any(e.get("phase") == "git_pull" for e in fail_events))


class TestCleanDistStrays(unittest.TestCase):
    """_clean_dist_strays is scoped tight to build output — anything it runs
    must never reach outside `mav_gss_lib/web/dist/assets/`."""

    def test_invokes_git_clean_scoped_to_dist_assets(self):
        with mock.patch("mav_gss_lib.updater._helpers._run_git") as rg:
            updater._helpers._clean_dist_strays()
        rg.assert_called_once()
        args, _ = rg.call_args
        self.assertEqual(args[0], ["clean", "-f", "mav_gss_lib/web/dist/assets/"])

    def test_swallows_exceptions_silently(self):
        with mock.patch("mav_gss_lib.updater._helpers._run_git", side_effect=RuntimeError("boom")):
            updater._helpers._clean_dist_strays()  # must not raise


if __name__ == "__main__":
    unittest.main()
