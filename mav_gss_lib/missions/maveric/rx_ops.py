"""
mav_gss_lib.missions.maveric.rx_ops -- MAVERIC RX parsing helpers

Extracted RX operations from MavericMissionAdapter. The adapter delegates
to these functions; the platform never imports this module directly.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from mav_gss_lib.protocols.crc import verify_csp_crc32
from mav_gss_lib.protocols.csp import try_parse_csp_v1
from mav_gss_lib.protocols.frame_detect import detect_frame_type, normalize_frame
from mav_gss_lib.missions.maveric.wire_format import try_parse_command
from mav_gss_lib.missions.maveric.schema import enrich_cmd_in_place
from mav_gss_lib.missions.maveric.telemetry import decode_telemetry
from mav_gss_lib.missions.maveric.telemetry.gnc_registers import decode_from_cmd as _decode_gnc_registers


def detect(meta) -> str:
    """Classify outer framing from GNU Radio/gr-satellites metadata."""
    return detect_frame_type(meta)


def normalize(frame_type: str, raw: bytes):
    """Strip mission-specific outer framing and return inner payload."""
    return normalize_frame(frame_type, raw)


def parse_packet(inner_payload: bytes, cmd_defs: dict, warnings: list[str] | None = None):
    """Parse one normalized RX payload into a mission-neutral result."""
    from mav_gss_lib.mission_adapter import ParsedPacket

    warnings = [] if warnings is None else warnings
    csp, csp_plausible = try_parse_csp_v1(inner_payload)
    if len(inner_payload) <= 4:
        return ParsedPacket(
            mission_data={"csp": csp, "csp_plausible": csp_plausible},
            warnings=warnings,
        )

    cmd, cmd_tail = try_parse_command(inner_payload[4:])
    ts_result = None
    if cmd:
        enrich_cmd_in_place(cmd, cmd_defs)
        if cmd.get("sat_time"):
            ts_result = cmd["sat_time"]

    crc_valid, crc_rx, crc_comp = None, None, None
    if cmd and cmd.get("csp_crc32") is not None:
        crc_valid, crc_rx, crc_comp = verify_csp_crc32(inner_payload)
        if crc_valid is False:
            warnings.append(
                f"CRC-32C mismatch: rx 0x{crc_rx:08x} != computed 0x{crc_comp:08x}"
            )

    telemetry = None
    if cmd:
        try:
            telemetry = decode_telemetry(cmd)
        except ValueError as e:
            warnings.append(f"telemetry decode failed: {e}")

    gnc_registers = None
    if cmd:
        try:
            gnc_registers = _decode_gnc_registers(cmd)
        except (ValueError, TypeError, KeyError) as e:
            warnings.append(f"gnc register decode failed: {e}")

    mission_data = {
        "csp": csp, "csp_plausible": csp_plausible,
        "cmd": cmd, "cmd_tail": cmd_tail,
        "ts_result": ts_result,
        "crc_status": {
            "csp_crc32_valid": crc_valid,
            "csp_crc32_rx": crc_rx,
            "csp_crc32_comp": crc_comp,
        },
        "telemetry": telemetry,
        "gnc_registers": gnc_registers,
    }
    return ParsedPacket(
        mission_data=mission_data,
        warnings=warnings,
    )


def duplicate_fingerprint(mission_data: dict):
    """Return a mission-specific duplicate fingerprint or None.

    Takes a mission_data dict (not a ParsedPacket).
    """
    cmd = mission_data.get("cmd")
    if not (cmd and cmd.get("crc") is not None and cmd.get("csp_crc32") is not None):
        return None
    return cmd["crc"], cmd["csp_crc32"]


def is_uplink_echo(mission_data: dict, gs_node: int) -> bool:
    """Classify whether a decoded command is the ground-station echo.

    Args:
        mission_data: dict (not a ParsedPacket)
        gs_node: ground station node ID (from NodeTable.gs_node)
    """
    cmd_obj = mission_data.get("cmd")
    return bool(cmd_obj and cmd_obj.get("src") == gs_node)
