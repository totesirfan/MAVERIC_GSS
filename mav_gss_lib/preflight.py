"""
mav_gss_lib.preflight -- Shared Preflight Check Library

Defines structured preflight checks as a generator yielding CheckResult
events. Used by both the CLI script and the web backend.

Author:  Irfan Annuar - USC ISI SERC
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from mav_gss_lib.config import get_rx_zmq_addr, get_tx_zmq_addr
from mav_gss_lib.constants import DEFAULT_MISSION

_LIB_DIR = Path(__file__).resolve().parent


@dataclass
class CheckResult:
    group: str
    label: str
    status: str        # "ok" | "fail" | "warn" | "skip"
    fix: str = ""
    detail: str = ""


@dataclass
class PreflightSummary:
    total: int
    passed: int
    failed: int
    warnings: int
    ready: bool


def summarize(results: list[CheckResult]) -> PreflightSummary:
    passed = sum(1 for r in results if r.status == "ok")
    failed = sum(1 for r in results if r.status == "fail")
    warnings = sum(1 for r in results if r.status == "warn")
    return PreflightSummary(
        total=len(results),
        passed=passed,
        failed=failed,
        warnings=warnings,
        ready=failed == 0,
    )


def run_preflight(cfg: dict | None = None,
                  mission_cfg: dict | None = None,
                  mission: Any = None,
                  mission_id: str | None = None,
                  lib_dir: Path | None = None,
                  *,
                  operator: str | None = None,
                  host: str | None = None,
                  station: str | None = None) -> Iterator[CheckResult]:
    """Yield check results as each check executes.

    Args:
        cfg: Pre-loaded platform config dict (native `platform_cfg` shape or
            legacy flat runtime cfg — both expose `tx.uplink_mode`,
            `rx.zmq_addr`, `tx.zmq_addr` at the same paths). If None, loads
            from gss.yml.
        mission_cfg: Mission-config dict for mission-specific checks such as
            command-schema path resolution. Optional for legacy callers.
        mission: Optional `MissionSpec` whose `preflight()` hook, if set, is
            called after the platform-neutral checks. Mission-specific checks
            (command schema file presence, radio capability probes, etc.)
            live under `MissionSpec.preflight` — the platform preflight no
            longer branches on mission id.
        mission_id: Active mission id. When None, falls back to
            `cfg.general.mission` (legacy) or `mission.id` when a MissionSpec
            is provided. Preferred in newer callers since `platform_cfg` does
            not carry `general.mission`.
        lib_dir: Library directory for path resolution. Defaults to mav_gss_lib/.
        operator, host, station: Inject identity captured elsewhere (e.g. from
            the already-running WebRuntime). When any of these is None, the
            missing field is captured fresh. Keep these in sync with
            runtime.operator/host/station to avoid drift between preflight
            and /api/identity.
    """
    if lib_dir is None:
        lib_dir = _LIB_DIR

    # ── Identity (informational — always PASS) ──
    # Prefer injected identity to avoid drift between preflight and /api/identity.
    from mav_gss_lib.identity import capture_host, capture_operator, capture_station
    if operator is None:
        operator = capture_operator()
    if host is None:
        host = capture_host()
    if station is None:
        station = capture_station(cfg or {}, host)
    yield CheckResult(
        "identity",
        f"OP {operator}  ·  Station {station}",
        "ok",
        detail=f"operator={operator}  host={host}  station={station}",
    )

    # ── Python Dependencies ──
    for mod, pkg, install in [
        ("fastapi", "fastapi", "pip install fastapi"),
        ("uvicorn", "uvicorn", "pip install uvicorn"),
        ("websockets", "websockets", "pip install websockets"),
        ("yaml", "PyYAML", "pip install PyYAML"),
        ("zmq", "pyzmq", "pip install pyzmq"),
        ("crcmod", "crcmod", "pip install crcmod"),
    ]:
        try:
            importlib.import_module(mod)
            yield CheckResult("python_deps", pkg, "ok")
        except ImportError:
            yield CheckResult("python_deps", pkg, "fail", fix=install)

    # ── GNU Radio / PMT ──
    try:
        importlib.import_module("pmt")
        yield CheckResult("gnuradio", "pmt (GNU Radio)", "ok")
    except ImportError:
        yield CheckResult("gnuradio", "pmt (GNU Radio)", "fail",
                          fix="Activate radioconda: conda activate radioconda")

    # ── Config Files ──
    gss_yml = lib_dir / "gss.yml"
    gss_example = lib_dir / "gss.example.yml"
    if gss_yml.is_file():
        yield CheckResult("config", "gss.yml exists", "ok")
    else:
        yield CheckResult("config", "gss.yml exists", "fail",
                          fix=f"Copy from example: cp {gss_example} {gss_yml}")

    # Load config for remaining checks
    if cfg is None:
        if gss_yml.is_file():
            from mav_gss_lib.config import load_split_config
            platform_cfg, _mission_id, loaded_mission_cfg = load_split_config(str(gss_yml))
            cfg = platform_cfg
            if mission_cfg is None:
                mission_cfg = loaded_mission_cfg
        else:
            cfg = {}

    if mission_id is None:
        if mission is not None and getattr(mission, "id", None):
            mission_id = str(mission.id)
        else:
            mission_id = cfg.get("general", {}).get("mission", DEFAULT_MISSION)
    mission_dir = lib_dir / "missions" / mission_id
    if mission_dir.is_dir():
        yield CheckResult("config", f"Mission: {mission_id}", "ok")
    else:
        yield CheckResult("config", f"Mission: {mission_id}", "fail",
                          fix=f"Set mission.id in gss.yml or create {mission_dir}")

    # Mission-specific checks (command schema, radio capability, etc.) come
    # from the mission's preflight hook. The platform doesn't branch on
    # mission id or inspect mission-private wire modes.
    if mission is not None and getattr(mission, "preflight", None) is not None:
        try:
            for check in mission.preflight():
                yield check
        except Exception as exc:
            yield CheckResult(
                "config",
                f"Mission preflight ({mission_id})",
                "fail",
                detail=str(exc),
            )

    # ── Web Build ──
    dist = lib_dir / "web" / "dist"
    index = dist / "index.html"
    if index.is_file():
        yield CheckResult("web_build", "Web build (dist/index.html)", "ok")
    else:
        yield CheckResult("web_build", "Web build (dist/index.html)", "fail",
                          fix="Run: cd mav_gss_lib/web && npm install && npm run build")

    # ── ZMQ Addresses ──
    rx_addr = get_rx_zmq_addr(cfg)
    tx_addr = get_tx_zmq_addr(cfg)
    yield CheckResult("zmq", "RX SUB", "ok", detail=rx_addr)
    yield CheckResult("zmq", "TX PUB", "ok", detail=tx_addr)
