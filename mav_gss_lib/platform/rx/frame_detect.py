"""Frame-type detection from gr-satellites transport metadata.

RX-direction utilities that look only at the PDU metadata (tx_info string)
and raw bytes — no mission-specific wire-format knowledge lives here. Both
the server (for pre-pipeline noise drops) and the active mission (for its
``PacketOps.normalize`` step) consume these helpers, so the module lives on
the platform side of the boundary.

Author:  Irfan Annuar - USC ISI SERC
"""


from __future__ import annotations

from typing import Any


def detect_frame_type(meta: dict[str, Any]) -> str:
    """Determine frame type from gr-satellites metadata."""
    tx_info = str(meta.get("transmitter", ""))
    for keyword, label in (("AX.25", "AX.25"), ("AX100", "ASM+GOLAY")):
        if keyword in tx_info:
            return label
    return "UNKNOWN"


def normalize_frame(frame_type: str, raw: bytes) -> tuple[bytes, str | None, list[str]]:
    """Strip outer framing, return (inner_payload, stripped_header_hex, warnings)."""
    warnings = []
    if frame_type == "AX.25":
        idx = raw.find(b"\x03\xf0")
        if idx == -1:
            warnings.append("AX.25 frame but no 03 f0 delimiter found")
            return raw, None, warnings
        return raw[idx + 2:], raw[:idx + 2].hex(" "), warnings
    if frame_type != "ASM+GOLAY":
        warnings.append("Unknown frame type -- returning raw")
    return raw, None, warnings


def is_noise_frame(frame_type: str, raw: bytes) -> bool:
    """True if this PDU is gr-satellites AX.25 noise that should be dropped.

    Detects one specific class: an AX.25-tagged frame whose payload
    contains no 03 F0 UI control+PID byte pair anywhere. A valid AX.25
    UI frame always carries these bytes at offsets 14-15 (after the
    16-byte address header), so the check cannot reject real traffic.
    """
    if frame_type != "AX.25":
        return False
    return raw.find(b"\x03\xf0") == -1
