from mav_gss_lib.parsing import Packet, build_rx_log_record


class _FakeAdapter:
    def protocol_blocks(self, pkt):      return []
    def integrity_blocks(self, pkt):     return []
    def packet_list_row(self, pkt):      return {}
    def packet_detail_blocks(self, pkt): return []
    def build_log_mission_data(self, pkt): return None


def test_rx_record_carries_identity():
    pkt = Packet(pkt_num=1, gs_ts="2026-04-21T12:00:00Z", frame_type="AX.25", raw=b"abc", inner_payload=b"a")
    record = build_rx_log_record(
        pkt, version="1.2.3", meta={"transmitter": "gr"}, adapter=_FakeAdapter(),
        operator="irfan", station="GS-0",
    )
    assert record["operator"] == "irfan"
    assert record["station"] == "GS-0"


import json
import os

from mav_gss_lib.logging import TXLog
from mav_gss_lib.protocols.ax25 import AX25Config
from mav_gss_lib.protocols.csp import CSPConfig


def test_tx_record_carries_identity(tmp_path):
    log = TXLog(str(tmp_path), zmq_addr="tcp://127.0.0.1:52002", version="1.2.3")
    try:
        log.write_mission_command(
            n=1,
            display={"title": "PING", "subtitle": ""},
            mission_payload={"cmd": "ping"},
            raw_cmd=b"\x01\x02",
            payload=b"\x01\x02",
            ax25=AX25Config(),
            csp=CSPConfig(),
            operator="irfan",
            station="GS-0",
        )
    finally:
        log.close()

    with open(log.jsonl_path) as f:
        rec = json.loads(f.readline())
    assert rec["operator"] == "irfan"
    assert rec["station"] == "GS-0"


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
