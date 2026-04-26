"""Declarative framing-spec types for mission.yml.

A mission may declare its uplink framer chain as YAML:

    framing:
      uplink:
        label: "ASM+Golay"
        chain:
          - framer: csp_v1
            config_ref: csp
          - framer: asm_golay
      downlink:
        accept_frame_types: [ASM+GOLAY]
        on_unexpected: warn

Parsed at boot into FramingSpec. Consumed by
mav_gss_lib.platform.framing.declarative.DeclarativeFramer, which builds
a per-send FramerChain and resolves `config_ref:` against live
mission_cfg so operator edits propagate without a MissionSpec rebuild.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class FramerSpec:
    framer: str
    config: Mapping[str, Any] = field(default_factory=dict)
    config_ref: str | None = None


@dataclass(frozen=True, slots=True)
class FramingSpec:
    uplink_chain: tuple[FramerSpec, ...]
    uplink_label: str | None = None
    accept_frame_types: tuple[str, ...] = ()
    on_unexpected: str = "warn"


_VALID_ON_UNEXPECTED = ("warn", "drop", "accept")


def parse_framing_section(raw: Mapping[str, Any] | None) -> FramingSpec | None:
    """Parse the ``framing:`` block from mission.yml.

    Returns None when the block is absent (raw is None). An empty mapping
    raises — a present-but-empty block is an authoring mistake we surface
    rather than silently swallow.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("framing must be a mapping")

    uplink = raw.get("uplink") or {}
    if not isinstance(uplink, Mapping):
        raise ValueError("framing.uplink must be a mapping")
    chain_raw = uplink.get("chain") or []
    if not isinstance(chain_raw, list) or not chain_raw:
        raise ValueError("framing.uplink.chain must be a non-empty list")
    chain: list[FramerSpec] = []
    for entry in chain_raw:
        if not isinstance(entry, Mapping):
            raise ValueError(f"framing.uplink.chain entry must be a mapping, got {type(entry).__name__}")
        framer = entry.get("framer")
        if not isinstance(framer, str) or not framer:
            raise ValueError(f"framing.uplink.chain entry missing 'framer' key: {entry!r}")
        config = entry.get("config") or {}
        if not isinstance(config, Mapping):
            raise ValueError(f"framing.uplink.chain[{framer}].config must be a mapping")
        config_ref = entry.get("config_ref")
        if config_ref is not None and not isinstance(config_ref, str):
            raise ValueError(f"framing.uplink.chain[{framer}].config_ref must be a string")
        chain.append(FramerSpec(framer=framer, config=dict(config), config_ref=config_ref))

    label = uplink.get("label")
    if label is not None and not isinstance(label, str):
        raise ValueError("framing.uplink.label must be a string")

    downlink = raw.get("downlink") or {}
    if not isinstance(downlink, Mapping):
        raise ValueError("framing.downlink must be a mapping")
    accept = downlink.get("accept_frame_types") or ()
    if not isinstance(accept, (list, tuple)):
        raise ValueError("framing.downlink.accept_frame_types must be a list")
    on_unexpected = downlink.get("on_unexpected", "warn")
    if on_unexpected not in _VALID_ON_UNEXPECTED:
        raise ValueError(
            f"framing.downlink.on_unexpected must be one of {_VALID_ON_UNEXPECTED}, "
            f"got {on_unexpected!r}"
        )

    return FramingSpec(
        uplink_chain=tuple(chain),
        uplink_label=label,
        accept_frame_types=tuple(str(x) for x in accept),
        on_unexpected=on_unexpected,
    )
