"""
mav_gss_lib.mission_adapter -- Mission Adapter Interface and Loader

Platform core:
  - ParsedPacket: normalized packet parse result
  - MissionAdapter: formal Protocol defining the mission boundary
  - load_mission_adapter(cfg): single-entry-point mission loader
  - load_mission_metadata(cfg): merge mission metadata into runtime config

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


# =============================================================================
#  PLATFORM CORE -- ParsedPacket
# =============================================================================

@dataclass
class ParsedPacket:
    """Mission-opaque packet parse result returned by a mission adapter.

    The adapter populates mission_data with whatever mission-specific
    semantics it needs. The platform never reads mission_data directly —
    it passes it through to adapter rendering/logging methods.
    """

    mission_data: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# =============================================================================
#  PLATFORM CORE -- Rendering Contracts
# =============================================================================

@dataclass
class ProtocolBlock:
    """Standardized protocol/wrapper information for the detail view.

    The platform owns how these are rendered. Missions provide the data.
    """
    kind: str        # e.g. "csp", "ax25"
    label: str       # e.g. "CSP V1", "AX.25"
    fields: list     # list of {"name": str, "value": str}


@dataclass
class IntegrityBlock:
    """Standardized integrity check result for the detail view.

    The platform owns how these are rendered. Missions provide the data.
    """
    kind: str                    # e.g. "crc16", "crc32c"
    label: str                   # e.g. "CRC-16", "CRC-32C"
    scope: str                   # e.g. "command", "csp"
    ok: bool | None              # True/False/None (unknown)
    received: str | None = None  # e.g. "0x1234"
    computed: str | None = None  # e.g. "0x1234"


# =============================================================================
#  PLATFORM CORE -- MissionAdapter Protocol
# =============================================================================

@runtime_checkable
class MissionAdapter(Protocol):
    """Formal interface for mission adapter implementations.

    Missions provide an adapter that satisfies this protocol.
    The platform runtime calls these methods without knowing
    which mission is active.
    """

    def detect_frame_type(self, meta: dict) -> str: ...
    def normalize_frame(self, frame_type: str, raw: bytes) -> tuple: ...

    def parse_packet(self, inner_payload: bytes, warnings: list[str] | None = None) -> ParsedPacket: ...

    def duplicate_fingerprint(self, parsed: ParsedPacket) -> tuple | None: ...
    def is_uplink_echo(self, cmd) -> bool: ...

    def build_tx_command(self, payload: dict) -> dict: ...

    # -- Rendering-slot contract (architecture spec §4) --
    def packet_list_columns(self) -> list[dict]: ...
    def packet_list_row(self, pkt) -> dict: ...
    def packet_detail_blocks(self, pkt) -> list[dict]: ...
    def protocol_blocks(self, pkt) -> list: ...
    def integrity_blocks(self, pkt) -> list: ...

    # -- Logging-slot contract --
    def build_log_mission_data(self, pkt) -> dict: ...
    def format_log_lines(self, pkt) -> list[str]: ...
    def is_unknown_packet(self, parsed: ParsedPacket) -> bool: ...

    # -- Plugin hook (optional) --
    # def on_packet_received(self, pkt) -> list[dict] | None: ...

    # -- Resolution contract --
    @property
    def gs_node(self) -> int: ...
    def node_name(self, node_id: int) -> str: ...
    def ptype_name(self, ptype_id: int) -> str: ...
    def node_label(self, node_id: int) -> str: ...
    def ptype_label(self, ptype_id: int) -> str: ...
    def resolve_node(self, s: str) -> int | None: ...
    def resolve_ptype(self, s: str) -> int | None: ...
    def cmd_line_to_payload(self, line: str) -> dict: ...
    def tx_queue_columns(self) -> list[dict]: ...


# =============================================================================
#  PLATFORM CORE -- Adapter Validation
# =============================================================================

SUPPORTED_API_VERSIONS = {1}


def validate_adapter(adapter, api_version: int, mission_name: str) -> None:
    """Check that a mission adapter has the required methods and API version.

    Uses @runtime_checkable Protocol for structural interface presence
    (method names only, not signatures). Raises ValueError if validation fails.
    Called once at startup before the adapter is used.
    """
    if not isinstance(adapter, MissionAdapter):
        missing = []
        for method_name in (
            'detect_frame_type', 'normalize_frame', 'parse_packet',
            'duplicate_fingerprint', 'is_uplink_echo',
            'build_tx_command',
            'packet_list_columns', 'packet_list_row',
            'packet_detail_blocks', 'protocol_blocks', 'integrity_blocks',
            'build_log_mission_data', 'format_log_lines', 'is_unknown_packet',
            'node_name', 'ptype_name', 'node_label', 'ptype_label',
            'resolve_node', 'resolve_ptype', 'cmd_line_to_payload',
            'tx_queue_columns',
        ):
            if not hasattr(adapter, method_name):
                missing.append(method_name)
        raise ValueError(
            f"Mission '{mission_name}' adapter {type(adapter).__name__} "
            f"does not satisfy MissionAdapter interface. "
            f"Missing methods: {', '.join(missing) if missing else 'unknown'}"
        )
    if not hasattr(adapter, 'gs_node'):
        raise ValueError(
            f"Mission '{mission_name}' adapter {type(adapter).__name__} "
            f"missing required property: gs_node"
        )
    if api_version not in SUPPORTED_API_VERSIONS:
        raise ValueError(
            f"Mission '{mission_name}' declares ADAPTER_API_VERSION={api_version}, "
            f"but this platform supports: {sorted(SUPPORTED_API_VERSIONS)}"
        )


# =============================================================================
#  PLATFORM CORE -- TX Plugin Helpers
# =============================================================================


def get_tx_capabilities(adapter) -> dict:
    """Return backend TX capabilities. Builder UI availability is
    determined by the frontend from convention-based discovery."""
    if hasattr(adapter, 'tx_capabilities') and callable(adapter.tx_capabilities):
        return adapter.tx_capabilities()
    return {"raw_send": True}


# =============================================================================
#  PLATFORM CORE -- Mission Loader
# =============================================================================

def _resolve_mission_module(mission_id: str) -> str:
    """Resolve a mission ID to its Python module path by convention.

    Looks for an importable package at mav_gss_lib.missions.<mission_id>.
    Returns the module path string if found.

    Raises ImportError if the package does not exist.
    Re-raises the original exception if the package exists but fails
    during import (broken dependency, syntax error, etc.) so that real
    bugs are not masked as "mission not found."

    This is the single resolution point for mission packages. If external
    or path-based mission loading is needed later, extend this function.
    """
    import importlib
    import importlib.util
    module_path = f"mav_gss_lib.missions.{mission_id}"
    spec = importlib.util.find_spec(module_path)
    if spec is None:
        raise ImportError(
            f"No mission package found at {module_path}. "
            f"Create mav_gss_lib/missions/{mission_id}/ with __init__.py."
        )
    importlib.import_module(module_path)
    return module_path


def _merge_mission_metadata(cfg: dict, mission_meta: dict) -> None:
    """Merge mission metadata into the runtime config dict in place.

    Mission metadata provides defaults. The operator's gss.yml
    values take precedence (they were already merged into cfg by
    load_gss_config).
    """
    for key in ("nodes", "ptypes", "node_descriptions", "ax25", "csp"):
        if key in mission_meta:
            existing = cfg.get(key, {})
            if isinstance(existing, dict) and existing:
                merged = dict(mission_meta[key])
                merged.update(existing)
                cfg[key] = merged
            else:
                cfg[key] = mission_meta[key]

    general = cfg.setdefault("general", {})
    if "mission_name" in mission_meta:
        general.setdefault("mission_name", mission_meta["mission_name"])
    if "gs_node" in mission_meta:
        general.setdefault("gs_node", mission_meta["gs_node"])
    if "command_defs" in mission_meta:
        general.setdefault("command_defs", mission_meta["command_defs"])

    ui = mission_meta.get("ui", {})
    for key in ("rx_title", "tx_title", "splash_subtitle"):
        if key in ui:
            general.setdefault(key, ui[key])

    tx_meta = mission_meta.get("tx", {})
    tx_cfg = cfg.setdefault("tx", {})
    for key in ("frequency", "uplink_mode"):
        if key in tx_meta:
            tx_cfg.setdefault(key, tx_meta[key])


def load_mission_metadata(cfg: dict) -> dict:
    """Read mission metadata and merge it into cfg.

    Must be called BEFORE init_nodes() and load_command_defs() so those
    see mission-provided values (nodes, ptypes, command_defs path).

    Resolution order:
      1. mission.yml          -- local/private mission metadata override
      2. mission.example.yml  -- tracked public-safe baseline

    Returns the raw metadata dict actually loaded. If neither file exists,
    returns empty dict and continues without error.
    """
    import importlib
    import importlib.util
    import logging
    import os

    mission = cfg.get("general", {}).get("mission", "maveric")
    spec = importlib.util.find_spec(f"mav_gss_lib.missions.{mission}")
    if spec is None:
        return {}

    module_path = f"mav_gss_lib.missions.{mission}"
    mission_pkg = importlib.import_module(module_path)

    pkg_dir = os.path.dirname(os.path.abspath(mission_pkg.__file__))
    metadata_path = ""
    for candidate in ("mission.yml", "mission.example.yml"):
        candidate_path = os.path.join(pkg_dir, candidate)
        if os.path.isfile(candidate_path):
            metadata_path = candidate_path
            break

    if not metadata_path:
        logging.debug("No mission metadata found for '%s' under %s", mission, pkg_dir)
        return {}

    try:
        import yaml
        with open(metadata_path) as f:
            mission_meta = yaml.safe_load(f) or {}
    except Exception as exc:
        logging.warning("Could not read %s: %s", metadata_path, exc)
        return {}

    _merge_mission_metadata(cfg, mission_meta)
    return mission_meta


def load_mission_adapter(cfg: dict, cmd_defs: dict | None = None):
    """Load, instantiate, and validate a mission adapter from config.

    This is the single shared mission-loading path. It owns:
      1. load_mission_metadata(cfg) — merge mission metadata
      2. mission_pkg.init_mission(cfg) — mission-specific init
      3. ADAPTER_CLASS(cmd_defs=...) — adapter construction
      4. validate_adapter() — interface validation

    The cmd_defs parameter is deprecated and ignored when the mission
    package provides init_mission(). It exists only for backward
    compatibility with callers that haven't been updated yet.

    Returns a validated adapter with cmd_defs populated.
    """
    import importlib
    import logging

    mission = cfg.get("general", {}).get("mission", "maveric")
    mission_name = cfg.get("general", {}).get("mission_name", mission.upper())

    # Ensure mission metadata is merged (idempotent — safe if already called)
    load_mission_metadata(cfg)

    module_path = _resolve_mission_module(mission)
    mission_pkg = importlib.import_module(module_path)  # already imported, returns cached

    api_version = getattr(mission_pkg, "ADAPTER_API_VERSION", None)
    if api_version is None:
        raise ValueError(
            f"Mission '{mission}' package '{module_path}' has no ADAPTER_API_VERSION"
        )

    adapter_cls = getattr(mission_pkg, "ADAPTER_CLASS", None)
    if adapter_cls is None:
        raise ValueError(
            f"Mission '{mission}' package '{module_path}' has no ADAPTER_CLASS"
        )

    # Call mission init hook if available
    init_fn = getattr(mission_pkg, "init_mission", None)
    resources = {}
    if init_fn is not None:
        resources = init_fn(cfg)
        resolved_cmd_defs = resources.get("cmd_defs", {})
    elif cmd_defs is not None:
        # Backward compat: caller provided cmd_defs directly
        resolved_cmd_defs = cmd_defs
    else:
        resolved_cmd_defs = {}

    # Build adapter kwargs — pass image_assembler if mission provides one
    adapter_kwargs = {"cmd_defs": resolved_cmd_defs}
    if resources.get("image_assembler") is not None:
        adapter_kwargs["image_assembler"] = resources["image_assembler"]

    adapter = adapter_cls(**adapter_kwargs)
    validate_adapter(adapter, api_version, mission_name)

    cmd_path = cfg.get("general", {}).get("command_defs", "")
    logging.info(
        "Mission loaded: %s [id=%s, adapter API v%d, schema=%s]",
        mission_name, mission, api_version, cmd_path,
    )
    return adapter
