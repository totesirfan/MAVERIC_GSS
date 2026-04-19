"""Fake echo mission for testing the mission-agnostic platform boundary.

This is NOT a real mission. It proves that:
  1. A non-MAVERIC adapter can be instantiated
  2. It satisfies the MissionAdapter Protocol
  3. It produces valid rendering data
  4. The platform can exercise it through RxPipeline
"""

from __future__ import annotations

from dataclasses import dataclass

ADAPTER_API_VERSION = 1


@dataclass
class EchoMissionAdapter:
    """Minimal mission adapter that echoes raw bytes without protocol parsing."""

    cmd_defs: dict

    def detect_frame_type(self, meta: dict) -> str:
        return "RAW"

    def normalize_frame(self, frame_type: str, raw: bytes):
        return raw, None, []

    def parse_packet(self, inner_payload: bytes, warnings=None):
        from mav_gss_lib.mission_adapter import ParsedPacket
        return ParsedPacket(warnings=warnings or [])

    def duplicate_fingerprint(self, parsed) -> tuple | None:
        return None

    def is_uplink_echo(self, cmd) -> bool:
        return False

    def build_tx_command(self, payload):
        """Echo mission: encode the raw line as ASCII bytes."""
        line = payload.get("line", "")
        raw = line.encode("ascii")
        return {
            "raw_cmd": raw,
            "display": {
                "title": line.split()[0] if line else "?",
                "subtitle": "",
                "row": {},
                "detail_blocks": [],
            },
            "guard": False,
        }

    # -- Rendering-slot contract --

    def packet_list_columns(self) -> list[dict]:
        return [
            {"id": "num",  "label": "#",     "align": "right", "width": "w-10"},
            {"id": "time", "label": "time",  "width": "w-[72px]"},
            {"id": "size", "label": "size",  "align": "right", "width": "w-12"},
            {"id": "hex",  "label": "hex",   "flex": True},
        ]

    def packet_list_row(self, pkt) -> dict:
        return {
            "values": {
                "num": pkt.pkt_num,
                "time": pkt.gs_ts_short,
                "size": len(pkt.raw),
                "hex": pkt.raw.hex(),
            },
            "_meta": {},
        }

    def packet_detail_blocks(self, pkt) -> list[dict]:
        return [
            {"kind": "raw", "label": "Echo Data", "fields": [
                {"name": "Size", "value": str(len(pkt.raw))},
                {"name": "Hex", "value": pkt.raw.hex()},
            ]},
        ]

    def protocol_blocks(self, pkt) -> list:
        return []

    def integrity_blocks(self, pkt) -> list:
        return []

    def build_log_mission_data(self, pkt) -> dict:
        return {}

    def format_log_lines(self, pkt) -> list[str]:
        return []

    def is_unknown_packet(self, parsed) -> bool:
        return True

    # -- Resolution contract (Phase 11) --

    @property
    def gs_node(self) -> int:
        return 0

    def node_name(self, node_id: int) -> str:
        return str(node_id)

    def ptype_name(self, ptype_id: int) -> str:
        return str(ptype_id)

    def resolve_node(self, s: str) -> int | None:
        try:
            return int(s)
        except ValueError:
            return None

    def resolve_ptype(self, s: str) -> int | None:
        try:
            return int(s)
        except ValueError:
            return None

    def cmd_line_to_payload(self, line: str) -> dict:
        line = line.strip()
        if not line:
            raise ValueError("empty command input")
        return {"line": line}

    def tx_queue_columns(self) -> list[dict]:
        """Return column definitions for the TX queue/history list."""
        return []


# Explicit entry point for shared mission loader
ADAPTER_CLASS = EchoMissionAdapter


def init_mission(cfg: dict) -> dict:
    """Echo mission has no initialization requirements."""
    return {"cmd_defs": {}, "cmd_warn": None}
