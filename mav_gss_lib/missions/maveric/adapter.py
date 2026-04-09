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

from mav_gss_lib.missions.maveric import rendering as _rendering, rx_ops, tx_ops
from mav_gss_lib.missions.maveric import log_format as _log_format
from mav_gss_lib.missions.maveric.nodes import NodeTable


# =============================================================================
#  MAVERIC MISSION ADAPTER
# =============================================================================


@dataclass
class MavericMissionAdapter:
    """Thin boundary around current MAVERIC protocol behavior.

    Owns explicit references to all mission state: cmd_defs, nodes,
    and image_assembler. No module globals.
    """

    cmd_defs: dict
    nodes: NodeTable
    image_assembler: object = None

    def detect_frame_type(self, meta) -> str:
        return rx_ops.detect(meta)

    def normalize_frame(self, frame_type: str, raw: bytes):
        return rx_ops.normalize(frame_type, raw)

    def parse_packet(self, inner_payload: bytes, warnings: list[str] | None = None):
        return rx_ops.parse_packet(inner_payload, self.cmd_defs, warnings)

    @staticmethod
    def _md(pkt) -> dict:
        return getattr(pkt, "mission_data", {}) or {}

    def duplicate_fingerprint(self, parsed):
        return rx_ops.duplicate_fingerprint(self._md(parsed))

    def is_uplink_echo(self, cmd) -> bool:
        from mav_gss_lib.mission_adapter import ParsedPacket
        md = self._md(cmd) if isinstance(cmd, ParsedPacket) else {"cmd": cmd}
        return rx_ops.is_uplink_echo(md, self.nodes.gs_node)

    def build_raw_command(self, src, dest, echo, ptype, cmd_id: str, args: str) -> bytes:
        return tx_ops.build_raw_command(src, dest, echo, ptype, cmd_id, args)

    def validate_tx_args(self, cmd_id: str, args: str):
        return tx_ops.validate_tx_args(cmd_id, args, self.cmd_defs)

    def build_tx_command(self, payload):
        """Build a mission command from structured input.

        Accepts: {cmd_id, args: str | {name: value, ...}, src?, dest, echo, ptype, guard?}
        Returns: {raw_cmd: bytes, display: dict, guard: bool}
        Raises ValueError on validation failure.
        """
        return tx_ops.build_tx_command(payload, self.cmd_defs, self.nodes)

    # -- Rendering-slot contract --

    def packet_list_columns(self): return _rendering.packet_list_columns()
    def packet_list_row(self, pkt): return _rendering.packet_list_row(pkt, self.nodes)
    def protocol_blocks(self, pkt): return _rendering.protocol_blocks(pkt)
    def integrity_blocks(self, pkt): return _rendering.integrity_blocks(pkt)
    def packet_detail_blocks(self, pkt): return _rendering.packet_detail_blocks(pkt, self.nodes)

    # -- Logging-slot contract --

    def build_log_mission_data(self, pkt) -> dict:
        return _log_format.build_log_mission_data(pkt)

    def format_log_lines(self, pkt) -> list[str]:
        return _log_format.format_log_lines(pkt, self.nodes)

    def is_unknown_packet(self, parsed) -> bool:
        return _log_format.is_unknown_packet(self._md(parsed))

    # -- Resolution contract --

    @property
    def gs_node(self) -> int:
        return self.nodes.gs_node

    def node_name(self, node_id: int) -> str:
        return self.nodes.node_name(node_id)

    def ptype_name(self, ptype_id: int) -> str:
        return self.nodes.ptype_name(ptype_id)

    def node_label(self, node_id: int) -> str:
        return self.nodes.node_label(node_id)

    def ptype_label(self, ptype_id: int) -> str:
        return self.nodes.ptype_label(ptype_id)

    def resolve_node(self, s: str) -> int | None:
        return self.nodes.resolve_node(s)

    def resolve_ptype(self, s: str) -> int | None:
        return self.nodes.resolve_ptype(s)

    def parse_cmd_line(self, line: str) -> tuple:
        from mav_gss_lib.missions.maveric.cmd_parser import parse_cmd_line
        return parse_cmd_line(line, self.nodes)

    def tx_queue_columns(self): return _rendering.tx_queue_columns()

    def cmd_line_to_payload(self, line: str) -> dict:
        """Convert raw CLI text to a payload dict for build_tx_command."""
        return tx_ops.cmd_line_to_payload(line, self.cmd_defs, self.nodes)

    # -- Plugin hook --

    def on_packet_received(self, pkt) -> list[dict] | None:
        """Feed image chunks to the assembler and return progress messages."""
        if not self.image_assembler:
            return None
        md = self._md(pkt)
        cmd = md.get("cmd")
        if not cmd:
            return None

        cmd_id = cmd.get("cmd_id", "")
        if cmd_id not in ("img_cnt_chunks", "img_get_chunk"):
            return None

        if cmd.get("schema_match") and cmd.get("typed_args"):
            args_by_name = {ta["name"]: ta.get("value", "") for ta in cmd["typed_args"]}
        else:
            return None

        filename = str(args_by_name.get("Filename", ""))
        if not filename:
            return None

        if cmd_id == "img_cnt_chunks":
            count = args_by_name.get("Num Chunks", "")
            try:
                self.image_assembler.set_total(filename, int(count))
            except (ValueError, TypeError):
                return None
        elif cmd_id == "img_get_chunk":
            chunk_num = args_by_name.get("Chunk Number", "")
            chunk_size = args_by_name.get("Chunk Size", None)
            data = args_by_name.get("Data", b"")
            if isinstance(data, str):
                try:
                    data = bytes.fromhex(data)
                except ValueError:
                    data = data.encode()
            try:
                self.image_assembler.feed_chunk(filename, int(chunk_num), data, chunk_size=chunk_size)
            except (ValueError, TypeError):
                return None

        received, total = self.image_assembler.progress(filename)
        return [{
            "type": "imaging_progress",
            "filename": filename,
            "received": received,
            "total": total,
            "complete": self.image_assembler.is_complete(filename),
        }]
