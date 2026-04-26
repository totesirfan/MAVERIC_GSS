"""MAVERIC wire framing — composes platform-provided framers.

MAVERIC owns its uplink stack end-to-end. The platform hands the mission an
`EncodedCommand.raw` (inner command bytes) and expects a `FramedCommand.wire`
back — the exact bytes to publish on ZMQ. This module is a thin composer:

    raw_cmd
      → CSPv1Framer (mission-configured src/dest/ports/CRC)
      → AsmGolayFramer  | Ax25Framer
      = wire

Byte-level framing lives in `mav_gss_lib.platform.framing.*`. This module
binds operator/mission config values into Framer instances and assembles
the per-send `FramerChain`.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mav_gss_lib.platform import EncodedCommand, FramedCommand
from mav_gss_lib.platform.framing import (
    AX25Config,
    CSPConfig,
    FramerChain,
    MAX_PAYLOAD as ASM_GOLAY_MAX_PAYLOAD,
    build_chain,
)


_AX25_FIELDS = [
    ("src_call", "src_call"),
    ("src_ssid", "src_ssid", int),
    ("dest_call", "dest_call"),
    ("dest_ssid", "dest_ssid", int),
]

_CSP_FIELDS = [
    ("priority", "prio", int),
    ("source", "src", int),
    ("destination", "dest", int),
    ("dest_port", "dport", int),
    ("src_port", "sport", int),
    ("flags", "flags", int),
    ("csp_crc", "csp_crc", bool),
]


def _populate(section: dict[str, Any], target: Any, mapping: list[tuple[Any, ...]]) -> None:
    for cfg_key, attr, *rest in mapping:
        if cfg_key not in section:
            continue
        value = section[cfg_key]
        setattr(target, attr, rest[0](value) if rest else value)


def _build_ax25(mission_cfg: dict[str, Any]) -> AX25Config:
    ax25 = AX25Config()
    section = mission_cfg.get("ax25")
    if isinstance(section, dict):
        _populate(section, ax25, _AX25_FIELDS)
    return ax25


def _build_csp(mission_cfg: dict[str, Any]) -> CSPConfig:
    csp = CSPConfig()
    section = mission_cfg.get("csp")
    if isinstance(section, dict):
        _populate(section, csp, _CSP_FIELDS)
    return csp


@dataclass(frozen=True, slots=True)
class MavericFramer:
    """Snapshot framer: built from the current mission_cfg at send time.

    The framer copies AX.25 + CSP config values out of `mission_cfg` at
    construction so two concurrent send paths don't race on config updates
    mid-frame.
    """

    uplink_mode: str
    ax25: AX25Config
    csp: CSPConfig

    @classmethod
    def from_mission_config(
        cls,
        mission_cfg: dict[str, Any],
        *,
        uplink_mode: str,
    ) -> "MavericFramer":
        return cls(
            uplink_mode=uplink_mode,
            ax25=_build_ax25(mission_cfg),
            csp=_build_csp(mission_cfg),
        )

    def _build_chain(self) -> FramerChain:
        csp_cfg = {
            "enabled": self.csp.enabled,
            "prio": self.csp.prio, "src": self.csp.src, "dest": self.csp.dest,
            "dport": self.csp.dport, "sport": self.csp.sport,
            "flags": self.csp.flags, "csp_crc": self.csp.csp_crc,
        }
        if self.uplink_mode == "ASM+Golay":
            return build_chain([
                {"framer": "csp_v1", "config": csp_cfg},
                {"framer": "asm_golay"},
            ])
        ax25_cfg = {
            "enabled": self.ax25.enabled,
            "src_call": self.ax25.src_call, "src_ssid": self.ax25.src_ssid,
            "dest_call": self.ax25.dest_call, "dest_ssid": self.ax25.dest_ssid,
        }
        return build_chain([
            {"framer": "csp_v1", "config": csp_cfg},
            {"framer": "ax25", "config": ax25_cfg},
        ])

    def max_wire_payload(self) -> int | None:
        """Inner-CSP-packet ceiling (post-CSP-wrap) or None for unlimited."""
        if self.uplink_mode == "ASM+Golay":
            return ASM_GOLAY_MAX_PAYLOAD
        return None

    def frame(self, encoded: EncodedCommand) -> FramedCommand:
        raw_cmd = encoded.raw
        chain = self._build_chain()
        wire = chain.frame(raw_cmd)
        return FramedCommand(
            wire=wire,
            frame_label=self.uplink_mode,
            max_payload=self.max_wire_payload(),
            log_fields=self._log_fields(),
            log_text=self._log_text(raw_cmd, wire),
        )

    # -- logging hooks ---------------------------------------------------------

    def _log_fields(self) -> dict[str, Any]:
        """JSONL-safe mission metadata embedded in each TX log record."""
        fields: dict[str, Any] = {"uplink_mode": self.uplink_mode}
        if self.ax25.enabled:
            fields["ax25"] = {
                "src_call": self.ax25.src_call,
                "src_ssid": int(self.ax25.src_ssid),
                "dest_call": self.ax25.dest_call,
                "dest_ssid": int(self.ax25.dest_ssid),
            }
        if self.csp.enabled:
            fields["csp"] = {
                "prio": int(self.csp.prio),
                "src": int(self.csp.src),
                "dest": int(self.csp.dest),
                "dport": int(self.csp.dport),
                "sport": int(self.csp.sport),
                "flags": int(self.csp.flags),
                "csp_crc": bool(self.csp.csp_crc),
            }
        return fields

    def _log_text(self, raw_cmd: bytes, wire: bytes) -> list[str]:
        """Pre-formatted banner lines the TX log prints under the command."""
        lines: list[str] = [_field_line("MODE", self.uplink_mode)]
        if self.uplink_mode != "ASM+Golay" and self.ax25.enabled:
            lines.append(_field_line(
                "AX.25",
                f"Src:{self.ax25.src_call}-{self.ax25.src_ssid}  "
                f"Dest:{self.ax25.dest_call}-{self.ax25.dest_ssid}",
            ))
        if self.csp.enabled:
            csp = self.csp
            lines.append(_field_line(
                "CSP",
                f"Prio:{csp.prio} Src:{csp.src}({csp.sport}) "
                f"Dest:{csp.dest}({csp.dport}) Flags:0x{csp.flags:02X}",
            ))
        csp_overhead = self.csp.overhead()
        if self.uplink_mode == "ASM+Golay":
            lines.append(_field_line(
                "SIZE",
                f"{len(wire)}B (cmd {len(raw_cmd)}B + CSP {csp_overhead}B)",
            ))
        else:
            ax25_overhead = self.ax25.overhead()
            lines.append(_field_line(
                "SIZE",
                f"{len(wire)}B (cmd {len(raw_cmd)}B + CSP {csp_overhead}B "
                f"+ AX.25 {ax25_overhead}B)",
            ))
        return lines


_LABEL_WIDTH = 10


def _field_line(label: str, value: str) -> str:
    return f"  {label:<{_LABEL_WIDTH}} {value}"
