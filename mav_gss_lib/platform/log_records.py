"""Unified JSONL record builders for RX, TX, parameter, and alarm events.

The writer classes are format-agnostic. Platform code builds event records
here, then ``mav_gss_lib.logging`` persists them to shared JSONL session files.
"""

from __future__ import annotations

from typing import Any, Iterator

from ._log_envelope import new_event_id, ts_iso
from .contract.mission import MissionSpec
from .contract.packets import PacketEnvelope


def rx_packet_record(
    mission: MissionSpec,
    packet: PacketEnvelope,
    version: str,
    *,
    session_id: str,
    event_id: str | None = None,
    mission_id: str = "",
    operator: str = "",
    station: str = "",
) -> dict[str, Any]:
    """Build one inbound packet event record."""
    event_id = event_id or new_event_id()
    return {
        "event_id": event_id,
        "event_kind": "rx_packet",
        "session_id": session_id,
        "ts_ms": packet.received_at_ms,
        "ts_iso": ts_iso(packet.received_at_ms),
        "seq": packet.seq,
        "v": version,
        "mission_id": mission_id or mission.id,
        "operator": operator,
        "station": station,
        "frame_type": packet.frame_type,
        "transport_meta": str(packet.transport_meta.get("transmitter", "")),
        "raw_hex": packet.raw.hex(),
        "size": len(packet.raw),
        "duplicate": packet.flags.is_duplicate,
        "uplink_echo": packet.flags.is_uplink_echo,
        "unknown": packet.flags.is_unknown,
        "warnings": list(packet.warnings),
        "mission": dict(packet.mission or {}),
    }


def parameter_records(
    packet: PacketEnvelope,
    *,
    session_id: str,
    rx_event_id: str,
    version: str,
    mission_id: str,
    operator: str = "",
    station: str = "",
) -> Iterator[dict[str, Any]]:
    """Yield one parameter event record per ``ParamUpdate`` on *packet*."""
    for u in packet.parameters:
        yield {
            "event_id": new_event_id(),
            "event_kind": "parameter",
            "session_id": session_id,
            "ts_ms": u.ts_ms or packet.received_at_ms,
            "ts_iso": ts_iso(u.ts_ms or packet.received_at_ms),
            "seq": packet.seq,
            "v": version,
            "mission_id": mission_id,
            "operator": operator,
            "station": station,
            "rx_event_id": rx_event_id,
            "name": u.name,
            "value": u.value,
            "unit": u.unit,
            "display_only": u.display_only,
        }


def tx_command_record(
    n: int,
    cmd_id: str,
    mission_facts: dict,
    parameters: list[dict],
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
    """Build one outbound command event record.

    `mission_facts` mirrors the RX `MissionFacts.facts` shape (for example
    mission-owned header/protocol blocks). `parameters` is the typed-args
    list (each `{name, value, unit, ...}`). `cmd_id` stays under the
    mission-owned block so the top-level envelope remains generic.
    """
    log_fields = dict(log_fields or {})
    mission_block: dict = {
        "id": mission_id,
        "cmd_id": cmd_id,
        "facts": dict(mission_facts or {}),
        "parameters": list(parameters or ()),
    }
    mission_block.update(log_fields)

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
        "frame_label": frame_label,
        "inner_hex": raw_cmd.hex(),
        "inner_len": len(raw_cmd),
        "wire_hex": wire.hex(),
        "wire_len": len(wire),
        "mission": mission_block,
    }


def radio_event_record(
    action: str,
    *,
    session_id: str,
    ts_ms: int,
    version: str,
    mission_id: str = "",
    operator: str = "",
    station: str = "",
    state: str = "",
    pid: int | None = None,
    exit_code: int | None = None,
    command: list[str] | None = None,
    script: str = "",
    cwd: str = "",
    detail: str = "",
    expected: bool | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Build one GNU Radio supervisor lifecycle event record."""
    return {
        "event_id": event_id or new_event_id(),
        "event_kind": "radio",
        "session_id": session_id,
        "ts_ms": ts_ms,
        "ts_iso": ts_iso(ts_ms),
        "seq": 0,
        "v": version,
        "mission_id": mission_id,
        "operator": operator,
        "station": station,
        "radio": {
            "action": action,
            "state": state,
            "pid": pid,
            "exit_code": exit_code,
            "command": list(command or ()),
            "script": script,
            "cwd": cwd,
            "detail": detail,
            "expected": expected,
        },
    }
