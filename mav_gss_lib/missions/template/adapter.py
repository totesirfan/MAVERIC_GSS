"""
Template Mission Adapter — Minimal implementation of the MissionAdapter protocol.

Copy and modify this for your mission. Each method has a comment explaining
what it does and what you need to change.

See tests/echo_mission.py for another minimal example and
mav_gss_lib/missions/maveric/adapter.py for a full implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from mav_gss_lib.mission_adapter import ParsedPacket


@dataclass
class TemplateMissionAdapter:
    """Minimal adapter — passes raw bytes through without protocol parsing."""

    cmd_defs: dict

    # -- RX path --

    def detect_frame_type(self, meta: dict) -> str:
        """Classify incoming frame from GNU Radio metadata.
        Return a string like 'AX.25', 'ASM+Golay', 'CSP', or 'RAW'."""
        return "RAW"

    def normalize_frame(self, frame_type: str, raw: bytes):
        """Strip outer framing (AX.25/KISS headers, etc).
        Return (inner_payload, stripped_header_hex_or_None, warnings)."""
        return raw, None, []

    def parse_packet(self, inner_payload: bytes, warnings=None):
        """Parse the inner payload into mission-specific fields.
        Return a ParsedPacket with whatever you extracted."""
        return ParsedPacket(warnings=warnings or [])

    def duplicate_fingerprint(self, parsed) -> tuple | None:
        """Return a hashable key for duplicate detection, or None to skip."""
        return None

    def is_uplink_echo(self, cmd) -> bool:
        """Return True if this packet is an echo of our own uplink."""
        return False

    # -- TX path --

    def cmd_line_to_payload(self, line: str) -> dict:
        """Wrap raw CLI text for build_tx_command.

        The platform passes the operator's raw input string. The mission
        interprets the text inside build_tx_command, not here.
        """
        line = line.strip()
        if not line:
            raise ValueError("empty command input")
        return {"line": line}

    def build_tx_command(self, payload):
        """Parse, validate, and encode a transmit command.

        Receives: {"line": "..."} from CLI, or a structured dict from
                  a custom mission builder UI.
        Returns: {raw_cmd: bytes, display: dict, guard: bool}
        """
        line = payload.get("line", "")
        raw = line.encode("ascii")
        return {
            "raw_cmd": raw,
            "display": {
                "title": line.split()[0] if line else "?",
                "subtitle": "",
                "row": {"cmd": line},
                "detail_blocks": [{"kind": "command", "label": "Command", "fields": [
                    {"name": "Input", "value": line},
                ]}],
            },
            "guard": False,
        }

    def tx_queue_columns(self) -> list[dict]:
        """Return column definitions for the TX queue/history list."""
        return [{"id": "cmd", "label": "command", "flex": True}]

    # -- Rendering slots (UI) --

    def packet_list_columns(self) -> list[dict]:
        """Define columns for the RX packet table."""
        return [
            {"id": "num",  "label": "#",    "align": "right", "width": "w-10"},
            {"id": "time", "label": "Time", "width": "w-[72px]"},
            {"id": "size", "label": "Size", "align": "right", "width": "w-12"},
            {"id": "hex",  "label": "Hex",  "flex": True},
        ]

    def packet_list_row(self, pkt) -> dict:
        """Produce column values for one packet row."""
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
        """Produce detail blocks shown when a packet row is expanded."""
        return [
            {"kind": "raw", "label": "Raw Data", "fields": [
                {"name": "Size", "value": str(len(pkt.raw))},
                {"name": "Hex", "value": pkt.raw.hex()},
            ]},
        ]

    def protocol_blocks(self, pkt) -> list:
        """Produce protocol header blocks (CSP, AX.25, etc). Return empty if none."""
        return []

    def integrity_blocks(self, pkt) -> list:
        """Produce integrity check blocks (CRC results). Return empty if none."""
        return []

    # -- Logging --

    def build_log_mission_data(self, pkt) -> dict:
        """Return mission-specific data to include in the JSONL log envelope."""
        return {}

    def format_log_lines(self, pkt) -> list[str]:
        """Return formatted text log lines for this packet."""
        return []

    def is_unknown_packet(self, parsed) -> bool:
        """Return True if the packet could not be parsed into known structure."""
        return True

    # -- Resolution --

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


