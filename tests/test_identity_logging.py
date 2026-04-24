from mav_gss_lib.platform import MissionSpec
from mav_gss_lib.platform.rx.logging import rx_log_record
from mav_gss_lib.platform.contract.packets import PacketEnvelope, PacketFlags
from mav_gss_lib.platform.contract.rendering import PacketRendering


class _Ui:
    def packet_columns(self): return []
    def tx_columns(self): return []
    def render_packet(self, packet): return PacketRendering(columns=[], row={})
    def render_log_data(self, packet): return {}
    def format_text_log(self, packet): return []


def test_rx_record_carries_identity():
    pkt = PacketEnvelope(
        seq=1,
        received_at_ms=0,
        received_at_text="2026-04-21T12:00:00Z",
        received_at_short="12:00:00",
        frame_type="AX.25",
        raw=b"abc",
        payload=b"a",
        transport_meta={"transmitter": "gr"},
        warnings=[],
        mission_payload={},
        flags=PacketFlags(),
    )
    spec = MissionSpec(id="test", name="Test", packets=None, ui=_Ui(), config=None)
    record = rx_log_record(
        spec, pkt, version="1.2.3",
        session_id="downlink_test",
        operator="irfan", station="GS-0",
    )
    assert record["operator"] == "irfan"
    assert record["station"] == "GS-0"
    assert record["event_kind"] == "rx_packet"
    assert record["session_id"] == "downlink_test"


import json
import os

from mav_gss_lib.logging import TXLog
from mav_gss_lib.platform.tx.logging import tx_log_record


def test_tx_record_carries_identity(tmp_path):
    log = TXLog(str(tmp_path), zmq_addr="tcp://127.0.0.1:52002", version="1.2.3")
    try:
        record = tx_log_record(
            1,
            {"title": "PING", "subtitle": ""},
            {"cmd": "ping"},
            b"\x01\x02", b"\x01\x02",
            session_id=log.session_id,
            ts_ms=1_700_000_000_000,
            version="1.2.3",
            operator="irfan", station="GS-0",
            frame_label="RAW",
            log_fields={"uplink_mode": "RAW"},
        )
        log.write_mission_command(record, raw_cmd=b"\x01\x02", wire=b"\x01\x02", log_text=[])
    finally:
        log.close()

    with open(log.jsonl_path) as f:
        rec = json.loads(f.readline())
    assert rec["operator"] == "irfan"
    assert rec["station"] == "GS-0"
    assert rec["uplink_mode"] == "RAW"
    assert rec["frame_label"] == "RAW"


import re


def test_rx_filename_includes_station_and_operator(tmp_path):
    from mav_gss_lib.logging import SessionLog
    log = SessionLog(str(tmp_path), zmq_addr="tcp://127.0.0.1:52001", version="1.2.3",
                     station="GS-0", operator="irfan")
    try:
        name = os.path.basename(log.jsonl_path)
        # shape: downlink_<ts>_<station>_<operator>_<tag>.jsonl (tag empty)
        assert re.match(r"downlink_\d{8}_\d{6}_GS-0_irfan(?:_.*)?\.jsonl$", name), name
    finally:
        log.close()


def test_text_banner_includes_identity_lines(tmp_path):
    from mav_gss_lib.logging import SessionLog
    log = SessionLog(str(tmp_path), zmq_addr="tcp://127.0.0.1:52001", version="1.2.3",
                     station="GS-0", operator="irfan")
    try:
        with open(log.text_path) as f:
            text = f.read()
        assert "Operator:" in text and "irfan" in text
        assert "Station:" in text and "GS-0" in text
    finally:
        log.close()
