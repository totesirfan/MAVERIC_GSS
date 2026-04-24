"""MAVERIC mission preflight checks.

Mission-specific checks that used to live in `mav_gss_lib/preflight.py` — the
command schema file check and the libfec (ASM+Golay RS encoder) capability
check. These are MAVERIC concerns and the platform preflight driver now
delegates to `MissionSpec.preflight()` for mission-specific results.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from mav_gss_lib.missions.maveric.config_access import command_defs_name


_GOLAY_FIX = (
    "Install libfec (e.g. `sudo apt install libfec-dev && sudo ldconfig`, "
    "`conda install -c ryanvolz libfec`, or build from "
    "https://github.com/quiet/libfec)"
)


def build_preflight(
    platform_config: dict[str, Any],
    mission_config: dict[str, Any],
    mission_dir: Path,
) -> Callable[[], Iterable[Any]]:
    """Return a zero-arg callable that yields MAVERIC preflight CheckResults."""

    def _checks() -> Iterable[Any]:
        # Lazily import CheckResult so this module doesn't import preflight
        # at module load time.
        from mav_gss_lib.preflight import CheckResult

        yield from _command_schema_checks(mission_config, mission_dir, CheckResult)
        yield from _uplink_capability_checks(platform_config, CheckResult)

    return _checks


def _command_schema_checks(
    mission_config: dict[str, Any],
    mission_dir: Path,
    CheckResult: type,
) -> Iterable[Any]:
    cmd_defs = command_defs_name(mission_config)
    path = Path(cmd_defs)
    cmd_schema = path if path.is_absolute() else mission_dir / cmd_defs
    cmd_example = mission_dir / (path.stem + ".example" + path.suffix)
    if cmd_schema.is_file():
        yield CheckResult("config", f"Command schema: {cmd_schema.name}", "ok")
    elif cmd_example.is_file():
        yield CheckResult(
            "config",
            f"Command schema: {cmd_schema.name}",
            "warn",
            fix=f"Copy from example: cp {cmd_example} {cmd_schema}",
        )
    else:
        yield CheckResult(
            "config",
            f"Command schema: {cmd_schema.name}",
            "warn",
            fix="System starts but cannot validate or send commands",
        )


def _uplink_capability_checks(platform_config: dict[str, Any], CheckResult: type) -> Iterable[Any]:
    try:
        from mav_gss_lib.protocols.golay import _GR_RS_OK as _golay_rs_ok
    except ImportError:
        _golay_rs_ok = False

    tx_section = platform_config.get("tx") if isinstance(platform_config.get("tx"), dict) else {}
    selected_mode = str(tx_section.get("uplink_mode", "AX.25"))

    if _golay_rs_ok:
        yield CheckResult("uplink", "libfec (ASM+Golay RS encoder)", "ok")
    elif selected_mode == "ASM+Golay":
        yield CheckResult(
            "uplink", "libfec (ASM+Golay RS encoder)", "fail",
            fix=f"{_GOLAY_FIX}, or switch tx.uplink_mode to AX.25",
            detail="tx.uplink_mode='ASM+Golay' selected but libfec is not loadable",
        )
    else:
        yield CheckResult(
            "uplink", "libfec (ASM+Golay RS encoder)", "warn",
            fix=f"{_GOLAY_FIX} to enable tx.uplink_mode='ASM+Golay'",
            detail="AX.25 mode active; ASM+Golay would be unavailable if selected",
        )
