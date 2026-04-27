"""DeclarativeFramer — generic mission framer driven by a FramingSpec.

Reads its uplink chain from a FramingSpec (parsed at boot from
mission.yml) and builds a FramerChain per send. Resolves ``config_ref``
entries against a live ``mission_cfg`` mapping so operator edits to
bound sections (e.g. csp.*) propagate to the next send without a
MissionSpec rebuild.

Operator-friendly key translation (priority -> prio, etc.) is handled
by the FRAMERS registry, so the resolved config is forwarded as-is.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from typing import Any, Mapping

from mav_gss_lib.platform.contract.commands import EncodedCommand, FramedCommand
from mav_gss_lib.platform.framing import build_chain
from mav_gss_lib.platform.framing.protocol import FramerChain
from mav_gss_lib.platform.spec.framing import FramerSpec, FramingSpec


_LABEL_WIDTH = 10


class DeclarativeFramer:
    """Mission-agnostic framer driven by a FramingSpec.

    `mission_cfg` is captured by reference; each frame() call reads its
    current state, so /api/config edits to bound sections take effect on
    the next send.
    """

    __slots__ = ("_spec", "_mission_cfg")

    def __init__(self, spec: FramingSpec, mission_cfg: Mapping[str, Any]) -> None:
        self._spec = spec
        self._mission_cfg = mission_cfg

    def frame(self, encoded: EncodedCommand) -> FramedCommand:
        chain = self._build_chain()
        wire = chain.frame(encoded.raw)
        label = self._spec.uplink_label or chain.frame_label or "raw"
        # The label flows through FramedCommand.frame_label — the dedicated
        # field on the platform contract. log_fields carries only chain
        # metadata (CSP headers etc.); we don't smuggle the label through
        # both channels.
        log_fields: dict[str, Any] = chain.log_fields()
        log_text: list[str] = [_field_line("MODE", label), *chain.log_lines()]
        log_text.append(_field_line(
            "SIZE",
            f"{len(wire)}B (cmd {len(encoded.raw)}B + framing {chain.overhead()}B)",
        ))
        return FramedCommand(
            wire=wire,
            frame_label=label,
            max_payload=chain.max_payload(),
            log_fields=log_fields,
            log_text=log_text,
        )

    def _build_chain(self) -> FramerChain:
        return build_chain([self._resolve(e) for e in self._spec.uplink_chain])

    def _resolve(self, e: FramerSpec) -> dict[str, Any]:
        # Static `config:` overrides config_ref values — explicit wins.
        config: dict[str, Any] = {}
        if e.config_ref:
            section = self._mission_cfg.get(e.config_ref)
            if isinstance(section, Mapping):
                config.update(section)
        config.update(e.config)
        return {"framer": e.framer, "config": config}


def _field_line(label: str, value: str) -> str:
    return f"  {label:<{_LABEL_WIDTH}} {value}"
