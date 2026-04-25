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

    def write_cmd_verifier(self, record: dict[str, Any]) -> None:
        """Write one cmd_verifier event (envelope-compatible with tx_command).

        Required keys in *record*:
          cmd_event_id, instance_id, stage, verifier_id, outcome, elapsed_ms,
          match_event_id (may be None), seq.
        The envelope (event_id, session_id, ts_ms, ts_iso, v, mission_id,
        operator, station, event_kind='cmd_verifier') is filled in here so the
        SQL archive can ingest cmd_verifier and tx_command rows with one
        schema.
        """
        from mav_gss_lib.platform._log_envelope import new_event_id, ts_iso
        import time as _time

        ts_ms = int(_time.time() * 1000)
        envelope: dict[str, Any] = {
            "event_id": new_event_id(),
            "event_kind": "cmd_verifier",
            "session_id": self.session_id,
            "ts_ms": ts_ms,
            "ts_iso": ts_iso(ts_ms),
            "seq": record.get("seq", 0),
            "v": self._version,
            "mission_id": self.mission_id,
            "operator": self._operator,
            "station": self._station,
        }
        envelope.update(record)
        envelope["event_kind"] = "cmd_verifier"  # guard — record must not override
        self.write_jsonl(envelope)
