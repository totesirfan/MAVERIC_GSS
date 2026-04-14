"""
mav_gss_lib.missions.maveric.tx_ops -- MAVERIC TX Command Building

All functions receive cmd_defs and/or nodes explicitly — no module globals.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mav_gss_lib.missions.maveric.wire_format import build_cmd_raw
from mav_gss_lib.missions.maveric.schema import validate_args
from mav_gss_lib.missions.maveric.cmd_parser import parse_cmd_line

if TYPE_CHECKING:
    from mav_gss_lib.missions.maveric.nodes import NodeTable


def build_raw_command(src, dest, echo, ptype, cmd_id: str, args: str) -> bytes:
    """Build one raw mission command payload for TX."""
    return build_cmd_raw(src, dest, cmd_id, args, echo=echo, ptype=ptype)


def validate_tx_args(cmd_id: str, args: str, cmd_defs: dict):
    """Validate TX arguments using the active mission command schema."""
    return validate_args(cmd_id, args, cmd_defs)


def build_tx_command(payload, cmd_defs: dict, nodes: NodeTable):
    """Build a mission command from structured input.

    Accepts: {cmd_id, args: str | {name: value, ...}, src?, dest, echo, ptype, guard?}
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

    # Resolve src: explicit payload value overrides gs_node default
    src_name = str(payload.get("src", ""))
    if src_name:
        src = nodes.resolve_node(src_name)
        if src is None:
            raise ValueError(f"unknown source node '{src_name}'")
    else:
        src = nodes.gs_node

    dest = nodes.resolve_node(dest_name)
    if dest is None:
        raise ValueError(f"unknown destination node '{dest_name}'")
    echo = nodes.resolve_node(echo_name)
    if echo is None:
        raise ValueError(f"unknown echo node '{echo_name}'")
    ptype = nodes.resolve_ptype(ptype_name)
    if ptype is None:
        raise ValueError(f"unknown packet type '{ptype_name}'")

    if cmd_defs and cmd_id not in cmd_defs:
        raise ValueError(f"'{cmd_id}' not in schema")
    defn = cmd_defs.get(cmd_id, {})
    if defn.get("rx_only"):
        raise ValueError(f"'{cmd_id}' is receive-only")
    allowed_nodes = defn.get("nodes", [])
    if allowed_nodes and dest_name not in allowed_nodes:
        raise ValueError(f"'{cmd_id}' not valid for node '{dest_name}' (allowed: {', '.join(allowed_nodes)})")

    tx_args_schema = defn.get("tx_args", [])

    # Normalize args_input to args_str (wire) and args_dict (display)
    if isinstance(args_input, str):
        args_str = args_input
        tokens = args_str.split() if args_str.strip() else []
        args_dict = {}
        for i, arg_def in enumerate(tx_args_schema):
            if i < len(tokens):
                args_dict[arg_def["name"]] = tokens[i]
        extra_tokens = tokens[len(tx_args_schema):]
    else:
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

    valid, issues = validate_args(cmd_id, args_str, cmd_defs)
    if not valid:
        raise ValueError("; ".join(issues))

    raw_cmd = bytes(build_cmd_raw(src, dest, cmd_id, args_str, echo=echo, ptype=ptype))

    guard = payload.get("guard", defn.get("guard", False))

    row = {
        "src": nodes.node_name(src),
        "dest": nodes.node_name(dest),
        "echo": nodes.node_name(echo),
        "ptype": nodes.ptype_name(ptype),
        "cmd": (f"{cmd_id} {args_str}".strip() if args_str else cmd_id),
    }

    routing_block = {"kind": "routing", "label": "Routing", "fields": [
        {"name": "Src", "value": nodes.node_name(src)},
        {"name": "Dest", "value": nodes.node_name(dest)},
        {"name": "Echo", "value": nodes.node_name(echo)},
        {"name": "Type", "value": nodes.ptype_name(ptype)},
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
        "subtitle": nodes.node_name(dest),
        "row": row,
        "detail_blocks": detail_blocks,
    }

    return {"raw_cmd": raw_cmd, "display": display, "guard": guard}


def cmd_line_to_payload(line: str, cmd_defs: dict, nodes: NodeTable) -> dict:
    """Convert raw CLI text to a payload dict for build_tx_command.

    Handles two input formats:
    - Shortcut: CMD_ID [ARGS]  (when cmd_id has routing defaults in schema)
    - Full:     [SRC] DEST ECHO TYPE CMD_ID [ARGS]
    """
    line = line.strip()
    if not line:
        raise ValueError("empty command input")

    parts = line.split()
    candidate = parts[0].lower()
    defn = cmd_defs.get(candidate)

    if defn and not defn.get("rx_only") and defn.get("dest") is not None:
        args = " ".join(parts[1:])
        return {
            "cmd_id": candidate,
            "args": args,
            "dest": nodes.node_name(defn["dest"]),
            "echo": nodes.node_name(defn["echo"]),
            "ptype": nodes.ptype_name(defn["ptype"]),
        }

    # Full parse path
    src, dest, echo, ptype, cmd_id, args = parse_cmd_line(line, nodes)
    result = {
        "cmd_id": cmd_id,
        "args": args,
        "dest": nodes.node_name(dest),
        "echo": nodes.node_name(echo),
        "ptype": nodes.ptype_name(ptype),
    }
    if src != nodes.gs_node:
        result["src"] = nodes.node_name(src)
    return result
