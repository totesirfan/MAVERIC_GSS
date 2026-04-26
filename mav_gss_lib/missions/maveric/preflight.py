"""MAVERIC mission preflight checks.

Mission-specific checks that used to live in `mav_gss_lib/preflight.py` —
the mission-database file check and the libfec (ASM+Golay RS encoder)
capability check. The platform preflight driver delegates to
`MissionSpec.preflight()` for mission-specific results.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable


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

        yield from _mission_yml_checks(mission_dir, CheckResult)
        yield from _uplink_capability_checks(platform_config, CheckResult)

    return _checks


def _mission_yml_checks(mission_dir: Path, CheckResult: type) -> Iterable[Any]:
    mission_yml = mission_dir / "mission.yml"
    if mission_yml.is_file():
        yield CheckResult("config", f"Mission schema: {mission_yml.name}", "ok")
    else:
        yield CheckResult(
            "config",
            "Mission schema: mission.yml",
            "fail",
            fix=f"Place mission.yml at {mission_yml} (gitignored — see CLAUDE.md).",
            detail="System cannot decode telemetry or encode commands without mission.yml.",
        )


def _uplink_capability_checks(platform_config: dict[str, Any], CheckResult: type) -> Iterable[Any]:
    try:
        from mav_gss_lib.platform.framing.asm_golay import _GR_RS_OK as _golay_rs_ok
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
