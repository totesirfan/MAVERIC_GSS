"""
mav_gss_lib.missions.maveric.adapter -- MAVERIC Mission Adapter

Thin boundary around current MAVERIC protocol behavior.
RX parsing, CRC checks, uplink-echo classification, and TX command
validation/building all pass through here so a future mission has
one obvious replacement seam.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass

from mav_gss_lib.protocols.crc import verify_csp_crc32
from mav_gss_lib.protocols.csp import try_parse_csp_v1
from mav_gss_lib.protocols.frame_detect import detect_frame_type, normalize_frame
from mav_gss_lib.missions.maveric.wire_format import (
    GS_NODE,
    apply_schema,
    build_cmd_raw,
    node_name,
    ptype_name,
    try_parse_command,
    validate_args,
)


# =============================================================================
#  MAVERIC MISSION ADAPTER
# =============================================================================


@dataclass
class MavericMissionAdapter:
    """Thin boundary around current MAVERIC protocol behavior.

    RX parsing, CRC checks, uplink-echo classification, and TX command
    validation/building all pass through here so a future mission has
    one obvious replacement seam.
    """

    cmd_defs: dict

    def detect_frame_type(self, meta) -> str:
        """Classify outer framing from GNU Radio/gr-satellites metadata."""
        return detect_frame_type(meta)

    def normalize_frame(self, frame_type: str, raw: bytes):
        """Strip mission-specific outer framing and return inner payload."""
        return normalize_frame(frame_type, raw)

    def parse_packet(self, inner_payload: bytes, warnings: list[str] | None = None):
        """Parse one normalized RX payload into a mission-neutral result."""
        from mav_gss_lib.mission_adapter import ParsedPacket

        warnings = [] if warnings is None else warnings
        csp, csp_plausible = try_parse_csp_v1(inner_payload)
        if len(inner_payload) <= 4:
            return ParsedPacket(csp=csp, csp_plausible=csp_plausible, warnings=warnings)

        cmd, cmd_tail = try_parse_command(inner_payload[4:])
        ts_result = None
        if cmd:
            apply_schema(cmd, self.cmd_defs)
            if cmd.get("sat_time"):
                ts_result = cmd["sat_time"]

        crc_valid, crc_rx, crc_comp = None, None, None
        if cmd and cmd.get("csp_crc32") is not None:
            crc_valid, crc_rx, crc_comp = verify_csp_crc32(inner_payload)
            if crc_valid is False:
                warnings.append(
                    f"CRC-32C mismatch: rx 0x{crc_rx:08x} != computed 0x{crc_comp:08x}"
                )

        return ParsedPacket(
            csp=csp,
            csp_plausible=csp_plausible,
            cmd=cmd,
            cmd_tail=cmd_tail,
            ts_result=ts_result,
            warnings=warnings,
            crc_status={
                "csp_crc32_valid": crc_valid,
                "csp_crc32_rx": crc_rx,
                "csp_crc32_comp": crc_comp,
            },
        )

    def parse_command(self, inner_payload: bytes):
        """Backward-compatible wrapper around parse_packet()."""
        parsed = self.parse_packet(inner_payload)
        return parsed.cmd, parsed.cmd_tail, parsed.ts_result

    def verify_crc(self, cmd, inner_payload: bytes, warnings: list[str]):
        """Backward-compatible CRC wrapper around parse_packet()."""
        parsed = self.parse_packet(inner_payload, warnings)
        return parsed.crc_status

    def duplicate_fingerprint(self, parsed):
        """Return a mission-specific duplicate fingerprint or None."""
        cmd = parsed.cmd
        if not (cmd and cmd.get("crc") is not None and cmd.get("csp_crc32") is not None):
            return None
        return cmd["crc"], cmd["csp_crc32"]

    def is_uplink_echo(self, cmd) -> bool:
        """Classify whether a decoded command is the ground-station echo."""
        from mav_gss_lib.mission_adapter import ParsedPacket
        cmd_obj = cmd.cmd if isinstance(cmd, ParsedPacket) else cmd
        return bool(cmd_obj and cmd_obj.get("src") == GS_NODE)

    def build_raw_command(self, src, dest, echo, ptype, cmd_id: str, args: str) -> bytes:
        """Build one raw mission command payload for TX."""
        return build_cmd_raw(dest, cmd_id, args, echo=echo, ptype=ptype, origin=src)

    def validate_tx_args(self, cmd_id: str, args: str):
        """Validate TX arguments using the active mission command schema."""
        return validate_args(cmd_id, args, self.cmd_defs)

    def packet_to_json(self, pkt) -> dict:
        """Transitional: convert Packet to the JSON shape the current frontend expects.

        This method will be replaced by the architecture spec's rendering-slot
        contract (packet_list_columns, packet_list_row, etc.) in Phase 5b.
        """
        cmd = pkt.cmd
        args_named = []
        args_extra = []
        if cmd and cmd.get("schema_match") and cmd.get("typed_args"):
            for ta in cmd["typed_args"]:
                val = ta.get("value", "")
                if ta["type"] == "epoch_ms":
                    if hasattr(val, "ms"):
                        val = val.ms
                    elif isinstance(val, dict) and "ms" in val:
                        val = val["ms"]
                if isinstance(val, (bytes, bytearray)):
                    val = val.hex()
                args_named.append({
                    "name": ta["name"],
                    "value": str(val),
                    "important": bool(ta.get("important")),
                })
            args_extra = [
                a.hex() if isinstance(a, (bytes, bytearray)) else str(a)
                for a in cmd.get("extra_args", [])
            ]
        elif cmd:
            raw_args = cmd.get("args", [])
            if isinstance(raw_args, list):
                args_extra = [str(a) for a in raw_args]
            else:
                args_extra = [str(raw_args)] if raw_args else []

        payload = {
            "num": pkt.pkt_num,
            "time": pkt.gs_ts_short,
            "time_utc": pkt.gs_ts,
            "frame": pkt.frame_type,
            "src": node_name(cmd["src"]) if cmd else "",
            "dest": node_name(cmd["dest"]) if cmd else "",
            "echo": node_name(cmd["echo"]) if cmd else "",
            "ptype": ptype_name(cmd["pkt_type"]) if cmd else "",
            "cmd": cmd["cmd_id"] if cmd else "",
            "args_named": args_named,
            "args_extra": args_extra,
            "size": len(pkt.raw),
            "crc16_ok": cmd.get("crc_valid") if cmd else None,
            "crc32_ok": pkt.crc_status.get("csp_crc32_valid"),
            "is_echo": pkt.is_uplink_echo,
            "is_dup": pkt.is_dup,
            "is_unknown": pkt.is_unknown,
            "raw_hex": pkt.raw.hex(),
            "warnings": pkt.warnings,
            "csp_header": pkt.csp,
            "ax25_header": pkt.stripped_hdr,
        }
        if pkt.ts_result:
            dt_utc, dt_local, ms = pkt.ts_result
            payload["sat_time_utc"] = dt_utc.strftime("%H:%M:%S") + " UTC" if dt_utc else None
            payload["sat_time_local"] = dt_local.strftime("%H:%M:%S %Z") if dt_local else None
            payload["sat_time_ms"] = ms
        return payload

    def queue_item_to_json(self, item: dict, match_tx_args, extra_tx_args) -> dict:
        """Transitional: convert TX queue item to the JSON shape the current frontend expects."""
        return {
            "type": "cmd",
            "num": item.get("num", 0),
            "src": node_name(item["src"]),
            "dest": node_name(item["dest"]),
            "echo": node_name(item["echo"]),
            "ptype": ptype_name(item["ptype"]),
            "cmd": item["cmd"],
            "args": item.get("args", ""),
            "args_named": match_tx_args(item["cmd"], item.get("args", "")),
            "args_extra": extra_tx_args(item["cmd"], item.get("args", "")),
            "guard": item.get("guard", False),
            "size": len(item.get("raw_cmd", b"")),
        }

    def history_entry(self, count: int, item: dict, payload_len: int) -> dict:
        """Transitional: build sent-command history entry for the current frontend."""
        from datetime import datetime
        return {
            "n": count,
            "ts": datetime.now().strftime("%H:%M:%S"),
            "src": node_name(item["src"]),
            "dest": node_name(item["dest"]),
            "echo": node_name(item["echo"]),
            "ptype": ptype_name(item["ptype"]),
            "cmd": item["cmd"],
            "args": item.get("args", ""),
            "size": payload_len,
        }

    # -- Rendering-slot contract (architecture spec) --

    def packet_list_columns(self) -> list[dict]:
        """Return column definitions for the RX packet list."""
        return [
            {"id": "num",   "label": "#",         "align": "right", "width": "w-10"},
            {"id": "time",  "label": "time",      "width": "w-[72px]"},
            {"id": "frame", "label": "frame",     "width": "w-[76px]", "toggle": "showFrame"},
            {"id": "src",   "label": "src",       "width": "w-[84px]"},
            {"id": "echo",  "label": "echo",      "width": "w-[84px]", "toggle": "showEcho"},
            {"id": "ptype", "label": "type",       "width": "w-[52px]", "badge": True},
            {"id": "cmd",   "label": "cmd / args", "flex": True},
            {"id": "flags", "label": "",           "width": "w-[76px]", "align": "right"},
            {"id": "size",  "label": "size",       "align": "right", "width": "w-12"},
        ]

    def packet_list_row(self, pkt) -> dict:
        """Return row values keyed by column ID for one packet."""
        cmd = pkt.cmd
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
                "src": node_name(cmd["src"]) if cmd else "",
                "echo": node_name(cmd["echo"]) if cmd else "",
                "ptype": ptype_name(cmd["pkt_type"]) if cmd else "",
                "cmd": ((cmd["cmd_id"] + " " + args_str).strip() if args_str else cmd["cmd_id"]) if cmd else "",
                "flags": flags,
                "size": len(pkt.raw),
            },
            "_meta": {"opacity": 0.5 if pkt.is_unknown else 1.0},
        }

    def protocol_blocks(self, pkt) -> list:
        """Return protocol/wrapper blocks for the detail view."""
        from mav_gss_lib.mission_adapter import ProtocolBlock
        blocks = []
        if pkt.csp:
            blocks.append(ProtocolBlock(
                kind="csp",
                label="CSP V1",
                fields=[{"name": k.capitalize(), "value": str(v)} for k, v in pkt.csp.items()],
            ))
        if pkt.stripped_hdr:
            blocks.append(ProtocolBlock(
                kind="ax25",
                label="AX.25",
                fields=[{"name": "Header", "value": pkt.stripped_hdr}],
            ))
        return blocks

    def integrity_blocks(self, pkt) -> list:
        """Return integrity check blocks for the detail view."""
        from mav_gss_lib.mission_adapter import IntegrityBlock
        blocks = []
        cmd = pkt.cmd
        if cmd and cmd.get("crc") is not None:
            blocks.append(IntegrityBlock(
                kind="crc16",
                label="CRC-16",
                scope="command",
                ok=cmd.get("crc_valid"),
                received=f"0x{cmd['crc']:04X}" if cmd.get("crc") is not None else None,
            ))
        crc_status = pkt.crc_status
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

    def packet_detail_blocks(self, pkt) -> list[dict]:
        """Return mission-specific semantic blocks for the detail view."""
        cmd = pkt.cmd
        blocks = []

        time_block = {"kind": "time", "label": "Time", "fields": [
            {"name": "GS Time", "value": pkt.gs_ts},
        ]}
        if pkt.ts_result:
            dt_utc, dt_local, ms = pkt.ts_result
            if dt_utc:
                time_block["fields"].append({"name": "SAT UTC", "value": dt_utc.strftime("%H:%M:%S") + " UTC"})
            if dt_local:
                time_block["fields"].append({"name": "SAT Local", "value": dt_local.strftime("%H:%M:%S %Z")})
        blocks.append(time_block)

        if cmd:
            blocks.append({"kind": "routing", "label": "Routing", "fields": [
                {"name": "Src", "value": node_name(cmd["src"])},
                {"name": "Dest", "value": node_name(cmd["dest"])},
                {"name": "Echo", "value": node_name(cmd["echo"])},
                {"name": "Type", "value": ptype_name(cmd["pkt_type"])},
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
