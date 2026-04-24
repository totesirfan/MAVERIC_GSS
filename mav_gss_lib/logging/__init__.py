"""File-based session logging for the ground station.

Two thin subclasses of `_BaseLog`, one per direction:

    session.py — SessionLog (RX) — rx_packet + telemetry events
    tx.py      — TXLog (TX)      — tx_command events
    _base.py   — shared I/O, background writer thread, rotation, rename,
                 ``session_id`` (file stem) stamped onto every record

JSONL records use the unified envelope (`event_id`, `event_kind`,
`session_id`, `ts_ms`, `ts_iso`, `seq`, `v`, `mission_id`, `operator`,
`station`) so SQL ingest sees one schema across RX and TX. The platform
builds records in ``mav_gss_lib.platform.rx.logging`` (RX) and
``mav_gss_lib.platform.tx.logging`` (TX); the writers here are
format-agnostic — they just persist whatever envelope the platform hands
them and assemble the human-readable text entry around it.

Four files per session live under ``<log_dir>/json/`` and
``<log_dir>/text/``: ``downlink_<ts>_<station>_<op>.{jsonl,txt}`` +
``uplink_<ts>_<station>_<op>.{jsonl,txt}``.

Author:  Irfan Annuar - USC ISI SERC
"""

from .session import SessionLog
from .tx import TXLog

__all__ = ["SessionLog", "TXLog"]
