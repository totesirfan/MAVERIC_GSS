"""
mav_gss_lib.web_runtime.tx_queue -- Pure TX Queue Operations

Stateless queue helper functions: item construction, validation,
serialization, persistence, import/export parsing, and summary.

TxService remains the runtime state owner (queue, history, sending).
This module owns only the pure logic that operates on queue data
without holding any mutable state of its own.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict, Union

if TYPE_CHECKING:
    from .state import WebRuntime

try:
    from mav_gss_lib.protocols.golay import MAX_PAYLOAD as GOLAY_MAX_PAYLOAD
except ImportError:
    GOLAY_MAX_PAYLOAD = 223


# =============================================================================
#  QUEUE ITEM SHAPES
# =============================================================================

class MissionCmdItem(TypedDict):
    type: Literal["mission_cmd"]
    raw_cmd: NotRequired[bytes]
    display: dict
    payload: dict
    guard: bool
    num: NotRequired[int]


class DelayItem(TypedDict):
    type: Literal["delay"]
    delay_ms: int


class NoteItem(TypedDict):
    type: Literal["note"]
    text: str


QueueItem = Union[MissionCmdItem, DelayItem, NoteItem]


# =============================================================================
#  ITEM CONSTRUCTORS
# =============================================================================

def make_delay(delay_ms: int) -> DelayItem:
    """Build one delay queue item."""
    return {"type": "delay", "delay_ms": delay_ms}


def make_note(text) -> NoteItem:
    """Build one note queue item (from ``//`` comment lines in JSONL files)."""
    return {"type": "note", "text": " ".join(str(text).split())}


def make_mission_cmd(payload, adapter=None) -> MissionCmdItem:
    """Build one mission-command queue item from a mission-specific payload.

    Calls the adapter's build_tx_command() to validate, encode, and
    produce display metadata. Does NOT check MTU — use
    validate_mission_cmd() for full admission.

    The original payload is stored so it can be re-built on queue restore.
    """
    result = adapter.build_tx_command(payload)
    return {
        "type": "mission_cmd",
        "raw_cmd": result["raw_cmd"],
        "display": result.get("display", {}),
        "guard": result.get("guard", False),
        "payload": payload,
    }


def validate_mission_cmd(payload, runtime: "WebRuntime | None" = None):
    """Validate and build a mission-command queue item.

    Checks: build succeeds, MTU fits.
    """
    from .state import ensure_runtime
    from .tx_context import build_send_context

    runtime = ensure_runtime(runtime)

    item = make_mission_cmd(payload, adapter=runtime.adapter)

    uplink_mode, send_csp, _send_ax25 = build_send_context(runtime)
    if uplink_mode == "ASM+Golay":
        csp_packet = send_csp.wrap(item["raw_cmd"])
        if len(csp_packet) > GOLAY_MAX_PAYLOAD:
            raise ValueError(
                f"command too large for ASM+Golay RS payload "
                f"({len(csp_packet)}B > {GOLAY_MAX_PAYLOAD}B)"
            )
    return item


def sanitize_queue_items(items, runtime: "WebRuntime | None" = None):
    """Filter a queue restore/import set down to valid command/delay items."""
    from .state import ensure_runtime

    runtime = ensure_runtime(runtime)
    accepted = []
    skipped = 0
    for item in items:
        if item["type"] in ("delay", "note"):
            accepted.append(item)
            continue
        if item["type"] == "mission_cmd":
            try:
                rebuilt = validate_mission_cmd(
                    item.get("payload", {}),
                    runtime=runtime,
                )
                if item.get("guard"):
                    rebuilt["guard"] = True
                accepted.append(rebuilt)
            except ValueError:
                skipped += 1
            continue
        # Unknown item type — skip
        skipped += 1
    return accepted, skipped


# =============================================================================
#  SERIALIZATION
# =============================================================================

def item_to_json(item):
    """Serialize a queue item for persistence (strips raw_cmd bytes)."""
    return {key: value for key, value in item.items() if key != "raw_cmd"}


def json_to_item(payload, runtime: "WebRuntime | None" = None):
    """Convert one persisted JSON payload back into a runtime queue item."""
    if payload["type"] == "delay":
        return make_delay(payload.get("delay_ms", 0))
    if payload["type"] == "note":
        return make_note(payload.get("text", ""))
    if payload["type"] == "mission_cmd":
        item = validate_mission_cmd(
            payload.get("payload", {}),
            runtime=runtime,
        )
        if "guard" in payload:
            item["guard"] = payload["guard"]
        return item
    raise ValueError(f"unsupported queue item type: {payload['type']}")


# =============================================================================
#  PERSISTENCE
# =============================================================================

def save_queue(queue: list, queue_file: Path) -> None:
    """Persist the current queue to disk as JSONL."""
    if not queue:
        try:
            os.remove(queue_file)
        except FileNotFoundError:
            pass
        return
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=str(queue_file.parent))
    try:
        with os.fdopen(fd, "w") as handle:
            for item in queue:
                handle.write(json.dumps(item_to_json(item)) + "\n")
        os.replace(tmp, str(queue_file))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_queue(queue_file: Path, runtime: "WebRuntime | None" = None) -> list:
    """Load any persisted queue items from disk."""
    if not queue_file.is_file():
        return []
    items = []
    with open(queue_file) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                items.append(json_to_item(payload, runtime=runtime))
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                logging.warning("Skipped corrupted queue entry: %s", exc)
    return items


