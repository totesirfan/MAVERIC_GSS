"""
mav_gss_lib.web_runtime.api.config -- Status / Config Routes

Endpoints: api_status, api_selfcheck, api_config_get, api_config_put

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from mav_gss_lib.config import (
    apply_ax25,
    apply_csp,
    deep_merge_inplace,
    get_rx_zmq_addr,
    get_tx_zmq_addr,
    load_operator_config_raw,
    save_operator_config_raw,
)
from mav_gss_lib.constants import DEFAULT_MISSION, DEFAULT_MISSION_NAME
from ..state import get_runtime
from ..security import require_api_token

router = APIRouter()


@router.get("/api/status")
async def api_status(request: Request):
    runtime = get_runtime(request)
    return {
        "mission": runtime.cfg.get("general", {}).get("mission", DEFAULT_MISSION),
        "mission_name": runtime.cfg.get("general", {}).get("mission_name", DEFAULT_MISSION_NAME),
        "version": runtime.cfg.get("general", {}).get("version", ""),
        "zmq_rx": runtime.rx.status.get(),
        "zmq_tx": runtime.tx.status.get(),
        "uplink_mode": runtime.cfg.get("tx", {}).get("uplink_mode", "AX.25"),
        "frequency": runtime.cfg.get("tx", {}).get("frequency", ""),
        "schema_path": runtime.cfg.get("general", {}).get("command_defs_resolved", "")
            or runtime.cfg.get("general", {}).get("command_defs", ""),
        "schema_count": len(runtime.cmd_defs),
        "schema_warning": runtime.cfg.get("general", {}).get("command_defs_warning", ""),
        "auth_token": runtime.session_token,
        "log_dir": runtime.cfg.get("general", {}).get("log_dir", "logs"),
        "logging": runtime.rx.log is not None,
        "rx_log_text": runtime.rx.log.text_path if runtime.rx.log else None,
        "rx_log_json": runtime.rx.log.jsonl_path if runtime.rx.log else None,
        "tx_log_text": runtime.tx.log.text_path if runtime.tx.log else None,
        "tx_log_json": runtime.tx.log.jsonl_path if runtime.tx.log else None,
    }


@router.get("/api/selfcheck")
async def api_selfcheck(request: Request):
    """Lightweight diagnostic for verifying runtime environment."""
    runtime = get_runtime(request)
    general = runtime.cfg.get("general", {})

    # Resolve config file path
    from mav_gss_lib.config import get_operator_config_path
    config_path = str(get_operator_config_path())
    config_exists = os.path.isfile(config_path)

    # Resolve command schema path
    schema_resolved = general.get("command_defs_resolved", "")
    schema_exists = os.path.isfile(schema_resolved) if schema_resolved else False

    # Web build presence
    from ..state import WEB_DIR
    web_build = (WEB_DIR / "index.html").is_file()
    asset_dir = (WEB_DIR / "assets").is_dir()

    return {
        "mission": general.get("mission", DEFAULT_MISSION),
        "mission_name": general.get("mission_name", ""),
        "version": general.get("version", ""),
        "config_path": config_path,
        "config_exists": config_exists,
        "schema_path": schema_resolved,
        "schema_exists": schema_exists,
        "schema_count": len(runtime.cmd_defs),
        "schema_warning": general.get("command_defs_warning", ""),
        "web_build": web_build,
        "web_assets": asset_dir,
        "zmq_rx_addr": runtime.cfg.get("rx", {}).get("zmq_addr", ""),
        "zmq_tx_addr": runtime.cfg.get("tx", {}).get("zmq_addr", ""),
        "zmq_rx_status": runtime.rx.status.get(),
        "zmq_tx_status": runtime.tx.status.get(),
        "log_dir": general.get("log_dir", "logs"),
        "uplink_mode": runtime.cfg.get("tx", {}).get("uplink_mode", ""),
    }


@router.get("/api/config")
async def api_config_get(request: Request):
    return get_runtime(request).cfg


_STRICT_MISSION_TOP_KEYS = {"nodes", "ptypes", "node_descriptions"}
_STRICT_MISSION_GENERAL_KEYS = {
    "mission_name",
    "gs_node",
    "command_defs",
    "command_defs_resolved",
    "command_defs_warning",
    "rx_title",
    "tx_title",
    "splash_subtitle",
}
_PLATFORM_DERIVED_GENERAL_KEYS = {"version", "build_sha"}


def _strip_persisted_junk(update: dict) -> dict:
    """Remove keys the client must never influence.

    Strips strictly mission-owned top-level sections, runtime-derived and
    mission-owned fields inside `general`, and platform-derived fields
    (`version`) that are single-sourced from `web/package.json`. Preserves
    `ax25`, `csp`, and `tx.*` because those are operator-overridable per
    CLAUDE.md. Mutates and returns the input dict.
    """
    for key in _STRICT_MISSION_TOP_KEYS:
        update.pop(key, None)
    general = update.get("general")
    if isinstance(general, dict):
        for key in _STRICT_MISSION_GENERAL_KEYS:
            general.pop(key, None)
        for key in _PLATFORM_DERIVED_GENERAL_KEYS:
            general.pop(key, None)
    return update


@router.put("/api/config")
async def api_config_put(update: dict, request: Request):
    runtime = get_runtime(request)
    denied = require_api_token(request)
    if denied:
        return denied

    old_rx_addr = get_rx_zmq_addr(runtime.cfg)
    old_tx_addr = get_tx_zmq_addr(runtime.cfg)
    requested_rx_addr = update.get("rx", {}).get("zmq_addr", old_rx_addr) if isinstance(update.get("rx"), dict) else old_rx_addr
    requested_tx_addr = update.get("tx", {}).get("zmq_addr", old_tx_addr) if isinstance(update.get("tx"), dict) else old_tx_addr
    with runtime.tx.send_lock:
        sending_active = runtime.tx.sending["active"]
    if sending_active and (requested_rx_addr != old_rx_addr or requested_tx_addr != old_tx_addr):
        return JSONResponse(status_code=409, content={"error": "cannot change ZMQ addresses during active send"})

    # Mission selection is startup-only; stations catalog is install-time. Both
    # are stripped from runtime updates to prevent UI changes, but NEITHER is in
    # _PLATFORM_DERIVED_GENERAL_KEYS (that set is stripped from the disk-merged
    # config too, which would wipe the on-disk catalog on every UI config save).
    if isinstance(update.get("general"), dict):
        update["general"].pop("mission", None)
    update.pop("stations", None)

    # Strip mission-owned, runtime-derived, and platform-derived keys from
    # the client payload before it reaches runtime state or disk.
    _strip_persisted_junk(update)

    with runtime.cfg_lock:
        deep_merge_inplace(runtime.cfg, update)
        raw_operator = load_operator_config_raw()
        deep_merge_inplace(raw_operator, update)
        raw_operator = _strip_persisted_junk(raw_operator)
        save_operator_config_raw(raw_operator)
        apply_csp(runtime.cfg, runtime.csp)
        apply_ax25(runtime.cfg, runtime.ax25)
        new_rx_addr = runtime.cfg.get("rx", {}).get("zmq_addr", old_rx_addr)
        new_tx_addr = runtime.cfg.get("tx", {}).get("zmq_addr", old_tx_addr)

    if new_tx_addr != old_tx_addr:
        runtime.tx.restart_pub(new_tx_addr)
        if runtime.tx.log:
            runtime.tx.log._zmq_addr = new_tx_addr
    if new_rx_addr != old_rx_addr:
        runtime.rx.restart_receiver()
        if runtime.rx.log:
            runtime.rx.log._zmq_addr = new_rx_addr
    return {"ok": True}
