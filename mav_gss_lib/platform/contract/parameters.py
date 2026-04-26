"""ParamUpdate — emit type for parameter cache. Mirror of PacketEnvelope's
location so platform/contract/packets.py can hold tuple[ParamUpdate, ...]
without an upward import."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ParamUpdate:
    """One parameter's value at one moment.

    `name` is fully qualified — ``"<group>.<key>"``. `unit` is optional
    display metadata used by the JSONL log writer; ParameterCache does
    not persist it (mission.yml is the source of unit truth via
    `parameter_types[ref].unit`). `display_only` updates render in
    detail blocks and JSONL but bypass cache persistence.
    """
    name: str
    value: Any
    ts_ms: int
    unit: str = ""
    display_only: bool = False


__all__ = ["ParamUpdate"]
