"""EPS HK extractor — decode eps_hk TLM packets into telemetry fragments.

Calls decode_eps_hk(cmd) directly from the mission's semantic decoder.
No dependency on mission_data["telemetry"] (that key is removed by
Task 10a). Each decoded TelemetryField becomes one TelemetryFragment
carrying engineering-unit value + unit string.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator

from mav_gss_lib.platform.telemetry import TelemetryFragment

from mav_gss_lib.missions.maveric.telemetry.semantics.eps import decode_eps_hk

if TYPE_CHECKING:
    from mav_gss_lib.missions.maveric.nodes import NodeTable


def extract(pkt: Any, nodes: "NodeTable", now_ms: int) -> Iterator[TelemetryFragment]:
    md = getattr(pkt, "mission_data", None) or {}
    cmd = md.get("cmd") or {}
    if cmd.get("cmd_id") != "eps_hk":
        return
    if nodes.ptype_name(md.get("ptype")) != "TLM":
        return
    try:
        fields = decode_eps_hk(cmd)
    except ValueError:
        # Short/malformed args_raw — log path still sees cmd; canonical
        # state simply gets no EPS fragments from this packet.
        return
    for f in fields:
        yield TelemetryFragment(
            "eps", f.name, f.value, now_ms, unit=f.unit,
        )
