from mav_gss_lib.web_runtime.telemetry import TelemetryFragment
from mav_gss_lib.web_runtime.telemetry.state import DomainState


def _f(k, v, t):
    return TelemetryFragment(domain="eps", key=k, value=v, ts_ms=t)


def test_fragment_fields():
    f = TelemetryFragment(
        domain="eps", key="V_BAT", value=12.34,
        ts_ms=1_700_000_000_000, unit="V",
    )
    assert (f.domain, f.key, f.value, f.ts_ms, f.unit) == (
        "eps", "V_BAT", 12.34, 1_700_000_000_000, "V",
    )


def test_fragment_unit_defaults_to_empty():
    f = TelemetryFragment(domain="spacecraft", key="ops_stage", value=3, ts_ms=1)
    assert f.unit == ""


def test_fragment_to_dict_is_stable():
    f = TelemetryFragment("eps", "V_BAT", 7.622, 1_700_000_000_000, unit="V")
    assert f.to_dict() == {
        "domain": "eps", "key": "V_BAT", "value": 7.622,
        "ts_ms": 1_700_000_000_000, "unit": "V",
    }


def test_empty_on_first_open(tmp_path):
    s = DomainState(tmp_path / "eps.json")
    assert s.snapshot() == {}


def test_apply_returns_changed_entries(tmp_path):
    s = DomainState(tmp_path / "eps.json")
    changes = s.apply([_f("V_BAT", 12.0, 100), _f("I_BAT", -0.5, 100)])
    assert changes == {"V_BAT": {"v": 12.0, "t": 100}, "I_BAT": {"v": -0.5, "t": 100}}


def test_newer_wins(tmp_path):
    s = DomainState(tmp_path / "eps.json")
    s.apply([_f("V_BAT", 12.0, 100)])
    changes = s.apply([_f("V_BAT", 12.5, 200)])
    assert changes == {"V_BAT": {"v": 12.5, "t": 200}}
    assert s.snapshot()["V_BAT"] == {"v": 12.5, "t": 200}


def test_older_is_dropped(tmp_path):
    s = DomainState(tmp_path / "eps.json")
    s.apply([_f("V_BAT", 12.0, 100)])
    changes = s.apply([_f("V_BAT", 11.0, 90)])
    assert changes == {}
    assert s.snapshot()["V_BAT"] == {"v": 12.0, "t": 100}


def test_persist_and_reload(tmp_path):
    p = tmp_path / "eps.json"
    DomainState(p).apply([_f("V_BAT", 12.0, 100)])
    assert DomainState(p).snapshot() == {"V_BAT": {"v": 12.0, "t": 100}}


def test_clear_removes_state_and_file(tmp_path):
    p = tmp_path / "eps.json"
    s = DomainState(p)
    s.apply([_f("V_BAT", 12.0, 100)])
    assert p.exists()
    s.clear()
    assert s.snapshot() == {} and not p.exists()


def test_unreadable_file_starts_empty(tmp_path):
    p = tmp_path / "eps.json"
    p.write_text("{not json")
    assert DomainState(p).snapshot() == {}


def test_mission_load_entries_runs_on_restart(tmp_path):
    path = tmp_path / "x.json"
    s1 = DomainState(path)
    s1.apply([
        TelemetryFragment("d", "FRESH", 1.0, 200),
        TelemetryFragment("d", "STALE", 9.9, 100),
    ])

    def drop_stale(raw):
        return {k: v for k, v in raw.items() if v.get("t", 0) >= 150}

    s2 = DomainState(path, load_entries=drop_stale)
    snap = s2.snapshot()
    assert "FRESH" in snap
    assert "STALE" not in snap


def test_mission_load_entries_failure_starts_empty(tmp_path):
    path = tmp_path / "x.json"
    DomainState(path).apply([TelemetryFragment("d", "K", 1.0, 100)])

    def boom(raw):
        raise RuntimeError("bad schema")

    s = DomainState(path, load_entries=boom)
    assert s.snapshot() == {}


def test_mission_supplied_merge_policy(tmp_path):
    """Platform applies the exact callable the mission passes; no
    hardcoded merge assumption."""

    def sequence_monotonic(prev, frag):
        seq = frag.value.get("seq", 0) if isinstance(frag.value, dict) else 0
        if prev is not None and seq <= prev.get("seq", -1):
            return None
        return {"v": frag.value.get("v"), "t": frag.ts_ms, "seq": seq}

    s = DomainState(tmp_path / "x.json", merge=sequence_monotonic)
    s.apply([TelemetryFragment("d", "K", {"v": 1, "seq": 1}, 100)])
    s.apply([TelemetryFragment("d", "K", {"v": 2, "seq": 3}, 90)])
    s.apply([TelemetryFragment("d", "K", {"v": 3, "seq": 2}, 200)])
    entry = s.snapshot()["K"]
    assert entry["v"] == 2 and entry["seq"] == 3
