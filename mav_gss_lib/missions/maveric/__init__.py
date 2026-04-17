"""
mav_gss_lib.missions.maveric -- MAVERIC CubeSat Mission Implementation

Mission package contract:
  - ADAPTER_API_VERSION: int — adapter contract version
  - ADAPTER_CLASS: type — adapter class (MavericMissionAdapter)
  - init_mission(cfg): mission-specific initialization hook
  - get_plugin_routers(adapter): optional FastAPI routers for mission plugins
  - mission.example.yml: tracked public-safe template for mission.yml
  - mission.yml: local mission metadata (gitignored; nodes, ptypes, protocol defaults)
  - adapter.py: MissionAdapter implementation
  - nodes.py: NodeTable dataclass + init_nodes() factory
  - wire_format.py: CommandFrame encode/decode
  - schema.py: command schema loading + validation
  - cmd_parser.py: TX command line parser
  - imaging.py: image chunk reassembly + REST API
"""

ADAPTER_API_VERSION = 1

from mav_gss_lib.missions.maveric.adapter import MavericMissionAdapter as ADAPTER_CLASS  # noqa: F401


def init_mission(cfg: dict) -> dict:
    """Initialize MAVERIC mission resources.

    Called by the shared mission loader after metadata merge.
    Builds NodeTable and loads the command schema.

    Returns:
        {"cmd_defs": dict, "cmd_warn": str | None, "nodes": NodeTable,
         "image_assembler": ImageAssembler}
    """
    import os
    from mav_gss_lib.missions.maveric.nodes import init_nodes
    from mav_gss_lib.missions.maveric.schema import load_command_defs
    from mav_gss_lib.missions.maveric.imaging import ImageAssembler
    from mav_gss_lib.missions.maveric.telemetry.gnc_registers import GncRegisterStore

    nodes = init_nodes(cfg)

    # Initialize ImageAssembler
    image_dir = cfg.get("general", {}).get("image_dir", "images")
    image_assembler = ImageAssembler(image_dir)

    # Initialize persistent GNC register store. The path is hard-wired
    # to <log_dir>/.gnc_snapshot.json — same trust boundary as the
    # platform's pending-queue sidecar, not a separately user-editable
    # knob. Operators change log_dir, not this path directly.
    log_dir = cfg.get("general", {}).get("log_dir", "logs")
    gnc_snapshot_path = os.path.join(log_dir, ".gnc_snapshot.json")
    gnc_store = GncRegisterStore(gnc_snapshot_path)

    # Resolve command schema path: check mission package dir first
    cmd_defs_name = cfg.get("general", {}).get("command_defs", "commands.yml")
    pkg_dir = os.path.dirname(os.path.abspath(__file__))

    if os.path.isabs(cmd_defs_name):
        path = cmd_defs_name
    else:
        mission_path = os.path.join(pkg_dir, cmd_defs_name)
        if os.path.isfile(mission_path):
            path = mission_path
        else:
            config_dir = os.path.join(pkg_dir, "..", "..", "config")
            config_path = os.path.normpath(os.path.join(config_dir, cmd_defs_name))
            path = config_path if os.path.isfile(config_path) else mission_path

    cmd_defs, cmd_warn = load_command_defs(path, nodes=nodes)
    cfg.setdefault("general", {})["command_defs_resolved"] = os.path.abspath(path)
    cfg["general"]["command_defs_warning"] = cmd_warn or ""
    return {
        "cmd_defs": cmd_defs,
        "cmd_warn": cmd_warn,
        "cmd_path": os.path.abspath(path),
        "nodes": nodes,
        "image_assembler": image_assembler,
        "gnc_store": gnc_store,
    }


def get_plugin_routers(adapter=None, config_accessor=None):
    """Return FastAPI routers for MAVERIC mission plugins.

    Args:
        adapter: MavericMissionAdapter with image_assembler / gnc_store
                 attributes. Routers are only built for resources that
                 the adapter actually carries.
        config_accessor: Optional zero-arg callable returning the live
                 mission config dict. Passed through to plugin routers
                 that need live config lookups (e.g., the imaging router
                 reads ``imaging.thumb_prefix`` for pair grouping).
    """
    routers = []
    if adapter is None:
        return routers

    assembler = getattr(adapter, "image_assembler", None)
    if assembler is not None:
        from mav_gss_lib.missions.maveric.imaging import get_imaging_router
        routers.append(get_imaging_router(assembler, config_accessor=config_accessor))

    gnc_store = getattr(adapter, "gnc_store", None)
    if gnc_store is not None:
        from mav_gss_lib.missions.maveric.telemetry.gnc_router import get_gnc_router
        routers.append(get_gnc_router(gnc_store))

    return routers
