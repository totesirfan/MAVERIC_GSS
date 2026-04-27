from dataclasses import dataclass
from typing import Any

from mav_gss_lib.platform import MissionConfigSpec, MissionPacket, MissionSpec, NormalizedPacket, PacketFlags, PacketOps
from mav_gss_lib.platform.loader import load_mission_spec
from mav_gss_lib.platform.rx.packet_pipeline import PacketPipeline
from mav_gss_lib.missions.echo_v2.mission import EchoUiOps


def test_packet_pipeline_builds_echo_envelope(tmp_path):
    spec = load_mission_spec(
        {"mission": {"id": "echo_v2", "config": {}}, "platform": {}},
        data_dir=tmp_path,
    )
    pipeline = PacketPipeline(spec)

    pkt = pipeline.process({"transmitter": "fixture"}, b"\x01\x02")

    assert pkt.seq == 1
    assert pkt.raw == b"\x01\x02"
    assert pkt.payload == b"\x01\x02"
    assert pkt.frame_type == "RAW"
    assert pkt.transport_meta == {"transmitter": "fixture"}
    assert pkt.mission_payload == {"hex": "0102"}
    assert pkt.flags.is_unknown is False
    assert pkt.flags.is_duplicate is False
    assert pipeline.packet_count == 1
    assert pipeline.unknown_count == 0


def test_packet_pipeline_tracks_unknown_balloon_packets(tmp_path):
    spec = load_mission_spec(
        {"mission": {"id": "balloon_v2", "config": {}}, "platform": {}},
        data_dir=tmp_path,
    )
    pipeline = PacketPipeline(spec)

    pkt = pipeline.process({}, b'{"type":"status"}')

    assert pkt.seq == 1
    assert pkt.flags.is_unknown is True
    assert pipeline.packet_count == 0
    assert pipeline.unknown_count == 1


@dataclass(frozen=True, slots=True)
class DuplicatePacketOps(PacketOps):
    def normalize(self, meta: dict[str, Any], raw: bytes) -> NormalizedPacket:
        return NormalizedPacket(raw=raw, payload=raw, frame_type="RAW")

    def parse(self, normalized: NormalizedPacket) -> MissionPacket:
        return MissionPacket(payload={"raw": normalized.payload.hex()})

    def classify(self, packet: MissionPacket) -> PacketFlags:
        return PacketFlags(duplicate_key=("fixed",))


def test_packet_pipeline_sets_duplicate_flag_on_repeated_key():
    spec = MissionSpec(
        id="dupe",
        name="Duplicate Fixture",
        packets=DuplicatePacketOps(),
        ui=EchoUiOps(),
        config=MissionConfigSpec(),
    )
    pipeline = PacketPipeline(spec)

    first = pipeline.process({}, b"\x01")
    second = pipeline.process({}, b"\x02")

    assert first.flags.is_duplicate is False
    assert second.flags.is_duplicate is True
    assert pipeline.packet_count == 2


def test_packet_pipeline_reset_counts_clears_duplicate_window():
    spec = MissionSpec(
        id="dupe",
        name="Duplicate Fixture",
        packets=DuplicatePacketOps(),
        ui=EchoUiOps(),
        config=MissionConfigSpec(),
    )
    pipeline = PacketPipeline(spec)

    pipeline.process({}, b"\x01")
    pipeline.reset_counts()
    pkt = pipeline.process({}, b"\x02")

    assert pkt.seq == 1
    assert pkt.flags.is_duplicate is False
