import os
from unittest import mock

import pytest

from mav_gss_lib.identity import capture_host, capture_operator, capture_station


def test_capture_operator_returns_getpass_user(monkeypatch):
    monkeypatch.delenv("SUDO_USER", raising=False)
    with mock.patch("mav_gss_lib.identity.getpass.getuser", return_value="irfan"):
        assert capture_operator() == "irfan"


def test_capture_operator_prefers_sudo_user(monkeypatch):
    monkeypatch.setenv("SUDO_USER", "alice")
    with mock.patch("mav_gss_lib.identity.getpass.getuser", return_value="root"):
        assert capture_operator() == "alice"


def test_capture_host_returns_socket_hostname():
    with mock.patch("mav_gss_lib.identity.socket.gethostname", return_value="d23ll-barnhart"):
        assert capture_host() == "d23ll-barnhart"


def test_capture_station_returns_config_override_when_set():
    cfg = {"stations": {"h": "GS-9"}}
    assert capture_station(cfg, "h") == "GS-9"


def test_capture_station_falls_back_to_host_when_override_missing():
    cfg = {"stations": {}}
    assert capture_station(cfg, "d23ll-barnhart") == "d23ll-barnhart"


def test_capture_station_falls_back_to_host_when_override_blank():
    cfg = {"stations": {"d23ll-barnhart": ""}}
    assert capture_station(cfg, "d23ll-barnhart") == "d23ll-barnhart"


def test_capture_station_handles_missing_stations_section():
    cfg = {}
    assert capture_station(cfg, "host1") == "host1"


from mav_gss_lib.config import _DEFAULTS


def test_stations_is_in_defaults():
    assert "stations" in _DEFAULTS
    assert _DEFAULTS["stations"] == {}
    assert "station_id" not in _DEFAULTS["general"]


def test_stations_strip_preserves_disk_value(tmp_path, monkeypatch):
    """A UI config save must not wipe the stations catalog from the persisted YAML."""
    import yaml
    from mav_gss_lib import config as cfg_module

    gss_path = tmp_path / "gss.yml"
    gss_path.write_text("stations:\n  host1: GS-7\ntx:\n  delay_ms: 500\n")
    monkeypatch.setattr(cfg_module, "_DEFAULT_GSS_PATH", gss_path)
    monkeypatch.setattr(cfg_module, "get_operator_config_path", lambda: gss_path)

    # Simulate UI save: operator changes delay_ms and tries to overwrite stations.
    from mav_gss_lib.web_runtime.api.config import _strip_persisted_junk
    raw = cfg_module.load_operator_config_raw()
    update = {"tx": {"delay_ms": 1000}, "stations": {"host1": "MALICIOUS"}}
    # Mirror the handler's inline strip:
    update.pop("stations", None)
    cfg_module.deep_merge_inplace(raw, update)
    raw = _strip_persisted_junk(raw)
    cfg_module.save_operator_config_raw(raw)

    reloaded = yaml.safe_load(gss_path.read_text())
    assert reloaded["stations"]["host1"] == "GS-7"
    assert reloaded["tx"]["delay_ms"] == 1000


def test_preflight_yields_identity_row_from_capture():
    """CLI path: no identity injected — falls back to capture."""
    from unittest import mock
    from mav_gss_lib.preflight import run_preflight
    cfg = {"general": {"mission": "maveric"}, "stations": {"dev-host": "GS-0"}}
    with mock.patch("mav_gss_lib.identity.getpass.getuser", return_value="irfan"), \
         mock.patch("mav_gss_lib.identity.socket.gethostname", return_value="dev-host"):
        results = list(run_preflight(cfg=cfg))
    identity_rows = [r for r in results if r.group == "identity"]
    assert len(identity_rows) == 1
    row = identity_rows[0]
    assert row.status == "ok"
    assert "irfan" in row.label or "irfan" in row.detail
    assert "GS-0" in row.label or "GS-0" in row.detail


def test_preflight_uses_injected_identity_over_capture():
    """Web path: runtime injects identity — capture must not run."""
    from mav_gss_lib.preflight import run_preflight
    cfg = {"general": {"mission": "maveric"}, "stations": {"gs1": "IGNORED"}}
    results = list(run_preflight(
        cfg=cfg,
        operator="alice", host="gs1", station="GS-1",
    ))
    identity_rows = [r for r in results if r.group == "identity"]
    assert len(identity_rows) == 1
    row = identity_rows[0]
    assert "alice" in row.detail and "GS-1" in row.detail
    # cfg station_id="IGNORED" must not leak in — injected identity wins
    assert "IGNORED" not in row.label and "IGNORED" not in row.detail