# =============================================================================
#  QUEUE OPERATIONS
# =============================================================================

def renumber_queue(queue: list) -> None:
    """Assign sequential display numbers to queued command items."""
    count = 0
    for item in queue:
        if item["type"] == "mission_cmd":
            count += 1
            item["num"] = count


def queue_summary(queue: list, cfg: dict) -> dict:
    """Summarize queue size, guard count, and rough execution time."""
    cmds = sum(1 for item in queue if item["type"] == "mission_cmd")
    guards = sum(1 for item in queue if item.get("guard"))
    delay_total = sum(item.get("delay_ms", 0) for item in queue if item["type"] == "delay")
    default_delay = cfg.get("tx", {}).get("delay_ms", 500)
    inter_cmd_ms = default_delay * max(cmds - 1, 0)
    est_time_s = (delay_total + inter_cmd_ms) / 1000.0
    return {"cmds": cmds, "guards": guards, "est_time_s": round(est_time_s, 1)}


def queue_items_json(queue: list) -> list:
    """Project the current queue into the websocket/API JSON shape."""
    result = []
    for item in queue:
        if item["type"] == "delay":
            result.append({"type": "delay", "delay_ms": item["delay_ms"]})
            continue
        if item["type"] == "note":
            result.append({"type": "note", "text": item["text"]})
            continue
        result.append({
            "type": "mission_cmd",
            "num": item.get("num", 0),
            "display": item.get("display", {}),
            "guard": item.get("guard", False),
            "size": len(item.get("raw_cmd", b"")),
            "payload": item.get("payload", {}),
        })
    return result


# =============================================================================
#  IMPORT / EXPORT
# =============================================================================

def parse_import_file(filepath, runtime=None):
    """Parse a queue import JSONL file into runtime queue items."""
    items = []
    skipped = 0
    for raw_line in filepath.read_text().strip().split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("//"):
            continue
        in_str, escaped, out = False, False, []
        for index, ch in enumerate(line):
            if escaped:
                escaped = False
                out.append(ch)
                continue
            if ch == "\\" and in_str:
                escaped = True
                out.append(ch)
                continue
            if ch == '"':
                in_str = not in_str
                out.append(ch)
                continue
            if not in_str and ch == "/" and index + 1 < len(line) and line[index + 1] == "/":
                break
            out.append(ch)
        line = "".join(out).rstrip().rstrip(",")
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                if obj.get("type") == "delay":
                    items.append(make_delay(max(0, min(300_000, int(obj.get("delay_ms", 0))))))
                elif obj.get("type") == "note":
                    text = str(obj.get("text", "")).strip()
                    if text:
                        items.append(make_note(text))
                elif obj.get("type") == "mission_cmd" and "payload" in obj:
                    item = validate_mission_cmd(obj["payload"], runtime=runtime)
                    if obj.get("guard"):
                        item["guard"] = True
                    items.append(item)
                else:
                    skipped += 1
            else:
                skipped += 1
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            skipped += 1
    return items, skipped
