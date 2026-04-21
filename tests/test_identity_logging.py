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
