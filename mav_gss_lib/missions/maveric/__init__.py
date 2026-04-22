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
    Builds NodeTable, loads the command schema, and declares the
    telemetry manifest + extractors the platform router consumes.

    Returns:
        {"cmd_defs": dict, "cmd_warn": str | None, "nodes": NodeTable,
         "image_assembler": ImageAssembler,
         "telemetry_manifest": dict, "telemetry_extractors": tuple}
    """
    import os
    from mav_gss_lib.missions.maveric.nodes import init_nodes
    from mav_gss_lib.missions.maveric.schema import load_command_defs
    from mav_gss_lib.missions.maveric.imaging import ImageAssembler
    from mav_gss_lib.missions.maveric.telemetry import TELEMETRY_MANIFEST
    from mav_gss_lib.missions.maveric.telemetry.extractors import EXTRACTORS

    nodes = init_nodes(cfg)

    # Initialize ImageAssembler
    image_dir = cfg.get("general", {}).get("image_dir", "images")
    image_assembler = ImageAssembler(image_dir)

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
        "telemetry_manifest": TELEMETRY_MANIFEST,
        "telemetry_extractors": EXTRACTORS,
    }


def get_plugin_routers(adapter=None, config_accessor=None):
    """Return FastAPI routers for MAVERIC mission plugins.

    Post-v2: only imaging. GNC snapshot + EPS snapshot routers are gone —
    canonical state is served by the platform's /api/telemetry/* routes
    (clear snapshot + catalog). Imaging is unaffected.

    Args:
        adapter: MavericMissionAdapter. A router is only built for
                 resources the adapter actually carries.
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

    return routers
