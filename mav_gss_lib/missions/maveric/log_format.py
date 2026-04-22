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

from mav_gss_lib.missions.maveric.display_helpers import (
    md as _md,
    ptype_of as _ptype_of,
    should_hide_args as _should_hide_args,
    unwrap_typed_arg_for_log,
    format_typed_arg_value,
    is_nvg_sensor, is_bcd_display, is_adcs_tmp, is_nvg_heartbeat,
    is_gnc_mode, is_gnc_counters,
)

if TYPE_CHECKING:
    from mav_gss_lib.missions.maveric.nodes import NodeTable


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
            cmd_log["args"] = {ta["name"]: unwrap_typed_arg_for_log(ta) for ta in cmd["typed_args"]}
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

    # Decoded mission telemetry — the single per-packet payload produced
    # by mission extractors. The text-log path in format_log_lines
    # iterates this same list; JSONL and text logs stay in sync by
    # construction, no symmetry patch required.
    frags = md.get("fragments")
    if frags:
        data["fragments"] = frags
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
    hide_args = _should_hide_args(cmd, md)

    if cmd:
        lines.append(f"  {'CMD':<12}"
            f"Src:{nodes.node_name(cmd['src'])}  Dest:{nodes.node_name(cmd['dest'])}  "
            f"Echo:{nodes.node_name(cmd['echo'])}  Type:{nodes.ptype_name(_ptype_of(md))}")
        lines.append(f"  {'CMD ID':<12}{cmd['cmd_id']}")

        if not hide_args:
            if cmd.get("schema_match"):
                for ta in cmd.get("typed_args", []):
                    lines.append(f"  {ta['name'].upper():<12}{format_typed_arg_value(ta)}")
                for i, extra in enumerate(cmd.get("extra_args", [])):
                    lines.append(f"  {f'ARG +{i}':<12}{extra}")
            else:
                if cmd.get("schema_warning"):
                    lines.append(f"  {'\u26a0 SCHEMA':<12}{cmd['schema_warning']}")
                for i, arg in enumerate(cmd.get("args", [])):
                    lines.append(f"  {f'ARG {i}':<12}{arg}")

    # Decoded telemetry — one source (mission extractors), one list.
    # Platform / EPS fragments render as a simple `  <KEY>  <value> <unit>`
    # line; GNC fragments delegate to the register block formatter, which
    # handles structured values (BCD, bitfields, NVG sensors, etc.).
    # Platform comes first so beacon packets show the shared prefix
    # (time, ops_stage, reboot counts, heartbeats, hn/ab states) before
    # the variant tail — matches the wire order.
    frags = md.get("fragments") or []
    for frag in frags:
        if frag["domain"] == "platform":
            suffix = f" {frag['unit']}" if frag.get("unit") else ""
            lines.append(f"  {frag['key']:<16}{frag['value']}{suffix}")
    for frag in frags:
        if frag["domain"] == "eps":
            suffix = f" {frag['unit']}" if frag.get("unit") else ""
            lines.append(f"  {frag['key']:<12}{frag['value']}{suffix}")
    for frag in frags:
        if frag["domain"] == "gnc":
            lines.extend(_format_gnc_register_lines(
                frag["key"], frag["value"], frag.get("unit", "")
            ))

    # CRC
    if cmd and cmd.get("crc") is not None:
        tag = "OK" if cmd.get("crc_valid") else "FAIL"
        lines.append(f"  {'CRC-16':<12}0x{cmd['crc']:04x} [{tag}]")
    crc_status = md.get("crc_status", {})
    if crc_status.get("csp_crc32_valid") is not None:
        tag = "OK" if crc_status["csp_crc32_valid"] else "FAIL"
        lines.append(f"  {'CRC-32C':<12}0x{crc_status['csp_crc32_rx']:08x} [{tag}]")

    return lines


def _format_gnc_register_lines(reg_name: str, value, unit: str = "") -> list[str]:
    """Render one decoded GNC register (MTQ or NVG) as text-log lines.

    Handles three shapes:
      - bitfield dict with MODE / flag bits (STAT/ACT_ERR/SEN_ERR)
      - BCD dict with `display` key (TIME/DATE)
      - NVG sensor dict (sensor_id, status, values, fields)
      - scalar / list / temperature dict — delegated to str()

    `value` is the structured payload the extractor attached to the
    fragment (identical in shape to the pre-v2 `snap["value"]`). `unit`
    travels on the fragment, populated by the mission extractors from
    the semantic decoder's unit table — no catalog lookup at render time.
    """
    unit_suffix = f" {unit}" if unit else ""
    lines = [f"  {reg_name:<18}— decoded"]

    if is_nvg_sensor(value):
        vals = value.get("values") or []
        fields = value.get("fields") or []
        display = value.get("display", "")
        status = value.get("status")
        lines[0] = f"  {reg_name:<18}{display} (status={status})"
        if fields and len(vals) == len(fields):
            for name, v in zip(fields, vals):
                lines.append(f"    {name:<12}{v}{unit_suffix}")
        else:
            for i, v in enumerate(vals):
                lines.append(f"    v[{i}]        {v}{unit_suffix}")
        return lines

    if is_bcd_display(value):
        lines[0] = f"  {reg_name:<18}{value['display']}"
        return lines

    if is_adcs_tmp(value):
        if value.get("comm_fault"):
            lines[0] = f"  {reg_name:<18}SENSOR FAULT"
        else:
            lines[0] = f"  {reg_name:<18}{value.get('celsius'):.2f} °C (raw={value.get('brdtmp')})"
        return lines

    if is_nvg_heartbeat(value):
        lines[0] = f"  {reg_name:<18}{value['label']} (status={value['status']})"
        return lines

    if is_gnc_mode(value):
        lines[0] = f"  {reg_name:<18}{value['mode_name']} ({value['mode']})"
        return lines

    if is_gnc_counters(value):
        lines[0] = (
            f"  {reg_name:<18}"
            f"reboot={value.get('reboot')}  "
            f"detumble={value.get('detumble')}  "
            f"sunspin={value.get('sunspin')}"
        )
        return lines

    if isinstance(value, dict):
        if "MODE" in value:
            lines[0] = f"  {reg_name:<18}mode={value.get('MODE_NAME')}({value.get('MODE')})"
        flags = [k for k, v in value.items() if v is True]
        if flags:
            lines.append(f"    flags       {', '.join(flags)}")
        return lines

    if isinstance(value, list):
        lines[0] = f"  {reg_name:<18}{', '.join(str(v) for v in value)}{unit_suffix}"
    else:
        lines[0] = f"  {reg_name:<18}{value}{unit_suffix}"
    return lines


def is_unknown_packet(mission_data: dict) -> bool:
    """MAVERIC: a packet is unknown when no command was decoded."""
    return mission_data.get("cmd") is None
