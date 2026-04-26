"""MAVERIC RX parsing helpers.

Mission-owned RX operations consumed by `MavericPacketOps` — frame
detection, payload normalization, command parsing, duplicate/echo
classification.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mav_gss_lib.platform.framing.crc import verify_csp_crc32
from mav_gss_lib.platform.framing.csp_v1 import try_parse_csp_v1
from mav_gss_lib.platform.rx.frame_detect import detect_frame_type, normalize_frame
from mav_gss_lib.missions.maveric.wire_format import try_parse_command
from mav_gss_lib.missions.maveric.schema import enrich_cmd_in_place


@dataclass(frozen=True, slots=True)
class MavericParseResult:
    mission_data: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def detect(meta: dict[str, Any]) -> str:
    """Classify outer framing from GNU Radio/gr-satellites metadata."""
    return detect_frame_type(meta)


def normalize(frame_type: str, raw: bytes) -> tuple[bytes, str, list[str]]:
    """Strip mission-specific outer framing and return inner payload."""
    return normalize_frame(frame_type, raw)


def parse_packet(
    inner_payload: bytes,
    cmd_defs: dict[str, Any],
    warnings: list[str] | None = None,
) -> MavericParseResult:
    """Parse one normalized RX payload into a MAVERIC parse result."""

    warnings = [] if warnings is None else warnings
    csp, csp_plausible = try_parse_csp_v1(inner_payload)
    if len(inner_payload) <= 4:
        return MavericParseResult(
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

    mission_data = {
        "csp": csp, "csp_plausible": csp_plausible,
        "cmd": cmd, "cmd_tail": cmd_tail,
        "ptype": cmd["pkt_type"] if cmd else None,
        "ts_result": ts_result,
        "crc_status": {
            "csp_crc32_valid": crc_valid,
            "csp_crc32_rx": crc_rx,
            "csp_crc32_comp": crc_comp,
        },
    }
    return MavericParseResult(
        mission_data=mission_data,
        warnings=warnings,
    )


def duplicate_fingerprint(mission_data: dict[str, Any]) -> tuple[int, int] | None:
    """Return a mission-specific duplicate fingerprint or None.

    Takes a mission_data dict.
    """
    cmd = mission_data.get("cmd")
    if not (cmd and cmd.get("crc") is not None and cmd.get("csp_crc32") is not None):
        return None
    return cmd["crc"], cmd["csp_crc32"]


def is_uplink_echo(mission_data: dict, gs_node: int) -> bool:
    """Classify whether a decoded command is the ground-station echo.

    Args:
        mission_data: parsed mission payload dict
        gs_node: ground station node ID (from NodeTable.gs_node)
    """
    cmd_obj = mission_data.get("cmd")
    return bool(cmd_obj and cmd_obj.get("src") == gs_node)
