"""
mav_gss_lib.missions.maveric.nodes -- Node & Packet Type Resolution

NodeTable dataclass holds all node/ptype addressing state.
init_nodes() is the only constructor — call once at startup.

Author:  Irfan Annuar - USC ISI SERC
"""

from dataclasses import dataclass, field


@dataclass
class NodeTable:
    """Immutable snapshot of node/ptype addressing tables.

    Created by init_nodes(cfg) at startup. Passed explicitly through
    the adapter to all ops/rendering/logging code that needs resolution.
    """
    node_names: dict = field(default_factory=dict)   # int -> str
    node_ids:   dict = field(default_factory=dict)    # str -> int
    ptype_names: dict = field(default_factory=dict)   # int -> str
    ptype_ids:   dict = field(default_factory=dict)   # str -> int
    gs_node:     int = 6

    def node_name(self, node_id: int) -> str:
        return self.node_names.get(node_id, str(node_id))

    def ptype_name(self, ptype_id: int) -> str:
        return self.ptype_names.get(ptype_id, str(ptype_id))

    def resolve_node(self, s: str) -> int | None:
        upper = s.upper()
        if upper in self.node_ids:
            return self.node_ids[upper]
        if s.isdigit():
            val = int(s)
            if val in self.node_names:
                return val
        return None

    def resolve_ptype(self, s: str) -> int | None:
        upper = s.upper()
        if upper in self.ptype_ids:
            return self.ptype_ids[upper]
        if s.isdigit():
            val = int(s)
            if val in self.ptype_names:
                return val
        return None


def init_nodes(cfg: dict) -> NodeTable:
    """Build a NodeTable from a loaded config dict.

    Must be called once at startup after load_gss_config() + metadata merge.
    Returns the table — caller stores it (no module globals).
    """
    node_names = {int(k): v for k, v in cfg["nodes"].items()}
    node_ids = {v: k for k, v in node_names.items()}

    ptype_names = {int(k): v for k, v in cfg["ptypes"].items()}
    ptype_ids = {v: k for k, v in ptype_names.items()}

    gs_name = cfg.get("general", {}).get("gs_node", "GS")
    gs_node = node_ids.get(gs_name, 6)

    return NodeTable(
        node_names=node_names,
        node_ids=node_ids,
        ptype_names=ptype_names,
        ptype_ids=ptype_ids,
        gs_node=gs_node,
    )
