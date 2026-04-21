import json
from unittest import mock

from fastapi.testclient import TestClient

from mav_gss_lib.web_runtime.app import create_app


def _client():
    with mock.patch("mav_gss_lib.identity.getpass.getuser", return_value="irfan"), \
         mock.patch("mav_gss_lib.identity.socket.gethostname", return_value="gs-test"):
        app = create_app()
    return TestClient(app), app


def test_session_info_ws_includes_identity():
    client, app = _client()
    token = app.state.runtime.session_token
    with client.websocket_connect(f"/ws/session?token={token}") as ws:
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "session_info"
        assert msg["operator"] == "irfan"
        assert msg["host"] == "gs-test"
        assert msg["station"] == "gs-test"


def test_session_info_rest_includes_identity():
    client, app = _client()
    token = app.state.runtime.session_token
    resp = client.get("/api/session", headers={"X-GSS-Token": token})
    body = resp.json()
    assert body["operator"] == "irfan"
    assert body["station"] == "gs-test"
    assert body["host"] == "gs-test"
