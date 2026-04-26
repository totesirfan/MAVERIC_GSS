"""One-shot migration from the legacy logging schema to the unified envelope.

Reads every ``<log_dir>/json/*.jsonl`` and writes an equivalent file under
``<log_dir>/json.v2/`` in the new shape. Does not touch the original files;
the operator reviews ``json.v2/`` and swaps the directories manually when
satisfied.

Shape changes:
  * RX records (identified by the legacy ``pkt`` key):
      - Renamed keys:  pkt -> seq, gs_ts -> ts_iso (+ derived ts_ms),
                       raw_hex -> wire_hex, payload_hex -> inner_hex,
                       raw_len -> wire_len, payload_len -> inner_len,
                       mission_log -> mission (always present)
      - Dropped keys:  _rendering, mission_name, telemetry (flattened out)
      - Added keys:    event_id, event_kind="rx_packet", session_id, mission_id
      - Each entry in the legacy ``telemetry`` array becomes its own
        ``event_kind="parameter"`` record with a ``rx_event_id`` back-pointer.

  * TX records (identified by the legacy ``type == "mission_cmd"`` marker):
      - Renamed keys:  n -> seq, ts -> ts_iso (+ derived ts_ms),
                       raw_hex -> inner_hex, raw_len -> inner_len,
                       hex -> wire_hex, len -> wire_len
      - Lifted to top-level from mission_payload: cmd_id, dest, src, echo, ptype
      - Mission-owned content (display, payload, ax25, csp, ...) folded
        under the single ``mission`` sub-dict.
      - Added keys:    event_id, event_kind="tx_command", session_id, mission_id

Usage::

    python3 scripts/migrate_logs.py <log_dir>
    python3 scripts/migrate_logs.py <log_dir> --mission-id maveric

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _parse_ts_ms(raw: str | int | None) -> int:
    """Best-effort parse of legacy ts string into millisecond epoch.

    Accepts ISO 8601 ("2026-04-21T15:52:21+00:00") and the legacy
    space-separated form with a TZ abbrev ("2026-04-21 15:52:21 PDT").
    Falls back to 0 on unparseable input so migration does not abort —
    the caller stamps ``ts_iso(0)`` (``1970-01-01T00:00:00.000+00:00``)
    so the unified envelope's non-empty-``ts_iso`` contract still holds
    and SQL ingest flags the row rather than rejecting the batch."""
    if isinstance(raw, int):
        return raw
    if not raw:
        return 0
    s = str(raw).strip()
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f %Z",
        "%Y-%m-%d %H:%M:%S %Z",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
    return 0


def _ts_iso(ms: int) -> str:
    return (
        datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
    )


def _new_event_id() -> str:
    return uuid.uuid4().hex


def _is_rx_record(entry: dict) -> bool:
    return "pkt" in entry


def _is_tx_record(entry: dict) -> bool:
    return entry.get("type") == "mission_cmd" or "n" in entry


def _normalize_mission_block(block: dict) -> dict:
    """Bring legacy mission-block quirks in line with the new writer's output.

    - ``csp_crc32.received`` is emitted as an integer by the live writer
      (``mav_gss_lib/missions/maveric/ui/log_format.py``); the legacy
      on-disk form was a 0x-prefixed hex string. Coerce to int so SQL
      ingest sees a consistent numeric column.
    """
    crc = block.get("csp_crc32")
    if isinstance(crc, dict):
        recv = crc.get("received")
        if isinstance(recv, str) and recv.startswith("0x"):
            try:
                crc["received"] = int(recv, 16)
            except ValueError:
                pass
    return block


def _migrate_rx(entry: dict, *, session_id: str, mission_id: str) -> list[dict]:
    ts_ms = _parse_ts_ms(entry.get("gs_ts") or entry.get("ts"))
    event_id = _new_event_id()
    mission_block = entry.get("mission_log") or entry.get("mission") or {}
    envelope_common = {
        "session_id": session_id,
        "ts_ms": ts_ms,
        "ts_iso": _ts_iso(ts_ms),
        "seq": entry.get("pkt", 0),
        "v": entry.get("v", ""),
        "mission_id": mission_id or entry.get("mission", ""),
        "operator": entry.get("operator", ""),
        "station": entry.get("station", ""),
    }
    rx_packet = {
        "event_id": event_id,
        "event_kind": "rx_packet",
        **envelope_common,
        "frame_type": entry.get("frame_type", ""),
        "transport_meta": entry.get("tx_meta", ""),
        "wire_hex": entry.get("raw_hex", ""),
        "wire_len": entry.get("raw_len", 0),
        "inner_hex": entry.get("payload_hex", ""),
        "inner_len": entry.get("payload_len", 0),
        "duplicate": bool(entry.get("duplicate", False)),
        "uplink_echo": bool(entry.get("uplink_echo", False)),
        "unknown": bool(entry.get("unknown", False)),
        "warnings": list(entry.get("warnings") or []),
        "mission": _normalize_mission_block(
            {k: v for k, v in mission_block.items() if k != "fragments"}
        ),
    }
    out: list[dict] = [rx_packet]

    telemetry_source = entry.get("telemetry") or []
    if not telemetry_source and isinstance(mission_block, dict):
        telemetry_source = mission_block.get("fragments") or []

    for frag in telemetry_source:
        if not isinstance(frag, dict):
            continue
        frag_ts = frag.get("ts_ms") or ts_ms
        domain = frag.get("domain") or ""
        key = frag.get("key") or ""
        name = f"{domain}.{key}" if domain else key
        out.append({
            "event_id": _new_event_id(),
            "event_kind": "parameter",
            **{**envelope_common, "ts_ms": frag_ts, "ts_iso": _ts_iso(frag_ts)},
            "rx_event_id": event_id,
            "name": name,
            "value": frag.get("value"),
            "unit": frag.get("unit", ""),
            "display_only": bool(frag.get("display_only", False)),
        })
    return out


def _migrate_tx(entry: dict, *, session_id: str, mission_id: str) -> dict:
    ts_ms = _parse_ts_ms(entry.get("ts"))
    mission_payload = entry.get("mission_payload") or {}
    display = entry.get("display") or {}
    # Everything carried by the old framer's log_fields lived flat at the
    # top level alongside the envelope. Fold it under `mission` now.
    legacy_extras = {
        k: v for k, v in entry.items()
        if k not in {
            "n", "ts", "type", "operator", "station",
            "display", "mission_payload",
            "raw_hex", "raw_len", "hex", "len",
            "frame_label", "uplink_mode",
        }
    }
    mission_block: dict = {"display": display, "payload": mission_payload}
    mission_block.update(legacy_extras)

    # Legacy v1 records carried both `frame_label` and `uplink_mode` with the
    # same value. Canonicalize to `frame_label` and drop the alias entirely.
    frame_label = entry.get("frame_label") or entry.get("uplink_mode", "")

    return {
        "event_id": _new_event_id(),
        "event_kind": "tx_command",
        "session_id": session_id,
        "ts_ms": ts_ms,
        "ts_iso": _ts_iso(ts_ms),
        "seq": entry.get("n", 0),
        "v": entry.get("v", ""),
        "mission_id": mission_id,
        "operator": entry.get("operator", ""),
        "station": entry.get("station", ""),
        "cmd_id": str(mission_payload.get("cmd_id", "")),
        "dest": str(mission_payload.get("dest", "")),
        "src": str(mission_payload.get("src", "")),
        "echo": str(mission_payload.get("echo", "")),
        "ptype": str(mission_payload.get("ptype", "")),
        "frame_label": frame_label,
        "inner_hex": entry.get("raw_hex", ""),
        "inner_len": entry.get("raw_len", 0),
        "wire_hex": entry.get("hex", ""),
        "wire_len": entry.get("len", 0),
        "mission": mission_block,
    }


def _migrate_telemetry_to_parameter(record: dict) -> dict:
    """Rename ``event_kind: "telemetry"`` → ``"parameter"`` and collapse fields.

    Collapses ``domain`` + ``key`` into the qualified ``name`` field used by
    the current writer.  Envelope fields (``event_id``, ``session_id``,
    ``ts_ms``, ``ts_iso``, ``seq``, ``v``, ``mission_id``, ``operator``,
    ``station``, ``rx_event_id``) and ``value`` / ``unit`` / ``display_only``
    are unchanged.  Records that are not ``event_kind: "telemetry"`` are
    returned as-is.
    """
    if record.get("event_kind") != "telemetry":
        return record
    domain = record.get("domain") or ""
    key = record.get("key") or ""
    name = f"{domain}.{key}" if domain else key
    out = dict(record)
    out["event_kind"] = "parameter"
    out["name"] = name
    out.pop("domain", None)
    out.pop("key", None)
    return out


def migrate_entry(entry: dict, *, session_id: str, mission_id: str) -> Iterable[dict]:
    if _is_rx_record(entry):
        return _migrate_rx(entry, session_id=session_id, mission_id=mission_id)
    if _is_tx_record(entry):
        return [_migrate_tx(entry, session_id=session_id, mission_id=mission_id)]
    # Already new-shape records: apply any pending renames then pass through.
    if "event_kind" in entry:
        return [_migrate_telemetry_to_parameter(entry)]
    return []


def migrate_file(src: Path, dst: Path, *, mission_id: str) -> tuple[int, int, int]:
    """Migrate one legacy jsonl file. Returns (in_count, out_count, skipped)."""
    session_id = src.stem
    out_lines: list[str] = []
    in_count = 0
    out_count = 0
    skipped = 0
    with open(src) as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            in_count += 1
            for new in migrate_entry(entry, session_id=session_id, mission_id=mission_id):
                out_lines.append(json.dumps(new))
                out_count += 1
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(out_lines) + ("\n" if out_lines else ""))
    return in_count, out_count, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log_dir", type=Path,
                        help="base log_dir containing json/ (the script "
                             "writes to json.v2/ at the same level)")
    parser.add_argument("--mission-id", default="maveric",
                        help="mission_id to stamp on records that lack one "
                             "(legacy RX records carry it in the 'mission' "
                             "field; TX records do not). Default: maveric.")
    args = parser.parse_args(argv)

    src_dir = args.log_dir / "json"
    dst_dir = args.log_dir / "json.v2"
    if not src_dir.is_dir():
        print(f"no source directory: {src_dir}", file=sys.stderr)
        return 2

    total_in = 0
    total_out = 0
    total_skipped = 0
    for src in sorted(src_dir.glob("*.jsonl")):
        dst = dst_dir / src.name
        in_count, out_count, skipped = migrate_file(src, dst, mission_id=args.mission_id)
        total_in += in_count
        total_out += out_count
        total_skipped += skipped
        skip_note = f"  [{skipped} malformed lines skipped]" if skipped else ""
        print(f"{src.name}: {in_count} -> {out_count}{skip_note}")

    print(f"\ntotal: {total_in} legacy records -> {total_out} unified events")
    if total_skipped:
        print(f"warning: {total_skipped} malformed lines were skipped "
              f"(unparseable JSON) — review source files before swapping")
    print(f"output: {dst_dir}")
    print("review, then swap: mv json json.v1 && mv json.v2 json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
