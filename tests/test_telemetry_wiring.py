"""Task 5 wiring test: WebRuntime builds a TelemetryRouter, adapter sees it,
and create_app mounts /api/telemetry/*. Mission-side manifest is still empty
at this task (Task 11 populates it), so the REST surface is checked with a
runtime-level register_domain call."""

from fastapi.testclient import TestClient

from mav_gss_lib.web_runtime.telemetry.router import TelemetryRouter


def test_runtime_has_telemetry_router():
    from mav_gss_lib.web_runtime.state import create_runtime

    runtime = create_runtime()
    assert isinstance(runtime.telemetry, TelemetryRouter)
    # Adapter sees the same router instance (Task 10 will read through this).
    assert runtime.adapter.telemetry is runtime.telemetry
    # Extractors alias is set; currently empty until Task 11 lands the manifest.
    assert runtime.adapter.extractors == ()


def test_create_app_mounts_telemetry_routes():
    from mav_gss_lib.web_runtime.app import create_app

    app = create_app()
    # Register a domain directly so the DELETE hits a real state bucket.
    runtime = app.state.runtime
    runtime.telemetry.register_domain("eps")
    with TestClient(app) as client:
        r = client.delete("/api/telemetry/eps/snapshot")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_create_app_catalog_404_on_unknown_domain():
    from mav_gss_lib.web_runtime.app import create_app

    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/telemetry/nope/catalog")
    assert r.status_code == 404
