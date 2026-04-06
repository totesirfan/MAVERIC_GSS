"""
mav_gss_lib.protocols.frame_detect -- Frame Type Detection & Normalization

RX-direction utilities: detect outer framing type from gr-satellites
metadata and strip it to expose the inner CSP+payload.
"""


def detect_frame_type(meta):
    """Determine frame type from gr-satellites metadata."""
    tx_info = str(meta.get("transmitter", ""))
    for keyword, label in (("AX.25", "AX.25"), ("AX100", "ASM+GOLAY")):
        if keyword in tx_info:
            return label
    return "UNKNOWN"


def normalize_frame(frame_type, raw):
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
