"""reset_legacy_snapshots helper: remove pre-v2 flat snapshot files once.

Idempotent on a clean host (second call returns []). Missing log_dir,
stray non-json files, and read-only files all exercised.
"""
from __future__ import annotations

from pathlib import Path

from mav_gss_lib.server.telemetry import reset_legacy_snapshots


def test_removes_both_legacy_files(tmp_path):
    eps = tmp_path / ".eps_snapshot.json"
    gnc = tmp_path / ".gnc_snapshot.json"
    eps.write_text("{}")
    gnc.write_text("{}")

    removed = reset_legacy_snapshots(tmp_path)

    assert set(removed) == {str(eps), str(gnc)}
    assert not eps.exists()
    assert not gnc.exists()


def test_removes_only_eps_when_gnc_absent(tmp_path):
    eps = tmp_path / ".eps_snapshot.json"
    eps.write_text("{}")

    removed = reset_legacy_snapshots(tmp_path)

    assert removed == [str(eps)]
    assert not eps.exists()


def test_clean_host_returns_empty_list(tmp_path):
    assert reset_legacy_snapshots(tmp_path) == []


def test_idempotent_second_call_is_clean(tmp_path):
    (tmp_path / ".eps_snapshot.json").write_text("{}")
    first = reset_legacy_snapshots(tmp_path)
    second = reset_legacy_snapshots(tmp_path)
    assert first and second == []


def test_accepts_string_log_dir(tmp_path):
    (tmp_path / ".gnc_snapshot.json").write_text("{}")
    removed = reset_legacy_snapshots(str(tmp_path))
    assert len(removed) == 1
