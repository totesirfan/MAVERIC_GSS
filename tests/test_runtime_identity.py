from unittest import mock

from mav_gss_lib.config import load_split_config
from mav_gss_lib.server.state import create_runtime


def _split_without_stations_catalog():
    """Return the split config with the `stations` catalog emptied — simulates
    an install where the mocked hostname isn't catalogued, so station falls
    back to host. Robust against any real `gss.yml` catalog entries."""
    platform_cfg, mission_id, mission_cfg = load_split_config()
    platform_cfg["stations"] = {}
    return platform_cfg, mission_id, mission_cfg


def test_runtime_captures_identity_on_construction(tmp_path, monkeypatch):
    monkeypatch.delenv("SUDO_USER", raising=False)
    with mock.patch("mav_gss_lib.identity.getpass.getuser", return_value="irfan"), \
         mock.patch("mav_gss_lib.identity.socket.gethostname", return_value="host-under-test"), \
         mock.patch("mav_gss_lib.server.state.load_split_config",
                    return_value=_split_without_stations_catalog()):
        runtime = create_runtime()
        assert runtime.operator == "irfan"
        assert runtime.host == "host-under-test"
        # Mocked hostname isn't catalogued → station falls back to host
        assert runtime.station == "host-under-test"
        assert runtime.session.operator == "irfan"
        assert runtime.session.host == "host-under-test"
        assert runtime.session.station == "host-under-test"
