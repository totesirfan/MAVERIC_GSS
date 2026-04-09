"""
mav_gss_lib.missions.maveric.rendering -- MAVERIC RX/TX Rendering Helpers

Module-level rendering slot functions extracted from MavericMissionAdapter.
These provide column definitions and packet-to-display transformations for
the RX packet list, detail view, and TX queue/history.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mav_gss_lib.missions.maveric.node_table import NodeTable


def _md(pkt) -> dict:
    """Read mission data from a packet."""
    return getattr(pkt, "mission_data", {}) or {}


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


def packet_list_row(pkt, nodes: NodeTable) -> dict:
    """Return row values keyed by column ID for one packet."""
    md = _md(pkt)
    cmd = md.get("cmd")
    args_str = ""
    if cmd and cmd.get("schema_match") and cmd.get("typed_args"):
        important = [ta for ta in cmd["typed_args"] if ta.get("important")]
        show = important if important else cmd["typed_args"]
        parts = []
        for ta in show:
            val = ta.get("value", "")
            if ta["type"] == "epoch_ms":
                val = val.ms if hasattr(val, "ms") else (val["ms"] if isinstance(val, dict) and "ms" in val else val)
            if isinstance(val, (bytes, bytearray)):
                val = val.hex()
            parts.append(str(val))
        args_str = " ".join(parts)
    elif cmd:
        raw = cmd.get("args", [])
        args_str = " ".join(str(a) for a in raw) if isinstance(raw, list) else str(raw)

    flags = []
    if cmd and cmd.get("crc_valid") is False:
        flags.append({"tag": "CRC", "tone": "danger"})
    if pkt.is_uplink_echo:
        flags.append({"tag": "UL", "tone": "info"})
    if pkt.is_dup:
        flags.append({"tag": "DUP", "tone": "warning"})
    if pkt.is_unknown:
        flags.append({"tag": "UNK", "tone": "danger"})

    return {
        "values": {
            "num": pkt.pkt_num,
            "time": pkt.gs_ts_short,
            "frame": pkt.frame_type,
            "src": nodes.node_name(cmd["src"]) if cmd else "",
            "echo": nodes.node_name(cmd["echo"]) if cmd else "",
            "ptype": nodes.ptype_name(cmd["pkt_type"]) if cmd else "",
            "cmd": ((cmd["cmd_id"] + " " + args_str).strip() if args_str else cmd["cmd_id"]) if cmd else "",
            "flags": flags,
            "size": len(pkt.raw),
        },
        "_meta": {"opacity": 0.5 if pkt.is_unknown else 1.0},
    }


# =============================================================================
#  Detail View — Protocol & Integrity Blocks
# =============================================================================


def protocol_blocks(pkt) -> list:
    """Return protocol/wrapper blocks for the detail view."""
    from mav_gss_lib.mission_adapter import ProtocolBlock
    from mav_gss_lib.protocols.ax25 import ax25_decode_header
    md = _md(pkt)
    csp = md.get("csp")
    blocks = []
    if csp:
        blocks.append(ProtocolBlock(
            kind="csp",
            label="CSP V1",
            fields=[{"name": k.capitalize(), "value": str(v)} for k, v in csp.items()],
        ))
    if pkt.stripped_hdr:
        ax25_fields = [{"name": "Header", "value": pkt.stripped_hdr}]
        try:
            decoded = ax25_decode_header(bytes.fromhex(pkt.stripped_hdr.replace(" ", "")))
            ax25_fields = [
                {"name": "Dest", "value": f"{decoded['dest']['callsign']}-{decoded['dest']['ssid']}"},
                {"name": "Src", "value": f"{decoded['src']['callsign']}-{decoded['src']['ssid']}"},
                {"name": "Control", "value": decoded["control_hex"]},
                {"name": "PID", "value": decoded["pid_hex"]},
            ]
        except Exception:
            pass
        blocks.append(ProtocolBlock(
            kind="ax25",
            label="AX.25",
            fields=ax25_fields,
        ))
    return blocks


def integrity_blocks(pkt) -> list:
    """Return integrity check blocks for the detail view."""
    from mav_gss_lib.mission_adapter import IntegrityBlock
    md = _md(pkt)
    blocks = []
    cmd = md.get("cmd")
    if cmd and cmd.get("crc") is not None:
        blocks.append(IntegrityBlock(
            kind="crc16",
            label="CRC-16",
            scope="command",
            ok=cmd.get("crc_valid"),
            received=f"0x{cmd['crc']:04X}" if cmd.get("crc") is not None else None,
        ))
    crc_status = md.get("crc_status", {})
    if crc_status.get("csp_crc32_valid") is not None:
        blocks.append(IntegrityBlock(
            kind="crc32c",
            label="CRC-32C",
            scope="csp",
            ok=crc_status["csp_crc32_valid"],
            received=f"0x{crc_status['csp_crc32_rx']:08X}" if crc_status.get("csp_crc32_rx") is not None else None,
            computed=f"0x{crc_status['csp_crc32_comp']:08X}" if crc_status.get("csp_crc32_comp") is not None else None,
        ))
    return blocks


def packet_detail_blocks(pkt, nodes: NodeTable) -> list[dict]:
    """Return mission-specific semantic blocks for the detail view."""
    md = _md(pkt)
    cmd = md.get("cmd")
    ts_result = md.get("ts_result")
    blocks = []

    time_block = {"kind": "time", "label": "Time", "fields": [
        {"name": "GS Time", "value": pkt.gs_ts},
    ]}
    if ts_result:
        dt_utc, dt_local, ms = ts_result
        if dt_utc:
            time_block["fields"].append({"name": "SAT UTC", "value": dt_utc.strftime("%H:%M:%S") + " UTC"})
        if dt_local:
            time_block["fields"].append({"name": "SAT Local", "value": dt_local.strftime("%H:%M:%S %Z")})
    blocks.append(time_block)

    if cmd:
        blocks.append({"kind": "routing", "label": "Routing", "fields": [
            {"name": "Src", "value": nodes.node_name(cmd["src"])},
            {"name": "Dest", "value": nodes.node_name(cmd["dest"])},
            {"name": "Echo", "value": nodes.node_name(cmd["echo"])},
            {"name": "Type", "value": nodes.ptype_name(cmd["pkt_type"])},
            {"name": "Cmd", "value": cmd["cmd_id"]},
        ]})

    if cmd and cmd.get("schema_match") and cmd.get("typed_args"):
        args_fields = []
        for ta in cmd["typed_args"]:
            val = ta.get("value", "")
            if ta["type"] == "epoch_ms":
                val = val.ms if hasattr(val, "ms") else (val["ms"] if isinstance(val, dict) and "ms" in val else val)
            if isinstance(val, (bytes, bytearray)):
                val = val.hex()
            args_fields.append({"name": ta["name"], "value": str(val)})
        for i, extra in enumerate(cmd.get("extra_args", [])):
            args_fields.append({"name": f"arg{len(cmd.get('typed_args', [])) + i}", "value": str(extra)})
        if args_fields:
            blocks.append({"kind": "args", "label": "Arguments", "fields": args_fields})
    elif cmd:
        raw = cmd.get("args", [])
        if raw:
            args_fields = [{"name": f"arg{i}", "value": str(a)} for i, a in enumerate(raw)]
            blocks.append({"kind": "args", "label": "Arguments", "fields": args_fields})

    return blocks


# =============================================================================
#  TX Queue / History
# =============================================================================


def tx_queue_columns() -> list[dict]:
    """Return column definitions for the TX queue/history list."""
    return [
        {"id": "src",   "label": "src",       "width": "w-[52px]", "hide_if_all": ["GS"]},
        {"id": "dest",  "label": "dest",      "width": "w-[52px]"},
        {"id": "echo",  "label": "echo",      "width": "w-[52px]", "hide_if_all": ["NONE"]},
        {"id": "ptype", "label": "type",      "width": "w-[52px]", "badge": True},
        {"id": "cmd",   "label": "id / args", "flex": True},
    ]
