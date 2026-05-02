"""MAVERIC's /api/schema extension fields.

The platform `CommandSchemaItem` is mission-agnostic. MAVERIC adds
CSP-style routing fields (dest/echo/ptype) and node-directory hints
(nodes) here. The TypedDict subclass keeps Required/NotRequired
inherited from the platform base; new fields are NotRequired since
not every command has a fixed dest (some are operator-routable).
"""

from __future__ import annotations

from typing import NotRequired

from mav_gss_lib.platform.contract.commands import CommandSchemaItem


class MavericCommandSchemaItem(CommandSchemaItem):
    """MAVERIC routing extension on top of the platform contract.

    `dest`/`echo`/`ptype` are CSP-style routing fields; `nodes` is the
    list of allowed dest names for the operator UI. None/absent means
    'operator chooses' (no fixed routing constraint).
    """
    dest: NotRequired[str | None]
    echo: NotRequired[str | None]
    ptype: NotRequired[str | None]
    nodes: NotRequired[list[str]]


__all__ = ["MavericCommandSchemaItem"]
