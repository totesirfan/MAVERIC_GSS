"""TX log formatter — JSONL envelope for outbound mission commands.

Mirrors ``platform/rx/logging.py``. Platform owns the envelope schema; the
file writer (``mav_gss_lib.logging.TXLog``) is format-agnostic and simply
persists whatever dict lands here. Mission-specific metadata from
``FramedCommand.log_fields`` rides under the nested ``mission`` key, except
for ``uplink_mode`` which is lifted to the top level so SQL ingest can
filter on it without reaching into the nested dict.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from typing import Any

from .._log_envelope import new_event_id, ts_iso


def tx_log_record(
    n: int,
    display: dict,
    mission_payload: dict,
    raw_cmd: bytes,
    wire: bytes,
    *,
    session_id: str,
    ts_ms: int,
    version: str,
    mission_id: str = "",
    operator: str = "",
    station: str = "",
    frame_label: str = "",
    log_fields: dict | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Build the platform-owned TX JSONL envelope for a command send.

    *raw_cmd* is the inner mission command bytes (pre-framing); *wire* is the
    full on-air frame the platform publishes to ZMQ. *log_fields* carries
    mission framer metadata (CSP headers, etc.) — everything except
    ``uplink_mode`` is merged under the ``mission`` block.
    """

    log_fields = dict(log_fields or {})
    mission_payload = dict(mission_payload or {})
    mission_block: dict = {
        "display": display,
        "payload": mission_payload,
    }
    uplink_mode = log_fields.pop("uplink_mode", "")
    mission_block.update(log_fields)

    # Declarative command-ops adapter emits dest/src/echo/ptype under the
    # `header` sub-dict (alongside cmd_id at top-level). Missions without
    # a header sub-dict (echo_v2, balloon_v2) fall through to "" — same
    # behavior as before for those missions.
    header = mission_payload.get("header") or {}

    return {
        "event_id": event_id or new_event_id(),
        "event_kind": "tx_command",
        "session_id": session_id,
        "ts_ms": ts_ms,
        "ts_iso": ts_iso(ts_ms),
        "seq": n,
        "v": version,
        "mission_id": mission_id,
        "operator": operator,
        "station": station,
        "cmd_id": str(mission_payload.get("cmd_id", "")),
        "dest": str(header.get("dest", "")),
        "src": str(header.get("src", "")),
        "echo": str(header.get("echo", "")),
        "ptype": str(header.get("ptype", "")),
        "frame_label": frame_label,
        "uplink_mode": uplink_mode,
        "inner_hex": raw_cmd.hex(),
        "inner_len": len(raw_cmd),
        "wire_hex": wire.hex(),
        "wire_len": len(wire),
        "mission": mission_block,
    }
