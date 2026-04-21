from unittest import mock

from fastapi.testclient import TestClient

from mav_gss_lib.web_runtime.app import create_app


def test_api_identity_returns_runtime_values():
    with mock.patch("mav_gss_lib.identity.getpass.getuser", return_value="irfan"), \
         mock.patch("mav_gss_lib.identity.socket.gethostname", return_value="d23ll-barnhart"):
        app = create_app()
    client = TestClient(app)
    resp = client.get("/api/identity")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"operator": "irfan", "host": "d23ll-barnhart", "station": "d23ll-barnhart"}
