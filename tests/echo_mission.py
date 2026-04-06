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

    def build_raw_command(self, src, dest, echo, ptype, cmd_id, args):
        return f"{cmd_id} {args}".encode("ascii")

    def validate_tx_args(self, cmd_id, args):
        return True, []

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

    # -- Transitional compatibility (Phase 5a) --

    def packet_to_json(self, pkt) -> dict:
        return {
            "num": pkt.pkt_num,
            "time": pkt.gs_ts_short,
            "time_utc": pkt.gs_ts,
            "frame": "RAW",
            "src": "", "dest": "", "echo": "", "ptype": "",
            "cmd": "", "args_named": [], "args_extra": [],
            "size": len(pkt.raw),
            "crc16_ok": None, "crc32_ok": None,
            "is_echo": False, "is_dup": pkt.is_dup,
            "is_unknown": True,
            "raw_hex": pkt.raw.hex(),
            "warnings": pkt.warnings,
            "csp_header": None, "ax25_header": None,
            "_rendering": {
                "row": self.packet_list_row(pkt),
                "detail_blocks": self.packet_detail_blocks(pkt),
                "protocol_blocks": [],
                "integrity_blocks": [],
            },
        }

    def queue_item_to_json(self, item, match_tx_args, extra_tx_args):
        return {
            "type": "cmd",
            "num": item.get("num", 0),
            "src": "", "dest": "", "echo": "", "ptype": "",
            "cmd": item.get("cmd", ""),
            "args": item.get("args", ""),
            "args_named": [], "args_extra": [],
            "guard": item.get("guard", False),
            "size": len(item.get("raw_cmd", b"")),
        }

    def history_entry(self, count, item, payload_len):
        from datetime import datetime
        return {
            "n": count,
            "ts": datetime.now().strftime("%H:%M:%S"),
            "src": "", "dest": "", "echo": "", "ptype": "",
            "cmd": item.get("cmd", ""),
            "args": item.get("args", ""),
            "size": payload_len,
        }


# Explicit entry point for shared mission loader
ADAPTER_CLASS = EchoMissionAdapter
