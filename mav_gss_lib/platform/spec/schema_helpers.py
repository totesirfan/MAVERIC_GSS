"""Platform helpers for mission CommandOps.schema() implementations.

Inlining ArgumentType metadata (description, valid_range, valid_values)
into a flat per-arg dict is generic logic; centralizing it here keeps
mission wrappers thin and gives the public fixture mission a direct
test surface (so CI proves the inlining shape without needing the
gitignored MAVERIC mission.yml).
"""

from __future__ import annotations

from mav_gss_lib.platform.contract.commands import TxArgSchema

from .commands import MetaCommand
from .mission import Mission


def inline_argument_metadata(mission: Mission, meta: MetaCommand) -> list[TxArgSchema]:
    arg_types = mission.argument_types
    out: list[TxArgSchema] = []
    for a in meta.argument_list:
        t = arg_types.get(a.type_ref)
        type_desc = getattr(t, "description", "") if t is not None else ""
        out.append({
            "name": a.name,
            "type": a.type_ref,
            "description": a.description or type_desc,
            "important": a.important,
            "valid_range": (
                list(t.valid_range)
                if (t is not None and getattr(t, "valid_range", None) is not None)
                else None
            ),
            "valid_values": (
                list(t.valid_values)
                if (t is not None and getattr(t, "valid_values", None) is not None)
                else None
            ),
            # NOTE: no `unit` field. ArgumentType (TC side) intentionally
            # does not carry units — XTCE keeps engineering units on
            # ParameterType (TM side) only. If TC ever needs a display
            # unit (e.g. "ms" hint next to a duration arg), add a real
            # field to ArgumentType in a separate change AND extend the
            # TS shape in lib/types.ts at the same time.
        })
    return out


__all__ = ["inline_argument_metadata"]
