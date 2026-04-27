"""Platform runtime container used by the production web runtime.

Loads the active MissionSpec, builds the DeclarativeWalker from
``mission.spec_root`` + ``mission.spec_plugins``, owns the live
``ParameterCache``, processes RX through ``RxPipeline``, and prepares
TX commands through ``CommandOps``.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contract.commands import EncodedCommand, FramedCommand
from .contract.mission import MissionSpec
from .loader import load_mission_spec_from_split
from .parameter_cache import ParameterCache
from .rx.pipeline import RxPipeline, RxResult
from .spec.runtime import DeclarativeWalker
from .tx.commands import PreparedCommand, frame_command, prepare_command
from .tx.verifiers import VerifierRegistry


def _resolve_log_dir(platform_cfg: dict[str, Any]) -> str:
    general = platform_cfg.get("general") or {}
    log_dir = general.get("log_dir")
    if log_dir:
        return str(log_dir)
    logs_block = platform_cfg.get("logs") or {}
    return str(logs_block.get("dir", "logs"))


@dataclass(slots=True)
class PlatformRuntime:
    """Mission + walker + parameter cache + RX pipeline, bound to split state.

    Created once per ``WebRuntime`` via ``PlatformRuntime.from_split(...)``.
    ``process_rx`` / ``prepare_tx`` / ``frame_tx`` are the three entry
    points the server calls on every RX packet and TX command.
    """

    mission: MissionSpec
    walker: DeclarativeWalker | None
    parameter_cache: ParameterCache
    rx: RxPipeline
    verifiers: VerifierRegistry

    @classmethod
    def from_split(
        cls,
        platform_cfg: dict[str, Any],
        mission_id: str,
        mission_cfg: dict[str, Any],
        *,
        on_parameter_apply=None,
    ) -> "PlatformRuntime":
        """Build the platform runtime from split operator state.

        Loads the active MissionSpec, constructs the walker from the
        mission's ``spec_root`` + ``spec_plugins`` (None when the mission
        has no declarative spec), builds the ``ParameterCache`` rooted
        under ``<log_dir>/parameters.json``, and wires the ``RxPipeline``.
        """
        log_dir = _resolve_log_dir(platform_cfg)
        mission = load_mission_spec_from_split(
            platform_cfg, mission_id, mission_cfg, data_dir=Path(log_dir),
        )
        walker = (
            DeclarativeWalker(mission.spec_root, plugins=mission.spec_plugins)
            if mission.spec_root is not None else None
        )
        cache = ParameterCache(
            Path(log_dir) / "parameters.json",
            on_apply=on_parameter_apply,
        )
        return cls(
            mission=mission,
            walker=walker,
            parameter_cache=cache,
            rx=RxPipeline(mission, walker, cache),
            verifiers=VerifierRegistry(),
        )

    def process_rx(self, meta: dict[str, Any], raw: bytes) -> RxResult:
        """Run one inbound frame through the full RX pipeline."""
        return self.rx.process(meta, raw)

    def prepare_tx(self, value: str | dict[str, Any]) -> PreparedCommand:
        """Run the mission command pipeline: parse → validate → encode → render."""
        return prepare_command(self.mission, value)

    def frame_tx(self, encoded: EncodedCommand) -> FramedCommand:
        """Ask the mission to wrap encoded bytes in its wire framing."""
        return frame_command(self.mission, encoded)

    def restore_verifiers(self, *, path, now_ms: int) -> None:
        """Load any persisted in-flight command instances into the registry."""
        from .tx.verifiers import restore_instances

        for inst in restore_instances(path, now_ms=now_ms):
            self.verifiers.register(inst)
