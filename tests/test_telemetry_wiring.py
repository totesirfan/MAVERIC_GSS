"""Telemetry wiring tests for the platform-owned router."""

from fastapi.testclient import TestClient

from mav_gss_lib.platform.telemetry.router import TelemetryRouter


def test_runtime_has_telemetry_router():
    from mav_gss_lib.server.state import create_runtime

    runtime = create_runtime()
    assert isinstance(runtime.telemetry, TelemetryRouter)
    assert runtime.telemetry is runtime.platform.telemetry
    assert len(runtime.mission.telemetry.extractors) == 1
    for name in ("eps", "gnc", "spacecraft"):
        assert runtime.telemetry.has_domain(name), f"{name} domain missing"


def test_create_app_mounts_telemetry_routes():
    from mav_gss_lib.server.app import create_app

    app = create_app()
    # Register a domain directly so the DELETE hits a real state bucket.
    runtime = app.state.runtime
    runtime.telemetry.register_domain("eps")
    with TestClient(app) as client:
        r = client.delete("/api/telemetry/eps/snapshot")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_create_app_catalog_404_on_unknown_domain():
    from mav_gss_lib.server.app import create_app

    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/telemetry/nope/catalog")
    assert r.status_code == 404
