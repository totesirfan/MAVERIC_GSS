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
    node_name as _wire_node_name,
    ptype_name as _wire_ptype_name,
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

    # Identifies the frontend builder component registered in missions/registry.ts.
    # Presence of this attribute signals that a custom TX input UI is available.
    tx_builder_id: str = "maveric"

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
            return ParsedPacket(
                mission_data={"csp": csp, "csp_plausible": csp_plausible},
                warnings=warnings,
            )

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

        mission_data = {
            "csp": csp, "csp_plausible": csp_plausible,
            "cmd": cmd, "cmd_tail": cmd_tail,
            "ts_result": ts_result,
            "crc_status": {
                "csp_crc32_valid": crc_valid,
                "csp_crc32_rx": crc_rx,
                "csp_crc32_comp": crc_comp,
            },
        }
        return ParsedPacket(
            mission_data=mission_data,
            warnings=warnings,
        )

    @staticmethod
    def _md(pkt) -> dict:
        """Read mission data from a packet."""
        return getattr(pkt, "mission_data", {}) or {}

    def duplicate_fingerprint(self, parsed):
        """Return a mission-specific duplicate fingerprint or None."""
        md = self._md(parsed)
        cmd = md.get("cmd")
        if not (cmd and cmd.get("crc") is not None and cmd.get("csp_crc32") is not None):
            return None
        return cmd["crc"], cmd["csp_crc32"]

    def is_uplink_echo(self, cmd) -> bool:
        """Classify whether a decoded command is the ground-station echo."""
        from mav_gss_lib.mission_adapter import ParsedPacket
        cmd_obj = self._md(cmd).get("cmd") if isinstance(cmd, ParsedPacket) else cmd
        return bool(cmd_obj and cmd_obj.get("src") == GS_NODE)

    def build_raw_command(self, src, dest, echo, ptype, cmd_id: str, args: str) -> bytes:
        """Build one raw mission command payload for TX."""
        return build_cmd_raw(dest, cmd_id, args, echo=echo, ptype=ptype, origin=src)

    def validate_tx_args(self, cmd_id: str, args: str):
        """Validate TX arguments using the active mission command schema."""
        return validate_args(cmd_id, args, self.cmd_defs)

    def build_tx_command(self, payload):
        """Build a mission command from structured input.

        Accepts: {cmd_id, args: str | {name: value, ...}, src?, dest, echo, ptype, guard?}
        - args as a flat string: CLI path — positional tokens matched to tx_args schema
        - args as a dict: mission builder path — {name: value} mapping
        - src (optional): override source node; defaults to GS_NODE
        Returns: {raw_cmd: bytes, display: dict, guard: bool}
        Raises ValueError on validation failure.
        """
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")
        cmd_id = str(payload.get("cmd_id", "")).lower()
        args_input = payload.get("args", {})
        dest_name = str(payload.get("dest", ""))
        echo_name = str(payload.get("echo", "NONE"))
        ptype_name = str(payload.get("ptype", "CMD"))

        from mav_gss_lib.missions.maveric.wire_format import (
            resolve_node, resolve_ptype,
            node_name as _node_name, ptype_name as _ptype_name,
        )

        # Resolve src: explicit payload value overrides GS_NODE default
        src_name = str(payload.get("src", ""))
        if src_name:
            src = resolve_node(src_name)
            if src is None:
                raise ValueError(f"unknown source node '{src_name}'")
        else:
            src = GS_NODE

        dest = resolve_node(dest_name)
        if dest is None:
            raise ValueError(f"unknown destination node '{dest_name}'")
        echo = resolve_node(echo_name)
        if echo is None:
            raise ValueError(f"unknown echo node '{echo_name}'")
        ptype = resolve_ptype(ptype_name)
        if ptype is None:
            raise ValueError(f"unknown packet type '{ptype_name}'")

        if self.cmd_defs and cmd_id not in self.cmd_defs:
            raise ValueError(f"'{cmd_id}' not in schema")
        defn = self.cmd_defs.get(cmd_id, {})
        if defn.get("rx_only"):
            raise ValueError(f"'{cmd_id}' is receive-only")
        allowed_nodes = defn.get("nodes", [])
        if allowed_nodes and dest_name not in allowed_nodes:
            raise ValueError(f"'{cmd_id}' not valid for node '{dest_name}' (allowed: {', '.join(allowed_nodes)})")

        tx_args_schema = defn.get("tx_args", [])

        # Normalize args_input to args_str (wire) and args_dict (display)
        if isinstance(args_input, str):
            # CLI path: flat string goes to wire directly; split for display matching
            args_str = args_input
            tokens = args_str.split() if args_str.strip() else []
            args_dict = {}
            for i, arg_def in enumerate(tx_args_schema):
                if i < len(tokens):
                    args_dict[arg_def["name"]] = tokens[i]
            extra_tokens = tokens[len(tx_args_schema):]
        else:
            # Mission builder path: reconstruct args_str from dict
            if not isinstance(args_input, dict):
                raise ValueError("args must be a str or dict")
            args_dict = args_input
            args_parts = []
            for arg_def in tx_args_schema:
                val = args_dict.get(arg_def["name"], "")
                if val:
                    args_parts.append(str(val))
            args_str = " ".join(args_parts)
            extra_tokens = []

        valid, issues = validate_args(cmd_id, args_str, self.cmd_defs)
        if not valid:
            raise ValueError("; ".join(issues))

        raw_cmd = bytes(build_cmd_raw(dest, cmd_id, args_str, echo=echo, ptype=ptype, origin=src))

        guard = payload.get("guard", defn.get("guard", False))

        row = {
            "src": _node_name(src),
            "dest": _node_name(dest),
            "echo": _node_name(echo),
            "ptype": _ptype_name(ptype),
            "cmd": (f"{cmd_id} {args_str}".strip() if args_str else cmd_id),
        }

        routing_block = {"kind": "routing", "label": "Routing", "fields": [
            {"name": "Src", "value": _node_name(src)},
            {"name": "Dest", "value": _node_name(dest)},
            {"name": "Echo", "value": _node_name(echo)},
            {"name": "Type", "value": _ptype_name(ptype)},
        ]}

        args_fields = []
        for arg_def in tx_args_schema:
            val = args_dict.get(arg_def["name"], "")
            if val:
                args_fields.append({"name": arg_def["name"], "value": str(val)})
        if isinstance(args_input, str):
            parts = args_str.split() if args_str else []
            for i, extra in enumerate(parts[len(tx_args_schema):]):
                args_fields.append({"name": f"arg{len(tx_args_schema) + i}", "value": extra})

        detail_blocks = [routing_block]
        if args_fields:
            detail_blocks.append({"kind": "args", "label": "Arguments", "fields": args_fields})

        display = {
            "title": cmd_id,
            "subtitle": f"{_node_name(src)} \u2192 {_node_name(dest)}",
            "row": row,
            "detail_blocks": detail_blocks,
        }

        return {"raw_cmd": raw_cmd, "display": display, "guard": guard}

    # =========================================================================
    #  Adapter boundary
    #
    #  This adapter implements the MissionAdapter protocol defined in
    #  mav_gss_lib/mission_adapter.py. The platform calls these methods
    #  without knowing which mission is active.
    #
    #  RX: detect_frame_type → normalize_frame → parse_packet
    #  TX: cmd_line_to_payload, build_tx_command, tx_queue_columns
    #  UI: packet_list_columns/row, packet_detail_blocks, protocol/integrity
    #  Log: build_log_mission_data, format_log_lines, is_unknown_packet
    #  Resolution: gs_node, node_name, ptype_name, resolve_node, resolve_ptype
    # =========================================================================

    # -- Rendering-slot contract (architecture spec) --

    def packet_list_columns(self) -> list[dict]:
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

    def packet_list_row(self, pkt) -> dict:
        """Return row values keyed by column ID for one packet."""
        md = self._md(pkt)
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
                "src": _wire_node_name(cmd["src"]) if cmd else "",
                "echo": _wire_node_name(cmd["echo"]) if cmd else "",
                "ptype": _wire_ptype_name(cmd["pkt_type"]) if cmd else "",
                "cmd": ((cmd["cmd_id"] + " " + args_str).strip() if args_str else cmd["cmd_id"]) if cmd else "",
                "flags": flags,
                "size": len(pkt.raw),
            },
            "_meta": {"opacity": 0.5 if pkt.is_unknown else 1.0},
        }

    def protocol_blocks(self, pkt) -> list:
        """Return protocol/wrapper blocks for the detail view."""
        from mav_gss_lib.mission_adapter import ProtocolBlock
        from mav_gss_lib.protocols.ax25 import ax25_decode_header
        md = self._md(pkt)
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

    def integrity_blocks(self, pkt) -> list:
        """Return integrity check blocks for the detail view."""
        from mav_gss_lib.mission_adapter import IntegrityBlock
        md = self._md(pkt)
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

    def packet_detail_blocks(self, pkt) -> list[dict]:
        """Return mission-specific semantic blocks for the detail view."""
        md = self._md(pkt)
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
                {"name": "Src", "value": _wire_node_name(cmd["src"])},
                {"name": "Dest", "value": _wire_node_name(cmd["dest"])},
                {"name": "Echo", "value": _wire_node_name(cmd["echo"])},
                {"name": "Type", "value": _wire_ptype_name(cmd["pkt_type"])},
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

    # -- Logging-slot contract --

    def build_log_mission_data(self, pkt) -> dict:
        """Return MAVERIC-specific fields for the JSONL log mission block.

        This produces the same fields that were previously inlined in
        build_rx_log_record(), but scoped under a 'mission' key in the
        platform envelope.
        """
        md = self._md(pkt)
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

    def format_log_lines(self, pkt) -> list[str]:
        """Return MAVERIC-specific text log lines for one packet.

        Platform handles: separator, warnings, hex dump, ASCII.
        Adapter handles: AX.25 header, CSP header, satellite time,
        command routing/args, CRC display.
        """
        from mav_gss_lib.missions.maveric.wire_format import format_arg_value

        md = self._md(pkt)
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
                f"Src:{_wire_node_name(cmd['src'])}  Dest:{_wire_node_name(cmd['dest'])}  "
                f"Echo:{_wire_node_name(cmd['echo'])}  Type:{_wire_ptype_name(cmd['pkt_type'])}")
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

    def is_unknown_packet(self, parsed) -> bool:
        """MAVERIC: a packet is unknown when no command was decoded."""
        cmd = self._md(parsed).get("cmd")
        return cmd is None

    # -- Resolution contract --

    @property
    def gs_node(self) -> int:
        return GS_NODE

    def node_name(self, node_id: int) -> str:
        return _wire_node_name(node_id)

    def ptype_name(self, ptype_id: int) -> str:
        return _wire_ptype_name(ptype_id)

    def node_label(self, node_id: int) -> str:
        from mav_gss_lib.missions.maveric.wire_format import node_label
        return node_label(node_id)

    def ptype_label(self, ptype_id: int) -> str:
        from mav_gss_lib.missions.maveric.wire_format import ptype_label
        return ptype_label(ptype_id)

    def resolve_node(self, s: str) -> int | None:
        from mav_gss_lib.missions.maveric.wire_format import resolve_node
        return resolve_node(s)

    def resolve_ptype(self, s: str) -> int | None:
        from mav_gss_lib.missions.maveric.wire_format import resolve_ptype
        return resolve_ptype(s)

    def parse_cmd_line(self, line: str) -> tuple:
        from mav_gss_lib.missions.maveric.wire_format import parse_cmd_line
        return parse_cmd_line(line)

    def tx_queue_columns(self) -> list[dict]:
        """Return column definitions for the TX queue/history list."""
        return [
            {"id": "src",   "label": "src",       "width": "w-[52px]", "hide_if_all": ["GS"]},
            {"id": "dest",  "label": "dest",      "width": "w-[52px]"},
            {"id": "echo",  "label": "echo",      "width": "w-[52px]", "hide_if_all": ["NONE"]},
            {"id": "ptype", "label": "type",      "width": "w-[52px]", "badge": True},
            {"id": "cmd",   "label": "id / args", "flex": True},
        ]

    def cmd_line_to_payload(self, line: str) -> dict:
        """Convert raw CLI text to a payload dict for build_tx_command.

        Handles two input formats:
        - Shortcut: CMD_ID [ARGS]  (when cmd_id has routing defaults in schema)
        - Full:     [SRC] DEST ECHO TYPE CMD_ID [ARGS]

        Returns: {cmd_id, args, dest, echo, ptype[, src]} for build_tx_command.
        Only includes 'src' when explicitly provided in full format.
        Raises ValueError on parse failure or unknown command.
        """
        line = line.strip()
        if not line:
            raise ValueError("empty command input")

        parts = line.split()
        candidate = parts[0].lower()
        defn = self.cmd_defs.get(candidate)

        if defn and not defn.get("rx_only") and defn.get("dest") is not None:
            # Shortcut path: cmd_id [args...]
            args = " ".join(parts[1:])
            return {
                "cmd_id": candidate,
                "args": args,
                "dest": _wire_node_name(defn["dest"]),
                "echo": _wire_node_name(defn["echo"]),
                "ptype": _wire_ptype_name(defn["ptype"]),
            }

        # Full parse path: [SRC] DEST ECHO TYPE CMD [ARGS]
        src, dest, echo, ptype, cmd_id, args = self.parse_cmd_line(line)
        result = {
            "cmd_id": cmd_id,
            "args": args,
            "dest": _wire_node_name(dest),
            "echo": _wire_node_name(echo),
            "ptype": _wire_ptype_name(ptype),
        }
        # Include explicit src only when it differs from GS_NODE
        if src != GS_NODE:
            result["src"] = _wire_node_name(src)
        return result
