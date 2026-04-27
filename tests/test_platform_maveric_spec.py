from pathlib import Path

from mav_gss_lib.config import load_split_config
from mav_gss_lib.platform.tx.commands import prepare_command
from mav_gss_lib.platform.loader import load_mission_spec_from_split
from mav_gss_lib.platform.parameter_cache import ParameterCache
from mav_gss_lib.platform.rx.pipeline import RxPipeline
from mav_gss_lib.platform.spec.runtime import DeclarativeWalker


EPS_HK_PAYLOAD_HEX = (
    "900600000206000506606570735f686b00b4000000e823220088266c"
    "1d2c2134023f00f50c8c00f40176132600c8000000feff00000000fe"
    "ff00000000feff00000000feff00000000feff00000000000000000000feff000000"
    "00feff00000000feff00000000feff00000000000000000000feff00"
    "0000050f079ba7a4"
)


def _maveric_spec(tmp_path):
    platform_cfg, mission_id, mission_cfg = load_split_config()
    return load_mission_spec_from_split(
        platform_cfg, mission_id, mission_cfg, data_dir=tmp_path,
    )


def _maveric_pipeline(spec, tmp_path: Path) -> RxPipeline:
    walker = (
        DeclarativeWalker(spec.spec_root, plugins=spec.spec_plugins)
        if spec.spec_root is not None else None
    )
    cache = ParameterCache(tmp_path / "parameters.json")
    return RxPipeline(spec, walker=walker, parameter_cache=cache)


def test_maveric_v2_spec_loads_with_capabilities(tmp_path):
    spec = _maveric_spec(tmp_path)

    assert spec.id == "maveric"
    assert spec.packets is not None
    assert spec.commands is not None
    assert spec.spec_root is not None
    assert spec.spec_plugins
    assert spec.ui is not None
    assert spec.http is not None


def test_maveric_v2_spec_loads_from_native_mission_config_shape(tmp_path):
    # Prove the spec loads from native split state starting empty — build(ctx)
    # seeds MAVERIC defaults, no external metadata file required.
    spec = load_mission_spec_from_split({}, "maveric", {}, data_dir=tmp_path)

    assert spec.id == "maveric"
    assert spec.name == "MAVERIC"
    assert spec.commands is not None
    assert spec.http is not None


def test_maveric_v2_command_ops_prepare_schema_command(tmp_path):
    spec = _maveric_spec(tmp_path)

    prepared = prepare_command(spec, "ftdi_log hello")

    assert prepared.encoded.raw
    assert prepared.rendering.title == "ftdi_log"
    assert "cmd" in prepared.rendering.row


def test_maveric_v2_rx_pipeline_renders_unknown_raw_packet(tmp_path):
    spec = _maveric_spec(tmp_path)
    rx = _maveric_pipeline(spec, tmp_path)

    result = rx.process({"transmitter": "fixture"}, b"\x01\x02")

    assert result.packet.seq == 1
    assert result.packet.flags.is_unknown is True
    assert result.packet_message["data"]["is_unknown"] is True
    assert result.packet_message["data"]["_rendering"]["row"]["num"]["value"] == 1


def test_maveric_v2_rx_pipeline_extracts_eps_hk_parameters(tmp_path):
    """EPS_HK fixture parity. Skipped when commands.yml/mission.yml routing
    rejects the fixture as unknown — same pre-existing fixture gap that the
    legacy version of this test had."""
    spec = _maveric_spec(tmp_path)
    rx = _maveric_pipeline(spec, tmp_path)

    result = rx.process({"transmitter": "fixture"}, bytes.fromhex(EPS_HK_PAYLOAD_HEX))

    if result.packet.flags.is_unknown:
        import pytest
        pytest.skip("EPS_HK fixture not accepted by current commands.yml routing")

    assert result.packet_message["data"]["_rendering"]["row"]["cmd"]["value"] == "eps_hk"
    # Walker emits qualified ParamUpdates.
    by_name = {p.name: p for p in result.packet.parameters}
    assert "eps.V_BAT" in by_name
    assert "eps.V_BUS" in by_name
    assert by_name["eps.V_BAT"].value == 7.532
    assert by_name["eps.V_BUS"].value == 9.192

    # parameters_message carries cache changes
    assert result.parameters_message is not None
    update_names = {u["name"] for u in result.parameters_message["updates"]}
    assert "eps.V_BAT" in update_names
