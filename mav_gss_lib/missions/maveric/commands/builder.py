"""MAVERIC TX command building.

Consumed by `MavericCommandOps` — turns a validated mission payload dict
into `raw_cmd` bytes plus the mission-opaque `display` metadata the UI
renders. Operator-CLI parsing (free-form text → payload dict) lives in
`cmd_parser`.

Pure functions — no module globals. Routing and schema inputs arrive via
parameters (`cmd_defs`, `nodes`).

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mav_gss_lib.missions.maveric.wire_format import build_cmd_raw
from mav_gss_lib.missions.maveric.schema import validate_args

if TYPE_CHECKING:
    from mav_gss_lib.missions.maveric.nodes import NodeTable


def _resolve_routing(payload: dict, nodes: NodeTable) -> tuple[int, int, int, int]:
    """Resolve (src, dest, echo, ptype) integers from a payload dict."""
    src_name = str(payload.get("src", ""))
    if src_name:
        src = nodes.resolve_node(src_name)
        if src is None:
            raise ValueError(f"unknown source node '{src_name}'")
    else:
        src = nodes.gs_node

    dest_name = str(payload.get("dest", ""))
    dest = nodes.resolve_node(dest_name)
    if dest is None:
        raise ValueError(f"unknown destination node '{dest_name}'")

    echo_name = str(payload.get("echo", "NONE"))
    echo = nodes.resolve_node(echo_name)
    if echo is None:
        raise ValueError(f"unknown echo node '{echo_name}'")

    ptype_name = str(payload.get("ptype", "CMD"))
    ptype = nodes.resolve_ptype(ptype_name)
    if ptype is None:
        raise ValueError(f"unknown packet type '{ptype_name}'")

    return src, dest, echo, ptype


def _normalize_args(
    args_input: str | dict[str, Any],
    tx_args_schema: list[dict[str, Any]],
) -> tuple[str, dict[str, Any], list[str]]:
    """Return (args_str, args_dict, extra_tokens).

    `args_str` is the wire-form string; `args_dict` maps schema arg names
    to raw string tokens for display; `extra_tokens` are any trailing
    tokens past the schema (only possible when `args_input` is a str).
    """
    if isinstance(args_input, str):
        args_str = args_input
        tokens = args_str.split() if args_str.strip() else []
        args_dict: dict = {}
        for i, arg_def in enumerate(tx_args_schema):
            if i < len(tokens):
                args_dict[arg_def["name"]] = tokens[i]
        extra_tokens = tokens[len(tx_args_schema):]
        return args_str, args_dict, extra_tokens

    if not isinstance(args_input, dict):
        raise ValueError("args must be a str or dict")
    args_dict = args_input
    args_parts = []
    gap_seen = False
    for arg_def in tx_args_schema:
        val = args_dict.get(arg_def["name"], "")
        if val:
            if gap_seen:
                raise ValueError(
                    f"cannot set '{arg_def['name']}' without setting earlier optional args"
                )
            args_parts.append(str(val))
        else:
            gap_seen = True
    args_str = " ".join(args_parts)
    return args_str, args_dict, []


def _build_display(
    cmd_id: str, args_str: str, args_dict: dict,
    tx_args_schema: list, args_input_is_str: bool, *,
    src: int, dest: int, echo: int, ptype: int, nodes: NodeTable,
) -> dict:
    """Assemble the mission-opaque `display` dict for a TX command."""
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
    if args_input_is_str:
        parts = args_str.split() if args_str else []
        for i, extra in enumerate(parts[len(tx_args_schema):]):
            args_fields.append({"name": f"arg{len(tx_args_schema) + i}", "value": extra})

    detail_blocks = [routing_block]
    if args_fields:
        detail_blocks.append({"kind": "args", "label": "Arguments", "fields": args_fields})

    return {
        "title": cmd_id,
        "subtitle": nodes.node_name(dest),
        "row": row,
        "detail_blocks": detail_blocks,
    }


def build_tx_command(
    payload: dict[str, Any],
    cmd_defs: dict[str, Any],
    nodes: NodeTable,
) -> dict[str, Any]:
    """Build a mission command from a structured payload.

    Accepts: {cmd_id, args: str | {name: value, ...}, src?, dest, echo, ptype, guard?}
    Returns: {raw_cmd: bytes, display: dict, guard: bool}
    Raises ValueError on validation failure.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    cmd_id = str(payload.get("cmd_id", "")).lower()

    src, dest, echo, ptype = _resolve_routing(payload, nodes)

    if cmd_defs and cmd_id not in cmd_defs:
        raise ValueError(f"'{cmd_id}' not in schema")
    defn = cmd_defs.get(cmd_id, {})
    if defn.get("rx_only"):
        raise ValueError(f"'{cmd_id}' is receive-only")
    dest_name = str(payload.get("dest", ""))
    allowed_nodes = defn.get("nodes", [])
    if allowed_nodes and dest_name not in allowed_nodes:
        raise ValueError(f"'{cmd_id}' not valid for node '{dest_name}' (allowed: {', '.join(allowed_nodes)})")

    args_input = payload.get("args", {})
    tx_args_schema = defn.get("tx_args", [])
    args_str, args_dict, _extra = _normalize_args(args_input, tx_args_schema)

    valid, issues = validate_args(cmd_id, args_str, cmd_defs)
    if not valid:
        raise ValueError("; ".join(issues))

    raw_cmd = bytes(build_cmd_raw(src, dest, cmd_id, args_str, echo=echo, ptype=ptype))
    guard = payload.get("guard", defn.get("guard", False))
    display = _build_display(
        cmd_id, args_str, args_dict, tx_args_schema,
        args_input_is_str=isinstance(args_input, str),
        src=src, dest=dest, echo=echo, ptype=ptype, nodes=nodes,
    )
    return {"raw_cmd": raw_cmd, "display": display, "guard": guard}
