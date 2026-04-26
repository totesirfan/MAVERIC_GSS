"""Mission UI capability — how a mission renders its packets and TX queue.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from typing import Any, Protocol

from .packets import PacketEnvelope
from .rendering import ColumnDef, PacketRendering


class UiOps(Protocol):
    def packet_columns(self) -> list[ColumnDef]: ...

    def render_packet(self, packet: PacketEnvelope) -> PacketRendering: ...

    def render_log_data(self, packet: PacketEnvelope) -> dict[str, Any]: ...

    def format_text_log(self, packet: PacketEnvelope) -> list[str]: ...
