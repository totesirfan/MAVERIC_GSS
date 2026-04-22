"""GNC RES extractor — decode RES packets into gnc-domain telemetry fragments.

Calls decode_from_cmd(cmd) directly from semantics/gnc_handlers.py. No
dependency on mission_data["gnc_registers"] (that key is removed by
Task 10a). Unit travels on each fragment so the log formatter reads
f["unit"] uniformly across domains.
"""
from __future__ import annotations

from mav_gss_lib.web_runtime.telemetry import TelemetryFragment
from mav_gss_lib.missions.maveric.telemetry.semantics.gnc_handlers import decode_from_cmd


def extract(pkt, nodes, now_ms: int):
    md = getattr(pkt, "mission_data", None) or {}
    cmd = md.get("cmd") or {}
    if nodes.ptype_name(md.get("ptype")) != "RES":
        return
    regs = decode_from_cmd(cmd)
    if not regs:
        return
    for name, snap in regs.items():
        if not snap.get("decode_ok"):
            continue
        # snap["unit"] is populated by decode_register() in gnc_schema.py
        # from RegisterDef.unit. Structured registers without a meaningful
        # scalar unit store "" — the log formatter appends nothing when
        # unit is empty, so structured registers still render correctly.
        yield TelemetryFragment(
            "gnc", name, snap.get("value"), now_ms,
            unit=snap.get("unit", ""),
        )
