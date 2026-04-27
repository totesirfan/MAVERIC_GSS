from pathlib import Path

from mav_gss_lib.platform.loader import load_mission_spec
from mav_gss_lib.platform.parameter_cache import ParameterCache
from mav_gss_lib.platform.rx.pipeline import RxPipeline


def _pipeline_for(spec, tmp_path: Path) -> RxPipeline:
    cache = ParameterCache(tmp_path / "parameters.json")
    return RxPipeline(spec, walker=None, parameter_cache=cache)


def test_rx_pipeline_v2_processes_echo_packet_without_parameters(tmp_path):
    spec = load_mission_spec(
        {"mission": {"id": "echo_v2", "config": {}}, "platform": {}},
        data_dir=tmp_path,
    )
    rx = _pipeline_for(spec, tmp_path)

    result = rx.process({"transmitter": "fixture"}, b"\x01\x02")

    assert result.packet.seq == 1
    assert result.packet.parameters == ()
    assert result.parameters_message is None
    assert result.packet_message["type"] == "packet"
    assert result.packet_message["data"]["raw_hex"] == "0102"
    assert result.packet_message["data"]["_rendering"]["row"]["hex"]["value"] == "0102"


def test_rx_pipeline_v2_balloon_packet_emits_no_parameters_post_swap(tmp_path):
    """balloon_v2 has no declarative spec — packets still flow but no
    parameters."""
    spec = load_mission_spec(
        {"mission": {"id": "balloon_v2", "config": {}}, "platform": {}},
        data_dir=tmp_path,
    )
    rx = _pipeline_for(spec, tmp_path)

    result = rx.process(
        {},
        b'{"type":"beacon","alt_m":1200,"lat":34.0,"lon":-118.2,"temp_c":18.4}',
    )

    assert result.packet.flags.is_unknown is False
    assert result.packet.parameters == ()
    assert result.parameters_message is None
    assert result.packet_message["data"]["_rendering"]["row"]["kind"]["value"] == "beacon"
    assert result.packet_message["data"]["_rendering"]["row"]["alt"]["value"] == 1200


def test_rx_pipeline_v2_marks_unknown_balloon_packet(tmp_path):
    spec = load_mission_spec(
        {"mission": {"id": "balloon_v2", "config": {}}, "platform": {}},
        data_dir=tmp_path,
    )
    rx = _pipeline_for(spec, tmp_path)

    result = rx.process({}, b'{"type":"status"}')

    assert result.packet.flags.is_unknown is True
    assert result.packet_message["data"]["is_unknown"] is True
    assert result.parameters_message is None
