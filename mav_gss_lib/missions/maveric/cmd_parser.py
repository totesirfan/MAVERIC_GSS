"""
mav_gss_lib.missions.maveric.cmd_parser -- TX Command Line Parser

Parses operator input into structured command fields for uplink.
Counterpart to try_parse_command() which parses the wire format (RX).

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mav_gss_lib.missions.maveric.nodes import NodeTable


def parse_cmd_line(line: str, nodes: NodeTable) -> tuple:
    """Parse command line: [SRC] DEST ECHO TYPE CMD [ARGS]

    SRC is optional -- if omitted, defaults to GS (nodes.gs_node).
    Detection: with 5+ tokens, if parts[3] resolves as a ptype then
    the first token is SRC; otherwise the old 4-token format is assumed.

    Returns (src, dest, echo, ptype, cmd, args).
    Raises ValueError with a specific message on failure."""
    parts = line.split(None, 5)
    if len(parts) < 4:
        raise ValueError("need at least: <dest> <echo> <type> <cmd>")

    # Detect format: if parts[3] is a valid ptype, first token is SRC
    ptype3 = nodes.resolve_ptype(parts[3]) if len(parts) >= 5 else None
    if ptype3 is not None:
        offset, src = 1, nodes.resolve_node(parts[0])
        if src is None:
            raise ValueError(f"unknown source node '{parts[0]}'")
        ptype = ptype3
    else:
        offset, src = 0, nodes.gs_node
        ptype = nodes.resolve_ptype(parts[2])
        if ptype is None:
            raise ValueError(f"unknown packet type '{parts[2]}'")

    dest = nodes.resolve_node(parts[offset])
    if dest is None:
        raise ValueError(f"unknown destination node '{parts[offset]}'")
    echo = nodes.resolve_node(parts[offset + 1])
    if echo is None:
        raise ValueError(f"unknown echo node '{parts[offset + 1]}'")

    cmd_idx = offset + 3
    args = " ".join(parts[cmd_idx + 1:]) if len(parts) > cmd_idx + 1 else ""
    return (src, dest, echo, ptype, parts[cmd_idx].lower(), args)
