"""mav_gss_lib.platform.framing -- Reusable wire-framing toolkit.

Generic wire primitives consumed by missions to compose an uplink stack:

    contract    Framer Protocol + FramerChain composer
    crc         CRC-16 XMODEM, CRC-32C Castagnoli (open standards)
    csp_v1      CSP v1 header + KISS framing + CSPv1Framer
    ax25        AX.25 UI header + HDLC/G3RUH/NRZI bitstream + Ax25Framer
    asm_golay   AX100 Mode 5 ASM+Golay over-the-air encoder + AsmGolayFramer

Missions reference framers by stable name via the FRAMERS registry and
compose chains via build_chain(). Per-mission choice (which framers, in
what order, with what operator config) stays in mission Python; the
platform owns the primitives + registry + composer.

The server backend may not import these directly — TX framing flows through
`MissionSpec.commands.frame()`. RX-side transport-metadata heuristics live in
``mav_gss_lib.platform.rx.frame_detect`` (they don't decode wire bytes,
they inspect gr-satellites metadata strings).
"""

from typing import Any, Callable

from mav_gss_lib.platform.framing.contract import Framer, FramerChain
from mav_gss_lib.platform.framing.crc import crc16, crc32c, verify_csp_crc32
from mav_gss_lib.platform.framing.csp_v1 import (
    FEND, FESC, TFEND, TFESC, kiss_wrap,
    try_parse_csp_v1, CSPConfig, CSPv1Framer,
)
from mav_gss_lib.platform.framing.ax25 import (
    AX25Config, ax25_decode_header, build_ax25_gfsk_frame, Ax25Framer,
)
from mav_gss_lib.platform.framing.asm_golay import (
    ASM, PREAMBLE, MAX_PAYLOAD, build_asm_golay_frame,
    ccsds_scrambler_sequence, golay_encode, rs_encode, AsmGolayFramer,
)


# ─── Registry + chain builder ───────────────────────────────────────────
#
# Each constructor accepts a single config dict and returns a Framer.
# Unknown keys are silently ignored — the framer's Config dataclass
# decides which keys it consumes. Missions compose chains by stable name
# via build_chain() rather than importing framer classes directly.

def _apply_config(target: Any, config: dict[str, Any]) -> Any:
    for k, v in config.items():
        if hasattr(target, k):
            setattr(target, k, v)
    return target


# Operator-facing keys (used in gss.yml + mission_cfg + mission.yml config_ref)
# differ from the framer's internal CSPConfig attribute names. Translation
# lives here at the registry boundary so every caller of build_chain (...)
# benefits — DeclarativeFramer doesn't need to know about it.
_CSP_OPERATOR_KEY_ALIASES = {
    "priority":    "prio",
    "source":      "src",
    "destination": "dest",
    "dest_port":   "dport",
    "src_port":    "sport",
}


def _normalize_csp_keys(config: dict[str, Any]) -> dict[str, Any]:
    return {_CSP_OPERATOR_KEY_ALIASES.get(k, k): v for k, v in config.items()}


def _make_csp_v1(config: dict[str, Any]) -> CSPv1Framer:
    return CSPv1Framer(_apply_config(CSPConfig(), _normalize_csp_keys(config)))


def _make_ax25(config: dict[str, Any]) -> Ax25Framer:
    return Ax25Framer(_apply_config(AX25Config(), config))


def _make_asm_golay(config: dict[str, Any]) -> AsmGolayFramer:
    return AsmGolayFramer()  # no operator-tunable params


FramerFactory = Callable[[dict[str, Any]], Framer]


FRAMERS: dict[str, FramerFactory] = {
    "csp_v1":    _make_csp_v1,
    "ax25":      _make_ax25,
    "asm_golay": _make_asm_golay,
}


def build_chain(spec: list[dict[str, Any]]) -> FramerChain:
    """Compose a FramerChain from an ordered list of {framer, config?} entries.

    ``framer`` names an entry in FRAMERS; the optional ``config`` dict is
    forwarded to that framer's constructor. Order is innermost-first.

    Example::

        chain = build_chain([
            {"framer": "csp_v1", "config": {"prio": 2, "src": 6, ...}},
            {"framer": "asm_golay"},
        ])
        wire = chain.frame(raw_cmd)
    """
    framers: list[Framer] = []
    for entry in spec:
        name = entry["framer"]
        if name not in FRAMERS:
            raise KeyError(
                f"unknown framer {name!r}; registered: {sorted(FRAMERS)}"
            )
        framers.append(FRAMERS[name](entry.get("config", {})))
    return FramerChain(framers)


from mav_gss_lib.platform.framing.declarative import DeclarativeFramer  # noqa: E402
