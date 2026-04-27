from dataclasses import dataclass
from typing import Any

from mav_gss_lib.platform import MissionConfigSpec, MissionSpec
from mav_gss_lib.platform.loader import load_mission_spec
from mav_gss_lib.platform.rx.packet_pipeline import PacketPipeline
from mav_gss_lib.platform.rx.rendering import (
    fallback_packet_rendering,
    format_text_log_safe,
    render_log_data_safe,
    render_packet,
)
from mav_gss_lib.missions.echo_v2.mission import EchoPacketOps


def test_render_packet_safe_uses_mission_renderer(tmp_path):
    spec = load_mission_spec(
        {"mission": {"id": "echo_v2", "config": {}}, "platform": {}},
        data_dir=tmp_path,
    )
    packet = PacketPipeline(spec).process({}, b"\xca\xfe")

    rendering = render_packet(spec, packet)

    assert packet.rendering is rendering
    assert rendering.row["hex"].value == "cafe"
    assert rendering.detail_blocks[0].label == "Raw Data"


@dataclass(frozen=True, slots=True)
class ExplodingUiOps:
    def packet_columns(self):
        raise RuntimeError("columns boom")

    def tx_columns(self):
        return []

    def render_packet(self, packet):
        raise RuntimeError("render boom")

    def render_log_data(self, packet) -> dict[str, Any]:
        raise RuntimeError("json boom")

    def format_text_log(self, packet) -> list[str]:
        raise RuntimeError("text boom")


def test_render_packet_safe_falls_back_when_mission_renderer_fails(caplog):
    spec = MissionSpec(
        id="broken_ui",
        name="Broken UI",
        packets=EchoPacketOps(),
        ui=ExplodingUiOps(),
        config=MissionConfigSpec(),
    )
    packet = PacketPipeline(spec).process({}, b"\x01\x02")

    rendering = render_packet(spec, packet)

    assert packet.rendering is rendering
    assert rendering == fallback_packet_rendering(packet)
    assert rendering.row["hex"].value == "0102"
    assert "Packet renderer failed" in caplog.text


def test_log_render_helpers_isolate_mission_failures(caplog):
    spec = MissionSpec(
        id="broken_ui",
        name="Broken UI",
        packets=EchoPacketOps(),
        ui=ExplodingUiOps(),
        config=MissionConfigSpec(),
    )
    packet = PacketPipeline(spec).process({}, b"\x01")

    assert render_log_data_safe(spec, packet) == {}
    assert format_text_log_safe(spec, packet) == []
    assert "Log data renderer failed" in caplog.text
    assert "Text log renderer failed" in caplog.text
