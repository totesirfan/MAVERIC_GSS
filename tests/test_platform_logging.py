from mav_gss_lib.platform.loader import load_mission_spec
from mav_gss_lib.platform.rx.logging import (
    rx_log_record,
    rx_log_text,
    rx_telemetry_records,
)
from mav_gss_lib.platform.rx.pipeline import RxPipeline
from mav_gss_lib.platform.telemetry.router import TelemetryRouter


def _router_for(spec, tmp_path):
    router = TelemetryRouter(tmp_path)
    if spec.telemetry is not None:
        for name, domain in spec.telemetry.domains.items():
            router.register_domain(name, **domain.router_kwargs())
    return router


def test_build_rx_log_record_wraps_echo_packet_in_platform_envelope(tmp_path):
    spec = load_mission_spec(
        {"mission": {"id": "echo_v2", "config": {}}, "platform": {}},
        data_dir=tmp_path,
    )
    result = RxPipeline(spec, _router_for(spec, tmp_path)).process(
        {"transmitter": "fixture"},
        b"\xde\xad",
    )

    record = rx_log_record(
        spec, result.packet, "1.2.3",
        session_id="downlink_test",
        operator="op", station="gs",
    )

    # Unified envelope fields
    assert record["event_kind"] == "rx_packet"
    assert record["session_id"] == "downlink_test"
    assert isinstance(record["event_id"], str) and len(record["event_id"]) == 32
    assert isinstance(record["ts_ms"], int)
    assert record["v"] == "1.2.3"
    assert record["mission_id"] == "echo_v2"
    assert record["operator"] == "op"
    assert record["station"] == "gs"

    # Wire/inner byte split (renamed from raw_hex/payload_hex)
    assert record["wire_hex"] == "dead"
    assert record["inner_hex"] == "dead"
    assert record["wire_len"] == 2
    assert record["inner_len"] == 2

    # Mission block always present; `_rendering` and nested `telemetry` gone
    assert record["mission"] == {"hex": "dead"}
    assert "_rendering" not in record
    assert "telemetry" not in record


def test_build_rx_log_record_emits_balloon_telemetry_as_separate_events(tmp_path):
    spec = load_mission_spec(
        {"mission": {"id": "balloon_v2", "config": {}}, "platform": {}},
        data_dir=tmp_path,
    )
    result = RxPipeline(spec, _router_for(spec, tmp_path)).process(
        {},
        b'{"type":"beacon","alt_m":1200,"lat":34.0,"lon":-118.2,"temp_c":18.4}',
    )

    record = rx_log_record(
        spec, result.packet, "1.2.3",
        session_id="downlink_test",
        mission_id="balloon_v2",
    )
    tel = list(rx_telemetry_records(
        result.packet,
        session_id="downlink_test",
        rx_event_id=record["event_id"],
        version="1.2.3",
        mission_id="balloon_v2",
    ))

    assert record["mission"]["type"] == "beacon"
    assert "nodes" not in record
    assert "ptypes" not in record

    keys = {(f["domain"], f["key"]) for f in tel}
    assert ("environment", "altitude_m") in keys
    assert ("position", "gps") in keys

    # Every telemetry event carries the envelope + back-pointer
    for t in tel:
        assert t["event_kind"] == "telemetry"
        assert t["session_id"] == "downlink_test"
        assert t["rx_event_id"] == record["event_id"]
        assert t["mission_id"] == "balloon_v2"
        assert isinstance(t["ts_ms"], int)


def test_format_rx_text_lines_uses_mission_ui_safely(tmp_path):
    spec = load_mission_spec(
        {"mission": {"id": "echo_v2", "config": {}}, "platform": {}},
        data_dir=tmp_path,
    )
    result = RxPipeline(spec, _router_for(spec, tmp_path)).process({}, b"\xca\xfe")

    assert rx_log_text(spec, result.packet) == ["  RAW         cafe"]
