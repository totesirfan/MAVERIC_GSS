from unittest import mock

from fastapi.testclient import TestClient

from mav_gss_lib.config import load_gss_config
from mav_gss_lib.web_runtime.app import create_app


def _cfg_without_stations_catalog():
    """Return the merged config with an empty stations catalog — simulates a
    fresh install whose gss.yml has no stations block yet, so station falls
    back to the raw hostname."""
    cfg = load_gss_config()
    cfg["stations"] = {}
    return cfg


def test_api_identity_returns_runtime_values():
    with mock.patch("mav_gss_lib.identity.getpass.getuser", return_value="irfan"), \
         mock.patch("mav_gss_lib.identity.socket.gethostname", return_value="d23ll-barnhart"), \
         mock.patch("mav_gss_lib.web_runtime.state.load_gss_config",
                    return_value=_cfg_without_stations_catalog()):
        app = create_app()
    client = TestClient(app)
    resp = client.get("/api/identity")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"operator": "irfan", "host": "d23ll-barnhart", "station": "d23ll-barnhart"}
