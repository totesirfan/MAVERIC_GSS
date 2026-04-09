"""
mav_gss_lib.missions.maveric -- MAVERIC CubeSat Mission Implementation

Mission package contract:
  - ADAPTER_API_VERSION: int — adapter contract version
  - ADAPTER_CLASS: type — adapter class (MavericMissionAdapter)
  - init_mission(cfg): mission-specific initialization hook
  - get_plugin_routers(): optional FastAPI routers for mission plugins
  - mission.example.yml: tracked public-safe mission metadata baseline
  - mission.yml: optional local mission metadata override
  - adapter.py: MissionAdapter implementation
  - wire_format.py: command wire format, schema, node tables
  - imaging.py: image chunk reassembly + REST API
"""

ADAPTER_API_VERSION = 1

from mav_gss_lib.missions.maveric.adapter import MavericMissionAdapter as ADAPTER_CLASS  # noqa: F401

# Module-level reference to the ImageAssembler, set during init_mission
_image_assembler = None


def init_mission(cfg: dict) -> dict:
    """Initialize MAVERIC mission resources.

    Called by the shared mission loader after metadata merge.
    Populates node/ptype tables and loads the command schema.

    Returns:
        {"cmd_defs": dict, "cmd_warn": str | None}
    """
    global _image_assembler
    import os
    from mav_gss_lib.missions.maveric.wire_format import init_nodes, load_command_defs
    from mav_gss_lib.missions.maveric.imaging import ImageAssembler

    init_nodes(cfg)

    # Initialize ImageAssembler
    image_dir = cfg.get("general", {}).get("image_dir", "images")
    _image_assembler = ImageAssembler(image_dir)

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
            # Fall back to config dir for backward compat
            config_dir = os.path.join(pkg_dir, "..", "..", "config")
            config_path = os.path.normpath(os.path.join(config_dir, cmd_defs_name))
            path = config_path if os.path.isfile(config_path) else mission_path

    cmd_defs, cmd_warn = load_command_defs(path)
    cfg.setdefault("general", {})["command_defs_resolved"] = os.path.abspath(path)
    cfg["general"]["command_defs_warning"] = cmd_warn or ""
    return {
        "cmd_defs": cmd_defs,
        "cmd_warn": cmd_warn,
        "cmd_path": os.path.abspath(path),
        "image_assembler": _image_assembler,
    }


def get_plugin_routers():
    """Return FastAPI routers for MAVERIC mission plugins."""
    if _image_assembler is None:
        return []
    from mav_gss_lib.missions.maveric.imaging import get_imaging_router
    return [get_imaging_router(_image_assembler)]
