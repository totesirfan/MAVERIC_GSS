#!/usr/bin/env python3
"""Migrate old TX log entries to the Phase 5b display rendering contract.

Old format:  {n, ts, src, src_lbl, dest, dest_lbl, echo, echo_lbl,
              ptype, ptype_lbl, cmd, args, raw_hex, ...}
New format:  {n, ts, type: "mission_cmd", uplink_mode, display: {
              title, subtitle, row, detail_blocks}, mission_payload,
              raw_hex, raw_len, hex, len}

Reads each JSONL TX log file, converts old entries in-place, and
writes back. New-format entries are left unchanged.

Usage:
    python3 scripts/migrate_tx_logs.py [log_dir]

    log_dir defaults to logs/json/ relative to the repo root.
"""

import json
import sys
from pathlib import Path


def migrate_entry(entry: dict) -> dict:
    """Convert one old-format TX log entry to the new display contract."""
    if entry.get("type") == "mission_cmd" and "display" in entry:
        # Already new format — check if display has row + detail_blocks
        display = entry["display"]
        if "row" in display and "detail_blocks" in display:
            return entry
        # Has display but missing row/detail_blocks (Phase 5 transitional)
        # Backfill from display.fields if present
        if "fields" in display:
            row = {}
            for f in display["fields"]:
                name_lower = f["name"].lower()
                if name_lower == "src":
                    row["src"] = f["value"]
                elif name_lower == "dest":
                    row["dest"] = f["value"]
                elif name_lower == "echo":
                    row["echo"] = f["value"]
                elif name_lower == "type":
                    row["ptype"] = f["value"]
            row.setdefault("cmd", display.get("title", ""))
            display["row"] = row
            routing_fields = [f for f in display["fields"] if f["name"] in ("Src", "Dest", "Echo", "Type")]
            arg_fields = [f for f in display["fields"] if f["name"] not in ("Src", "Dest", "Echo", "Type")]
            blocks = []
            if routing_fields:
                blocks.append({"kind": "routing", "label": "Routing", "fields": routing_fields})
            if arg_fields:
                blocks.append({"kind": "args", "label": "Arguments", "fields": arg_fields})
            display["detail_blocks"] = blocks
            display.pop("fields", None)
        return entry

    # Old format — build display from flat fields
    src_lbl = str(entry.get("src_lbl", entry.get("src", "")))
    dest_lbl = str(entry.get("dest_lbl", entry.get("dest", "")))
    echo_lbl = str(entry.get("echo_lbl", entry.get("echo", "")))
    ptype_lbl = str(entry.get("ptype_lbl", entry.get("ptype", "")))
    cmd = str(entry.get("cmd", ""))
    args = str(entry.get("args", ""))

    row = {
        "src": src_lbl,
        "dest": dest_lbl,
        "echo": echo_lbl,
        "ptype": ptype_lbl,
        "cmd": f"{cmd} {args}".strip() if args else cmd,
    }

    routing_block = {"kind": "routing", "label": "Routing", "fields": [
        {"name": "Src", "value": src_lbl},
        {"name": "Dest", "value": dest_lbl},
        {"name": "Echo", "value": echo_lbl},
        {"name": "Type", "value": ptype_lbl},
    ]}

    args_fields = []
    if args:
        for i, part in enumerate(args.split()):
            args_fields.append({"name": f"arg{i}", "value": part})

    detail_blocks = [routing_block]
    if args_fields:
        detail_blocks.append({"kind": "args", "label": "Arguments", "fields": args_fields})

    display = {
        "title": cmd,
        "subtitle": f"{src_lbl} \u2192 {dest_lbl}",
        "row": row,
        "detail_blocks": detail_blocks,
    }

    # Build mission_payload for requeue support
    mission_payload = {
        "cmd_id": cmd,
        "args": args,
        "dest": dest_lbl,
        "echo": echo_lbl,
        "ptype": ptype_lbl,
    }
    if src_lbl and src_lbl != "GS":
        mission_payload["src"] = src_lbl

    entry["type"] = "mission_cmd"
    entry["display"] = display
    entry["mission_payload"] = mission_payload

    return entry


def migrate_file(path: Path) -> tuple[int, int]:
    """Migrate one JSONL file. Returns (total, migrated) counts."""
    lines = path.read_text().strip().split("\n")
    if not lines or not lines[0]:
        return 0, 0

    migrated = 0
    output = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            output.append(line)
            continue

        # Check if this is an old-format entry
        is_old = "display" not in entry or (
            "display" in entry and (
                "row" not in entry.get("display", {}) or
                "detail_blocks" not in entry.get("display", {})
            )
        )

        if is_old:
            entry = migrate_entry(entry)
            migrated += 1

        output.append(json.dumps(entry))

    path.write_text("\n".join(output) + "\n")
    return len(output), migrated


def main():
    if len(sys.argv) > 1:
        log_dir = Path(sys.argv[1])
    else:
        log_dir = Path(__file__).resolve().parent.parent / "logs" / "json"

    if not log_dir.is_dir():
        print(f"Log directory not found: {log_dir}")
        sys.exit(1)

    tx_files = sorted(log_dir.glob("uplink_*.jsonl"))
    if not tx_files:
        print("No TX log files found")
        return

    total_migrated = 0
    for path in tx_files:
        total, migrated = migrate_file(path)
        if migrated > 0:
            print(f"  {path.name}: {migrated}/{total} entries migrated")
            total_migrated += migrated

    if total_migrated == 0:
        print("All TX logs already up to date")
    else:
        print(f"\nMigrated {total_migrated} entries total")


if __name__ == "__main__":
    main()
