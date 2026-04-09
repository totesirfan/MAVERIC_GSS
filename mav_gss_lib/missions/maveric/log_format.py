"""
mav_gss_lib.missions.maveric.log_format -- MAVERIC Logging Format Helpers

Extracts JSONL log fields and text log lines for one received packet.
Platform handles: separator, warnings, hex dump, ASCII.
Mission handles: AX.25 header, CSP header, satellite time,
command routing/args, CRC display.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mav_gss_lib.missions.maveric.schema import format_arg_value

if TYPE_CHECKING:
    from mav_gss_lib.missions.maveric.node_table import NodeTable


def _md(pkt) -> dict:
    """Read mission data from a packet."""
    return getattr(pkt, "mission_data", {}) or {}


def build_log_mission_data(pkt) -> dict:
    """Return MAVERIC-specific fields for the JSONL log mission block.

    This produces the same fields that were previously inlined in
    build_rx_log_record(), but scoped under a 'mission' key in the
    platform envelope.
    """
    md = _md(pkt)
    data = {}
    csp = md.get("csp")
    if csp:
        data["csp_candidate"] = csp
        data["csp_plausible"] = md.get("csp_plausible", False)
    ts_result = md.get("ts_result")
    if ts_result:
        data["sat_ts_ms"] = ts_result[2]
    crc_status = md.get("crc_status", {})
    if crc_status.get("csp_crc32_valid") is not None:
        data["csp_crc32"] = {
            "valid": crc_status["csp_crc32_valid"],
            "received": f"0x{crc_status['csp_crc32_rx']:08x}",
        }
    cmd = md.get("cmd")
    if cmd:
        cmd_log = {
            "src": cmd["src"], "dest": cmd["dest"],
            "echo": cmd["echo"], "pkt_type": cmd["pkt_type"],
            "cmd_id": cmd["cmd_id"], "crc": cmd["crc"],
            "crc_valid": cmd.get("crc_valid"),
        }
        if cmd.get("schema_match"):
            typed_log = {}
            for ta in cmd["typed_args"]:
                if ta["type"] == "epoch_ms" and "ms" in ta["value"]:
                    typed_log[ta["name"]] = ta["value"]["ms"]
                elif ta["type"] == "blob" and isinstance(ta["value"], (bytes, bytearray)):
                    typed_log[ta["name"]] = ta["value"].hex()
                else:
                    typed_log[ta["name"]] = ta["value"]
            cmd_log["args"] = typed_log
            if cmd["extra_args"]:
                cmd_log["extra_args"] = cmd["extra_args"]
        else:
            cmd_log["args"] = cmd["args"]
            if cmd.get("schema_warning"):
                cmd_log["schema_warning"] = cmd["schema_warning"]
        data["cmd"] = cmd_log
        cmd_tail = md.get("cmd_tail")
        if cmd_tail:
            data["tail_hex"] = cmd_tail.hex()
    return data


def format_log_lines(pkt, nodes: NodeTable) -> list[str]:
    """Return MAVERIC-specific text log lines for one packet.

    Platform handles: separator, warnings, hex dump, ASCII.
    Adapter handles: AX.25 header, CSP header, satellite time,
    command routing/args, CRC display.
    """
    md = _md(pkt)
    lines = []

    # AX.25 header
    if pkt.stripped_hdr:
        from mav_gss_lib.protocols.ax25 import ax25_decode_header
        try:
            decoded = ax25_decode_header(bytes.fromhex(pkt.stripped_hdr.replace(" ", "")))
            lines.append(
                f"  {'AX.25 HDR':<12}"
                f"Dest:{decoded['dest']['callsign']}-{decoded['dest']['ssid']}  "
                f"Src:{decoded['src']['callsign']}-{decoded['src']['ssid']}  "
                f"Ctrl:{decoded['control_hex']}  PID:{decoded['pid_hex']}"
            )
        except Exception:
            lines.append(f"  {'AX.25 HDR':<12}{pkt.stripped_hdr}")

    # CSP header
    csp = md.get("csp")
    if csp:
        tag = "CSP V1" if md.get("csp_plausible") else "CSP V1 [?]"
        lines.append(f"  {tag:<12}"
            f"Prio:{csp['prio']}  Src:{csp['src']}  Dest:{csp['dest']}  "
            f"DPort:{csp['dport']}  SPort:{csp['sport']}  Flags:0x{csp['flags']:02X}")

    # Satellite time
    ts_result = md.get("ts_result")
    if ts_result:
        dt_utc, dt_local, raw_ms = ts_result
        lines.append(f"  {'SAT TIME':<12}"
            f"{dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC')} \u2502 "
            f"{dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')}  ({raw_ms})")

    # Command
    cmd = md.get("cmd")
    if cmd:
        lines.append(f"  {'CMD':<12}"
            f"Src:{nodes.node_name(cmd['src'])}  Dest:{nodes.node_name(cmd['dest'])}  "
            f"Echo:{nodes.node_name(cmd['echo'])}  Type:{nodes.ptype_name(cmd['pkt_type'])}")
        lines.append(f"  {'CMD ID':<12}{cmd['cmd_id']}")

        if cmd.get("schema_match"):
            for ta in cmd.get("typed_args", []):
                lines.append(f"  {ta['name'].upper():<12}{format_arg_value(ta)}")
            for i, extra in enumerate(cmd.get("extra_args", [])):
                lines.append(f"  {f'ARG +{i}':<12}{extra}")
        else:
            if cmd.get("schema_warning"):
                lines.append(f"  {'\u26a0 SCHEMA':<12}{cmd['schema_warning']}")
            for i, arg in enumerate(cmd.get("args", [])):
                lines.append(f"  {f'ARG {i}':<12}{arg}")

    # CRC
    if cmd and cmd.get("crc") is not None:
        tag = "OK" if cmd.get("crc_valid") else "FAIL"
        lines.append(f"  {'CRC-16':<12}0x{cmd['crc']:04x} [{tag}]")
    crc_status = md.get("crc_status", {})
    if crc_status.get("csp_crc32_valid") is not None:
        tag = "OK" if crc_status["csp_crc32_valid"] else "FAIL"
        lines.append(f"  {'CRC-32C':<12}0x{crc_status['csp_crc32_rx']:08x} [{tag}]")

    return lines


def is_unknown_packet(mission_data: dict) -> bool:
    """MAVERIC: a packet is unknown when no command was decoded."""
    return mission_data.get("cmd") is None
