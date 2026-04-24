"""TX session log — JSONL + text entries for outbound mission commands.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from typing import Any

from mav_gss_lib.constants import DEFAULT_MISSION_NAME
from mav_gss_lib.textutil import clean_text

from ._base import _BaseLog


class TXLog(_BaseLog):
    """TX session log — JSONL (tx_command events) + text.

    The JSONL record is built by ``mav_gss_lib.platform.tx.logging.tx_log_record``
    (also re-exported from ``mav_gss_lib.platform`` for convenience) and
    handed in pre-assembled; this writer just persists it and formats the
    human-readable text entry around the same inputs.
    """

    def __init__(
        self,
        log_dir: str,
        zmq_addr: str,
        version: str = "",
        mission_name: str = DEFAULT_MISSION_NAME,
        *,
        mission_id: str = "",
        station: str = "",
        operator: str = "",
        host: str = "",
    ) -> None:
        super().__init__(log_dir, "uplink", version, "TX Dashboard", zmq_addr,
                         mission_name=mission_name, mission_id=mission_id,
                         station=station, operator=operator, host=host)

    def write_mission_command(
        self,
        record: dict[str, Any],
        *,
        raw_cmd: bytes,
        wire: bytes,
        log_text: list[str] | None = None,
    ) -> None:
        """Write one mission-built TX command entry.

        *record* is the pre-built envelope from
        ``mav_gss_lib.platform.tx.logging.tx_log_record``.
        *raw_cmd* and *wire* are the inner command bytes and the full wire
        frame — both are re-needed here for the text-log hex blocks.
        *log_text* is the mission framer's banner lines (from
        ``FramedCommand.log_text``), inserted verbatim between the command
        header and the hex dumps.
        """
        self.write_jsonl(record)

        display = record["mission"]["display"]
        title = display.get("title", "?")
        subtitle = display.get("subtitle", "")
        frame_label = record.get("frame_label", "")
        ts_ms = record["ts_ms"]
        n = record["seq"]

        lines = [self._separator(f"#{n}", subtitle, ts_ms=ts_ms)]
        if frame_label:
            lines.append(self._field("MODE", frame_label))
        lines.append(self._field("COMMAND", title))
        for block in display.get("detail_blocks", []):
            for field in block.get("fields", []):
                lines.append(self._field(field["name"].upper(), str(field["value"])))
        lines.extend(log_text or [])
        lines.extend(self._hex_lines(raw_cmd, "RAW CMD"))
        lines.extend(self._hex_lines(wire, "FULL HEX"))
        ascii_text = clean_text(raw_cmd)
        if ascii_text:
            lines.append(self._field("ASCII", ascii_text))

        self._write_entry(lines)
