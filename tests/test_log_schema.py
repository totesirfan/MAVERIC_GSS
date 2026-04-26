"""Envelope-stability guardrail for the unified JSONL logging schema.

Every JSONL line (rx_packet, parameter, tx_command) must carry the full
envelope (`event_id`, `event_kind`, `session_id`, `ts_ms`, `ts_iso`, `seq`,
`v`, `mission_id`, `operator`, `station`). Missing keys break SQL ingest
on the other team's side, so the test fails fast instead of letting the
drift go unnoticed.
"""

from __future__ import annotations

import json
import tempfile

from mav_gss_lib.logging import TXLog
from mav_gss_lib.platform import MissionSpec
from mav_gss_lib.platform.contract.packets import PacketEnvelope, PacketFlags
from mav_gss_lib.platform.contract.parameters import ParamUpdate
from mav_gss_lib.platform.contract.rendering import PacketRendering
from mav_gss_lib.platform.rx.logging import (
    parameter_log_records,
    rx_log_record,
)
from mav_gss_lib.platform.tx.logging import tx_log_record


_ENVELOPE_KEYS = {
    "event_id", "event_kind", "session_id", "ts_ms", "ts_iso",
    "seq", "v", "mission_id", "operator", "station",
}

_ALLOWED_KINDS = {"rx_packet", "tx_command", "parameter"}


class _Ui:
    def packet_columns(self): return []
    def tx_columns(self): return []
    def render_packet(self, packet): return PacketRendering(columns=[], row={})
    def render_log_data(self, packet): return {"sig": "probe"}
    def format_text_log(self, packet): return []


def _assert_envelope(rec: dict) -> None:
    missing = _ENVELOPE_KEYS - rec.keys()
    assert not missing, f"record missing envelope keys {missing}: {rec}"
    assert rec["event_kind"] in _ALLOWED_KINDS, (
        f"unknown event_kind {rec['event_kind']}"
    )
    assert isinstance(rec["event_id"], str) and rec["event_id"], rec
    assert isinstance(rec["ts_ms"], int), rec
    assert isinstance(rec["ts_iso"], str) and rec["ts_iso"], rec
    assert isinstance(rec["seq"], int), rec


def _make_packet() -> PacketEnvelope:
    return PacketEnvelope(
        seq=42,
        received_at_ms=1714053603500,
        received_at_text="2026-04-23 14:00:03 UTC",
        received_at_short="14:00:03",
        frame_type="ASM+GOLAY",
        raw=b"\x01\x02\x03\x04",
        payload=b"\x02\x03",
        transport_meta={"transmitter": "probe"},
        warnings=[],
        mission_payload={},
        flags=PacketFlags(),
        parameters=(
            ParamUpdate(name="eps.vbatt", value=7.42,
                        ts_ms=1714053603500, unit="V"),
            ParamUpdate(name="eps.temp_batt", value=18.3,
                        ts_ms=1714053603500, unit="C"),
        ),
    )


def _make_spec() -> MissionSpec:
    return MissionSpec(id="maveric", name="MAVERIC", packets=None, ui=_Ui(), config=None)


def test_rx_packet_envelope_shape():
    spec = _make_spec()
    pkt = _make_packet()
    record = rx_log_record(
        spec, pkt, "5.7.0",
        session_id="downlink_20260423_140000",
        mission_id="maveric", operator="irfan", station="GS-0",
    )
    _assert_envelope(record)
    assert record["event_kind"] == "rx_packet"
    assert record["wire_hex"] == "01020304"
    assert record["wire_len"] == 4
    assert record["inner_hex"] == "0203"
    assert record["inner_len"] == 2
    assert record["mission"] == {"sig": "probe"}
    assert "_rendering" not in record
    assert "telemetry" not in record


def test_parameter_records_envelope_shape():
    pkt = _make_packet()
    rows = list(parameter_log_records(
        pkt,
        session_id="downlink_20260423_140000",
        rx_event_id="parent_event_id",
        version="5.7.0",
        mission_id="maveric", operator="irfan", station="GS-0",
    ))
    assert len(rows) == 2
    for row in rows:
        _assert_envelope(row)
        assert row["event_kind"] == "parameter"
        assert row["rx_event_id"] == "parent_event_id"
        assert row["seq"] == 42
        assert isinstance(row["ts_ms"], int)
        assert row["v"] == "5.7.0"
        assert "domain" not in row
        assert "key" not in row
    assert {row["name"] for row in rows} == {"eps.vbatt", "eps.temp_batt"}


def test_tx_command_envelope_shape():
    with tempfile.TemporaryDirectory() as tmp:
        log = TXLog(tmp, zmq_addr="tcp://127.0.0.1:52002", version="5.7.0",
                    mission_id="maveric", station="GS-0", operator="irfan")
        try:
            raw_cmd = b"\x01\x02\x03"
            wire = b"\x01\x02\x03\x04\x05"
            record = tx_log_record(
                1,
                {"title": "com_ping", "subtitle": "EPS"},
                {"cmd_id": "com_ping", "dest": "EPS", "src": "GS",
                 "echo": "NONE", "ptype": "CMD"},
                raw_cmd, wire,
                session_id=log.session_id,
                ts_ms=1_700_000_000_000,
                version="5.7.0",
                mission_id="maveric", operator="irfan", station="GS-0",
                frame_label="ASM+Golay",
                log_fields={"uplink_mode": "ASM+Golay",
                            "csp": {"prio": 2, "dest": 8}},
            )
            # `uplink_mode` is a legacy alias; defensively cleaned out by
            # tx_log_record so it cannot resurface as either a top-level
            # field or a nested mission key.
            log.write_mission_command(record, raw_cmd=raw_cmd, wire=wire, log_text=[])
        finally:
            log.close()

        with open(log.jsonl_path) as f:
            rec = json.loads(f.readline())

    _assert_envelope(rec)
    assert rec["event_kind"] == "tx_command"
    assert rec["mission_id"] == "maveric"
    assert rec["cmd_id"] == "com_ping"
    assert rec["dest"] == "EPS"
    assert rec["ptype"] == "CMD"
    assert rec["frame_label"] == "ASM+Golay"
    # Legacy `uplink_mode` alias must not surface — neither at top level nor
    # under the nested mission block.
    assert "uplink_mode" not in rec
    assert "uplink_mode" not in rec["mission"]
    assert rec["inner_hex"] == "010203"
    assert rec["inner_len"] == 3
    assert rec["wire_hex"] == "0102030405"
    assert rec["wire_len"] == 5
    # Mission-owned everything under one key
    assert rec["mission"]["display"]["title"] == "com_ping"
    assert rec["mission"]["payload"]["cmd_id"] == "com_ping"
    assert rec["mission"]["csp"]["dest"] == 8


def test_session_id_matches_file_stem():
    with tempfile.TemporaryDirectory() as tmp:
        log = TXLog(tmp, zmq_addr="tcp://127.0.0.1:52002", version="5.7.0",
                    mission_id="maveric", station="GS-0", operator="irfan")
        try:
            record = tx_log_record(
                1, {"title": "x"}, {}, b"", b"",
                session_id=log.session_id,
                ts_ms=1_700_000_000_000,
                version="5.7.0",
                mission_id="maveric", operator="irfan", station="GS-0",
            )
            log.write_mission_command(record, raw_cmd=b"", wire=b"", log_text=[])
            expected_stem = log.session_id
        finally:
            log.close()

        with open(log.jsonl_path) as f:
            rec = json.loads(f.readline())
    assert rec["session_id"] == expected_stem
    import os
    assert os.path.basename(log.jsonl_path).removesuffix(".jsonl") == expected_stem
