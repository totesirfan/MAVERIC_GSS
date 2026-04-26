"""Contract tests for /api/logs endpoints against the unified schema.

Uses FastAPI's TestClient over a live WebRuntime fixture so the filters,
pagination, and event_kind routing exercise real code paths.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from mav_gss_lib.server.app import create_app


def _build_fixture(log_dir: Path) -> str:
    (log_dir / "json").mkdir(parents=True, exist_ok=True)
    stem = "downlink_20260423_140000_GS-0_irfan"
    path = log_dir / "json" / f"{stem}.jsonl"
    rx = {
        "event_id": "e1", "event_kind": "rx_packet",
        "session_id": stem, "ts_ms": 1714053603500,
        "ts_iso": "2026-04-23T14:00:03.500+00:00",
        "seq": 1, "v": "5.7.0", "mission_id": "maveric",
        "operator": "irfan", "station": "GS-0",
        "frame_type": "ASM+GOLAY", "transport_meta": "",
        "wire_hex": "deadbeef", "wire_len": 4,
        "inner_hex": "dead", "inner_len": 2,
        "duplicate": False, "uplink_echo": False, "unknown": False,
        "warnings": [],
        "mission": {"cmd": {"cmd_id": "eps_hk"}},
    }
    tel = {
        "event_id": "t1", "event_kind": "parameter",
        "session_id": stem, "ts_ms": 1714053603500,
        "ts_iso": "2026-04-23T14:00:03.500+00:00",
        "seq": 1, "v": "5.7.0", "mission_id": "maveric",
        "operator": "irfan", "station": "GS-0",
        "rx_event_id": "e1",
        "name": "eps.vbatt", "value": 7.42,
        "unit": "V", "display_only": False,
    }
    rx2 = {**rx, "event_id": "e2", "seq": 2,
           "ts_ms": 1714053607500,
           "ts_iso": "2026-04-23T14:00:07.500+00:00",
           "mission": {"cmd": {"cmd_id": "com_ping"}}}
    path.write_text("\n".join(json.dumps(x) for x in [rx, tel, rx2]) + "\n")
    return stem


def test_list_sessions_enumerates_json_dir():
    with tempfile.TemporaryDirectory() as tmp:
        stem = _build_fixture(Path(tmp))
        app = create_app()
        # `log_dir` is a read-only property over platform_cfg.general.log_dir
        app.state.runtime.platform_cfg.setdefault("general", {})["log_dir"] = tmp
        with TestClient(app) as client:
            r = client.get("/api/logs")
        assert r.status_code == 200
        items = r.json()
        assert any(s["session_id"] == stem for s in items)


def test_entries_endpoint_defaults_exclude_parameters():
    with tempfile.TemporaryDirectory() as tmp:
        stem = _build_fixture(Path(tmp))
        app = create_app()
        # `log_dir` is a read-only property over platform_cfg.general.log_dir
        app.state.runtime.platform_cfg.setdefault("general", {})["log_dir"] = tmp
        with TestClient(app) as client:
            r = client.get(f"/api/logs/{stem}")
        assert r.status_code == 200
        data = r.json()
        kinds = {e["event_kind"] for e in data["entries"]}
        assert kinds == {"rx_packet"}  # parameter records filtered out by default
        assert len(data["entries"]) == 2


def test_entries_endpoint_opt_in_parameters():
    with tempfile.TemporaryDirectory() as tmp:
        stem = _build_fixture(Path(tmp))
        app = create_app()
        # `log_dir` is a read-only property over platform_cfg.general.log_dir
        app.state.runtime.platform_cfg.setdefault("general", {})["log_dir"] = tmp
        with TestClient(app) as client:
            r = client.get(f"/api/logs/{stem}?event_kind=rx_packet,parameter")
        assert r.status_code == 200
        kinds = [e["event_kind"] for e in r.json()["entries"]]
        assert kinds.count("parameter") == 1
        assert kinds.count("rx_packet") == 2


def test_cmd_filter_matches_mission_cmd_id():
    with tempfile.TemporaryDirectory() as tmp:
        stem = _build_fixture(Path(tmp))
        app = create_app()
        # `log_dir` is a read-only property over platform_cfg.general.log_dir
        app.state.runtime.platform_cfg.setdefault("general", {})["log_dir"] = tmp
        with TestClient(app) as client:
            r = client.get(f"/api/logs/{stem}?cmd=ping")
        assert r.status_code == 200
        entries = r.json()["entries"]
        assert len(entries) == 1
        assert entries[0]["seq"] == 2


def test_parameters_endpoint_filters_by_name():
    with tempfile.TemporaryDirectory() as tmp:
        stem = _build_fixture(Path(tmp))
        app = create_app()
        # `log_dir` is a read-only property over platform_cfg.general.log_dir
        app.state.runtime.platform_cfg.setdefault("general", {})["log_dir"] = tmp
        with TestClient(app) as client:
            r = client.get(f"/api/logs/{stem}/parameters?name=eps.vbatt")
        assert r.status_code == 200
        entries = r.json()["entries"]
        assert len(entries) == 1
        assert entries[0]["value"] == 7.42
        assert entries[0]["unit"] == "V"


def test_missing_session_returns_404():
    with tempfile.TemporaryDirectory() as tmp:
        _build_fixture(Path(tmp))
        app = create_app()
        app.state.runtime.platform_cfg.setdefault("general", {})["log_dir"] = tmp
        with TestClient(app) as client:
            r = client.get("/api/logs/does_not_exist")
        assert r.status_code == 404
