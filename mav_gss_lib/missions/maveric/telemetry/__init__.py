"""MAVERIC mission telemetry decoders.

Public surface: decode_telemetry(cmd) -> dict | None.

The registry is keyed by (cmd_id, pkt_type). Each entry carries a
`hide_schema_args` flag that gates whether the decoder's raw schema-
parsed args are hidden in all three views (RX row, detail block,
text log). Default False — only opt in when the schema rendering
produces garbage (e.g. binary args mis-rendered as ASCII for eps_hk).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .types import TelemetryField
from .eps import decode_eps_hk


_PTYPE_TLM = 4  # maveric mission.yml: 4 = TLM


@dataclass(frozen=True, slots=True)
class _Entry:
    fn: Callable[[dict], list[TelemetryField]]
    hide_schema_args: bool = False


_REGISTRY: dict[tuple[str, int], _Entry] = {
    # eps_hk: args_raw is 96 bytes of binary int16. The schema parses
    # it as ASCII-space-split garbage extra_args — hide it everywhere
    # in favor of the decoded HK fields.
    ("eps_hk", _PTYPE_TLM): _Entry(fn=decode_eps_hk, hide_schema_args=True),
}


def decode_telemetry(cmd: dict) -> dict | None:
    """Return {cmd_id, fields, hide_schema_args} or None if no decoder.

    The returned dict is what rx_ops stores in mission_data["telemetry"];
    rendering.py and log_format.py read it directly.
    """
    key = (cmd.get("cmd_id"), cmd.get("pkt_type"))
    entry = _REGISTRY.get(key)
    if entry is None:
        return None
    fields = entry.fn(cmd)
    return {
        "cmd_id": cmd["cmd_id"],
        "fields": [f.to_dict() for f in fields],
        "hide_schema_args": entry.hide_schema_args,
    }


__all__ = ["decode_telemetry", "TelemetryField"]
