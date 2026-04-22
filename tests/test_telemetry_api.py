from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mav_gss_lib.web_runtime.telemetry import TelemetryFragment
from mav_gss_lib.web_runtime.telemetry.api import get_telemetry_router
from mav_gss_lib.web_runtime.telemetry.router import TelemetryRouter


class _RecordingRx:
    def __init__(self):
        self.sent: list[dict] = []

    async def broadcast(self, msg):
        self.sent.append(msg)


def _mk_app(tmp_path, *, catalog_body=None, with_catalog_domain="gnc"):
    router = TelemetryRouter(tmp_path)
    router.register_domain("eps")
    if catalog_body is not None:
        router.register_domain(with_catalog_domain, catalog=lambda: catalog_body)
    rx = _RecordingRx()
    runtime = SimpleNamespace(telemetry=router, rx=rx)
    app = FastAPI()
    app.state.runtime = runtime
    app.include_router(get_telemetry_router())
    return app, runtime


def test_delete_snapshot_known_domain_returns_ok(tmp_path):
    app, runtime = _mk_app(tmp_path)
    runtime.telemetry.ingest([TelemetryFragment("eps", "V_BAT", 12.0, 100)])
    with TestClient(app) as client:
        r = client.delete("/api/telemetry/eps/snapshot")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    # One cleared broadcast went out.
    assert runtime.rx.sent == [
        {"type": "telemetry", "domain": "eps", "cleared": True}
    ]
    # State is cleared.
    assert runtime.telemetry.replay() == []


def test_delete_snapshot_unknown_domain_returns_404(tmp_path):
    app, runtime = _mk_app(tmp_path)
    with TestClient(app) as client:
        r = client.delete("/api/telemetry/unknown/snapshot")
    assert r.status_code == 404
    assert runtime.rx.sent == []


def test_get_catalog_known_domain_returns_body(tmp_path):
    body = [{"name": "STAT", "unit": ""}]
    app, _ = _mk_app(tmp_path, catalog_body=body)
    with TestClient(app) as client:
        r = client.get("/api/telemetry/gnc/catalog")
    assert r.status_code == 200
    assert r.json() == body


def test_get_catalog_domain_without_catalog_returns_404(tmp_path):
    app, _ = _mk_app(tmp_path)
    with TestClient(app) as client:
        r = client.get("/api/telemetry/eps/catalog")
    assert r.status_code == 404


def test_get_catalog_unknown_domain_returns_404(tmp_path):
    app, _ = _mk_app(tmp_path)
    with TestClient(app) as client:
        r = client.get("/api/telemetry/nope/catalog")
    assert r.status_code == 404
