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
    cfg = {"general": {"station_id": "GS-1"}}
    assert capture_station(cfg, host="d23ll-barnhart") == "GS-1"


def test_capture_station_falls_back_to_host_when_override_missing():
    cfg = {"general": {}}
    assert capture_station(cfg, host="d23ll-barnhart") == "d23ll-barnhart"


def test_capture_station_falls_back_to_host_when_override_blank():
    cfg = {"general": {"station_id": ""}}
    assert capture_station(cfg, host="d23ll-barnhart") == "d23ll-barnhart"


def test_capture_station_handles_missing_general_section():
    cfg = {}
    assert capture_station(cfg, host="host1") == "host1"


from mav_gss_lib.config import _DEFAULTS


def test_station_id_is_in_defaults():
    assert "station_id" in _DEFAULTS["general"]
    assert _DEFAULTS["general"]["station_id"] is None


def test_station_id_strip_preserves_disk_value(tmp_path, monkeypatch):
    """A UI config save must not wipe station_id from the persisted YAML."""
    import yaml
    from mav_gss_lib import config as cfg_module

    gss_path = tmp_path / "gss.yml"
    gss_path.write_text("general:\n  station_id: GS-7\ntx:\n  delay_ms: 500\n")
    monkeypatch.setattr(cfg_module, "_DEFAULT_GSS_PATH", gss_path)
    monkeypatch.setattr(cfg_module, "get_operator_config_path", lambda: gss_path)

    # Simulate UI save: operator changes delay_ms, sends "station_id": "BAD" too.
    from mav_gss_lib.web_runtime.api.config import _strip_persisted_junk
    raw = cfg_module.load_operator_config_raw()
    update = {"tx": {"delay_ms": 1000}, "general": {"station_id": "BAD"}}
    # Mirror the handler's inline strip:
    if isinstance(update.get("general"), dict):
        update["general"].pop("station_id", None)
    cfg_module.deep_merge_inplace(raw, update)
    raw = _strip_persisted_junk(raw)
    cfg_module.save_operator_config_raw(raw)

    reloaded = yaml.safe_load(gss_path.read_text())
    assert reloaded["general"]["station_id"] == "GS-7"
    assert reloaded["tx"]["delay_ms"] == 1000
