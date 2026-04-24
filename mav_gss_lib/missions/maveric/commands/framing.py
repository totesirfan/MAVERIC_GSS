"""MAVERIC wire framing — CSP + AX.25 / ASM+Golay.

MAVERIC owns its uplink stack end-to-end. The platform hands the mission an
`EncodedCommand.raw` (inner command bytes) and expects a `FramedCommand.wire`
back — the exact bytes to publish on ZMQ. This module performs the CSP wrap
plus the selected outer framing (AX.25 HDLC/GFSK or ASM+Golay/RS) and emits
structured log hooks the platform TX log merges into the per-command record.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mav_gss_lib.platform import EncodedCommand, FramedCommand
from mav_gss_lib.protocols.ax25 import AX25Config, build_ax25_gfsk_frame
from mav_gss_lib.protocols.csp import CSPConfig

try:
    from mav_gss_lib.protocols.golay import MAX_PAYLOAD as GOLAY_MAX_PAYLOAD
    from mav_gss_lib.protocols.golay import _GR_RS_OK, build_asm_golay_frame
except ImportError:  # pragma: no cover - libfec optional
    GOLAY_MAX_PAYLOAD = 223
    _GR_RS_OK = False

    def build_asm_golay_frame(_data: bytes) -> bytes:  # type: ignore[misc]
        raise RuntimeError("ASM+Golay requested but libfec is unavailable")


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

    def max_wire_payload(self) -> int | None:
        """Return the admission ceiling (post-framing) or None for unlimited."""
        if self.uplink_mode == "ASM+Golay":
            return GOLAY_MAX_PAYLOAD
        return None

    def frame(self, encoded: EncodedCommand) -> FramedCommand:
        raw_cmd = encoded.raw
        csp_packet = self.csp.wrap(raw_cmd)
        assert len(csp_packet) >= len(raw_cmd), \
            f"CSP shrank payload: {len(csp_packet)} < {len(raw_cmd)}"

        if self.uplink_mode == "ASM+Golay":
            if not _GR_RS_OK:
                raise RuntimeError(
                    "ASM+Golay selected but libfec RS encoder is unavailable in this "
                    "environment. Install libfec (e.g. `sudo apt install libfec-dev && "
                    "sudo ldconfig`, `conda install -c ryanvolz libfec`, or build from "
                    "https://github.com/quiet/libfec) or switch tx.uplink_mode to AX.25."
                )
            if len(csp_packet) > GOLAY_MAX_PAYLOAD:
                raise ValueError(
                    f"command too large for ASM+Golay RS payload "
                    f"({len(csp_packet)}B > {GOLAY_MAX_PAYLOAD}B)"
                )
            wire = build_asm_golay_frame(csp_packet)
        else:
            ax25_packet = self.ax25.wrap(csp_packet)
            wire = build_ax25_gfsk_frame(ax25_packet)

        assert len(wire) > len(csp_packet), \
            f"framer produced suspiciously small wire: {len(wire)}B ≤ csp {len(csp_packet)}B"
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
