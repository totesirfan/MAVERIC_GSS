"""Platform runtime container used by the production web runtime.

Loads the active MissionSpec, registers mission telemetry domains,
processes RX through `RxPipeline`, and prepares TX commands through
`CommandOps`.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contract.commands import EncodedCommand, FramedCommand
from .contract.mission import MissionSpec
from .loader import load_mission_spec_from_split
from .rx.pipeline import RxPipeline, RxResult
from .telemetry import TelemetryRouter
from .tx.commands import PreparedCommand, frame_command, prepare_command


def _resolve_log_dir(platform_cfg: dict[str, Any]) -> str:
    general = platform_cfg.get("general") or {}
    log_dir = general.get("log_dir")
    if log_dir:
        return str(log_dir)
    logs_block = platform_cfg.get("logs") or {}
    return str(logs_block.get("dir", "logs"))


@dataclass(slots=True)
class PlatformRuntime:
    """Mission + telemetry router + RX pipeline, bound to split operator state.

    Created once per ``WebRuntime`` via ``PlatformRuntime.from_split(...)``.
    ``process_rx`` / ``prepare_tx`` / ``frame_tx`` are the three entry
    points the server calls on every RX packet and TX command.
    """

    mission: MissionSpec
    telemetry: TelemetryRouter
    rx: RxPipeline

    @classmethod
    def from_split(
        cls,
        platform_cfg: dict[str, Any],
        mission_id: str,
        mission_cfg: dict[str, Any],
    ) -> "PlatformRuntime":
        """Build the platform runtime from split operator state.

        Loads the active MissionSpec, registers mission telemetry domains
        on a fresh ``TelemetryRouter`` rooted under ``<log_dir>/.telemetry``,
        and wires the ``RxPipeline`` that stitches packet/telemetry/render
        into one call.
        """
        log_dir = _resolve_log_dir(platform_cfg)
        mission = load_mission_spec_from_split(
            platform_cfg, mission_id, mission_cfg, data_dir=Path(log_dir),
        )
        telemetry = TelemetryRouter(Path(log_dir) / ".telemetry")
        if mission.telemetry is not None:
            for name, domain in mission.telemetry.domains.items():
                telemetry.register_domain(name, **domain.router_kwargs())
        return cls(
            mission=mission,
            telemetry=telemetry,
            rx=RxPipeline(mission, telemetry),
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
