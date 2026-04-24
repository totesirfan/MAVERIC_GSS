from pathlib import Path
import io
import tokenize


def test_platform_package_public_api_imports():
    import mav_gss_lib.platform as platform

    assert platform.MissionSpec
    assert platform.PlatformRuntime
    assert platform.RxPipeline
    assert platform.prepare_command
    assert platform.rx_log_record


def test_platform_package_does_not_import_maveric():
    root = Path("mav_gss_lib/platform")
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text()
        if "missions.maveric" in text:
            offenders.append(str(path))

    assert offenders == []


def test_server_does_not_use_legacy_adapter_boundary():
    root = Path("mav_gss_lib/server")
    forbidden = (
        "runtime.adapter",
        "load_mission_adapter",
        "MissionAdapter",
        "cmd_defs",
    )
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text()
        for pattern in forbidden:
            if pattern in text:
                offenders.append((str(path), pattern))

    assert offenders == []


def test_maveric_v2_runtime_does_not_import_legacy_adapter_boundary():
    root = Path("mav_gss_lib/missions/maveric")
    allowed = {"adapter.py", "__init__.py", "README.md"}
    offenders = []
    for path in root.rglob("*.py"):
        if path.name in allowed:
            continue
        text = path.read_text()
        if "mission_adapter" in text or "ParsedPacket" in text:
            offenders.append(str(path))

    assert offenders == []


def test_platform_package_does_not_encode_maveric_vocabulary():
    root = Path("mav_gss_lib/platform")
    forbidden = (
        "nodes",
        "ptypes",
        "gs_node",
        "imaging",
        "node_name",
        "ptype",
        "ptype_name",
        "resolve_node",
        "resolve_ptype",
    )
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text()
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for token in tokens:
            if token.type == tokenize.NAME and token.string in forbidden:
                offenders.append((str(path), token.string))

    assert offenders == []
