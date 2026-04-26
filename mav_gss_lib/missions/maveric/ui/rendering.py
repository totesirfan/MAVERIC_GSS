"""MAVERIC RX/TX rendering helpers — declarative shape.

Reads MaverMissionPayload attributes (header, args_raw, valid_crc,
csp_header, csp_plausible, csp_crc32, csp_crc32_valid) +
envelope.parameters directly. No mission_data dict, no NodeTable.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from mav_gss_lib.missions.maveric.ui.formatters import (
    compact_value as _compact_value,
    display_kind,
    display_label as _display_label,
    render_detail_fields,
    render_value,
)

if TYPE_CHECKING:
    from mav_gss_lib.missions.maveric.packets import MaverMissionPayload
    from mav_gss_lib.platform import PacketEnvelope
    from mav_gss_lib.platform.spec import Mission


@dataclass(frozen=True, slots=True)
class ProtocolBlock:
    kind: str
    label: str
    fields: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class IntegrityBlock:
    kind: str
    label: str
    scope: str
    ok: bool | None
    received: str | None = None
    computed: str | None = None


# =============================================================================
#  Time helpers
# =============================================================================


def _split_qname(name: str) -> tuple[str, str]:
    """Split a qualified ParamUpdate name into (group, key)."""
    if "." in name:
        g, k = name.split(".", 1)
        return g, k
    return "", name


def ts_result(envelope: "PacketEnvelope") -> tuple | None:
    """Derive (utc_dt, local_dt, unix_ms) from a 'time' or 'sat_time'
    parameter in envelope.parameters.

    Beacons emit 'time' (BCD-time entry in mission.yml). Commands
    emit 'sat_time' iff mission.yml declares a sequence_container that
    decodes a sat_time arg. When no such parameter is present this
    returns None and the row falls through to envelope.received_at_short.
    """
    for u in envelope.parameters:
        _, key = _split_qname(u.name)
        if key not in ("time", "sat_time"):
            continue
        if not isinstance(u.value, dict):
            continue
        unix_ms = u.value.get("unix_ms")
        if unix_ms is None:
            continue
        try:
            dt_utc = datetime.fromtimestamp(unix_ms / 1000.0, tz=timezone.utc)
            return (dt_utc, dt_utc.astimezone(), unix_ms)
        except (OSError, OverflowError, ValueError):
            return None
    return None


def _ts_for_row(envelope: "PacketEnvelope") -> str:
    """Format the time column. Prefers ts_result (satellite time from
    fragments); falls back to GS receive time."""
    ts = ts_result(envelope)
    if ts is None:
        return envelope.received_at_short
    _, dt_local, _ = ts
    return f"{dt_local.hour:02d}:{dt_local.minute:02d}:{dt_local.second:02d}"


# =============================================================================
#  RX Packet List
# =============================================================================


def packet_list_columns() -> list[dict]:
    """Return column definitions for the RX packet list."""
    return [
        {"id": "num",   "label": "#",         "align": "right", "width": "w-9"},
        {"id": "time",  "label": "time",      "width": "w-[68px]"},
        {"id": "frame", "label": "frame",     "width": "w-[72px]", "toggle": "showFrame"},
        {"id": "src",   "label": "src",       "width": "w-[52px]"},
        {"id": "echo",  "label": "echo",      "width": "w-[52px]", "toggle": "showEcho"},
        {"id": "ptype", "label": "type",      "width": "w-[52px]", "badge": True},
        {"id": "cmd",   "label": "id / args", "flex": True},
        {"id": "flags", "label": "",          "width": "w-[72px]", "align": "right"},
        {"id": "size",  "label": "size",      "align": "right", "width": "w-10"},
    ]


def packet_list_row(payload: "MaverMissionPayload", envelope: "PacketEnvelope") -> dict[str, Any]:
    """Return row values keyed by column ID for one packet."""
    h = payload.header or {}
    flags = []
    if not payload.valid_crc:                 flags.append({"tag": "CRC", "tone": "danger"})
    if envelope.flags.is_uplink_echo:         flags.append({"tag": "UL", "tone": "info"})
    if envelope.flags.is_duplicate:           flags.append({"tag": "DUP", "tone": "warning"})
    if envelope.flags.is_unknown:             flags.append({"tag": "UNK", "tone": "danger"})
    return {
        "values": {
            "num":   envelope.seq,
            "time":  _ts_for_row(envelope),
            "frame": envelope.frame_type,
            "src":   str(h.get("src", "")),
            "echo":  str(h.get("echo", "")),
            "ptype": str(h.get("ptype", "")),
            "cmd":   _cmd_summary(payload, envelope),
            "flags": flags,
            "size":  len(envelope.raw),
        },
        "_meta": {"opacity": 0.5 if envelope.flags.is_unknown else 1.0},
    }


def _cmd_summary(payload: "MaverMissionPayload", envelope: "PacketEnvelope") -> str:
    """Format the cmd column. Walker emits typed args as parameters — read
    them when present; fall back to args_raw.hex() when mission.yml has
    no container for this cmd_id."""
    if payload.header is None:
        return ""
    cmd_id = payload.header.get("cmd_id", "")
    if envelope.parameters:
        # Show up to first 3 emitted parameters compactly.
        parts = []
        for u in envelope.parameters[:3]:
            if u.display_only:
                continue
            _, key = _split_qname(u.name)
            parts.append(f"{key}={_compact_value(u.value, u.unit)}")
        if parts:
            return f"{cmd_id} {' '.join(parts)}".strip()
    if payload.args_raw:
        return f"{cmd_id} {payload.args_raw.hex()}".strip()
    return str(cmd_id)


# =============================================================================
#  Detail View — Protocol & Integrity Blocks
# =============================================================================


def protocol_blocks(payload: "MaverMissionPayload", envelope: "PacketEnvelope") -> list[ProtocolBlock]:
    """Return protocol/wrapper blocks for the detail view."""
    out: list[ProtocolBlock] = []
    if payload.csp_header:
        out.append(ProtocolBlock(
            kind="csp",
            label=("CSP V1" if payload.csp_plausible else "CSP V1 [?]"),
            fields=[
                {"name": k.capitalize(), "value": str(v)}
                for k, v in payload.csp_header.items()
            ],
        ))
    return out


def integrity_blocks(payload: "MaverMissionPayload", envelope: "PacketEnvelope") -> list[IntegrityBlock]:
    """Return integrity check blocks for the detail view."""
    out: list[IntegrityBlock] = [
        IntegrityBlock(
            kind="body_crc",
            label="Body CRC-16",
            scope="inner",
            ok=payload.valid_crc,
        ),
    ]
    if payload.csp_crc32 is not None:
        out.append(IntegrityBlock(
            kind="csp_crc32",
            label="CSP CRC-32C",
            scope="csp",
            ok=payload.csp_crc32_valid,
            received=f"0x{payload.csp_crc32:08X}",
        ))
    return out


# =============================================================================
#  Detail View — Mission Semantic Blocks
# =============================================================================


def packet_detail_blocks(
    payload: "MaverMissionPayload",
    envelope: "PacketEnvelope",
    mission: "Mission",
) -> list[dict[str, Any]]:
    """Return mission-specific semantic blocks for the detail view."""
    blocks: list[dict[str, Any]] = []
    h = payload.header or {}

    # Time block
    time_block = {"kind": "time", "label": "Time", "fields": [
        {"name": "GS Time", "value": envelope.received_at_short},
    ]}
    ts = ts_result(envelope)
    if ts is not None:
        dt_utc, dt_local, _ = ts
        if dt_utc is not None:
            time_block["fields"].append({"name": "SAT UTC", "value": dt_utc.strftime("%H:%M:%S") + " UTC"})
        if dt_local is not None:
            time_block["fields"].append({"name": "SAT Local", "value": dt_local.strftime("%H:%M:%S %Z")})
    blocks.append(time_block)

    # Routing block (when header is present)
    if h:
        blocks.append({"kind": "routing", "label": "Routing", "fields": [
            {"name": "Src",  "value": str(h.get("src", ""))},
            {"name": "Dest", "value": str(h.get("dest", ""))},
            {"name": "Echo", "value": str(h.get("echo", ""))},
            {"name": "Type", "value": str(h.get("ptype", ""))},
            {"name": "Cmd",  "value": str(h.get("cmd_id", ""))},
        ]})

    # Telemetry blocks — partition by group prefix, render via display_kind dispatch.
    cmd_id = h.get("cmd_id") if h else None
    is_beacon = cmd_id == "tlm_beacon"

    sc_canon, sc_raw = _split_canonical_and_raw(envelope.parameters, "spacecraft")
    if sc_canon:
        blocks.append(_frag_block(sc_canon, "SPACECRAFT", mission))
    if sc_raw:
        blocks.append(_frag_block(sc_raw, "SPACECRAFT (raw)", mission))

    eps_canon, eps_raw = _split_canonical_and_raw(envelope.parameters, "eps")
    if eps_canon:
        blocks.append(_frag_block(eps_canon, "EPS", mission))
    if eps_raw:
        blocks.append(_frag_block(eps_raw, "EPS (raw)", mission))

    gnc_canon, gnc_raw = _split_canonical_and_raw(envelope.parameters, "gnc")
    if gnc_canon:
        if is_beacon:
            blocks.append(_frag_block(gnc_canon, "GNC", mission))
        else:
            for u in gnc_canon:
                _, key = _split_qname(u.name)
                dispatch = display_kind(mission, key)
                fields = render_detail_fields(u.value, dispatch, u.unit)
                if not fields:
                    continue
                blocks.append({
                    "kind": "args",
                    "label": _display_label(key),
                    "fields": fields,
                })
    if gnc_raw:
        blocks.append(_frag_block(gnc_raw, "GNC (raw)", mission))

    # Other groups (imaging, hk, etc.) — render as a single block per group
    seen_groups = {"spacecraft", "eps", "gnc"}
    other_groups: dict[str, list] = {}
    for u in envelope.parameters:
        group, _ = _split_qname(u.name)
        if group in seen_groups or not group:
            continue
        other_groups.setdefault(group, []).append(u)
    for group in sorted(other_groups.keys()):
        blocks.append(_frag_block(other_groups[group], group.upper(), mission))

    return blocks


def _split_canonical_and_raw(
    parameters,
    group: str,
) -> tuple[list, list]:
    """Partition envelope.parameters by group prefix + display_only flag."""
    canonical = []
    raw = []
    for u in parameters:
        g, _ = _split_qname(u.name)
        if g != group:
            continue
        if u.display_only:
            raw.append(u)
        else:
            canonical.append(u)
    return canonical, raw


def _frag_block(parameters: list, label: str, mission: "Mission") -> dict[str, Any]:
    """Build one {kind:'args', label, fields} block from a parameter list,
    rendering each value via display_kind / render_value."""
    rows = []
    for u in parameters:
        _, key = _split_qname(u.name)
        dispatch = display_kind(mission, key)
        rendered = render_value(u.value, dispatch, u.unit)
        rows.append({
            "name":  _display_label(key),
            "value": rendered,
        })
    return {"kind": "args", "label": label, "fields": rows}


