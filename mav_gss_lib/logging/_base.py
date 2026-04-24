"""Shared base class for RX/TX session logs.

`_BaseLog` owns the file I/O contract: background writer thread, JSONL +
text file pair, session-header banner, hex-dump and separator formatting,
new-session swap (preflight + commit), atomic rename, and close-on-empty
cleanup. `SessionLog` (RX) and `TXLog` (TX) extend this with the packet-
and command-specific formatting.

Author:  Irfan Annuar - USC ISI SERC
"""

import json
import os
import queue
import re
import sys
import threading
from datetime import datetime

from mav_gss_lib.constants import DEFAULT_MISSION_NAME

TS_FULL = "%Y-%m-%d %H:%M:%S %Z"   # Full timestamp with timezone
TS_FULL_MS = "%Y-%m-%d %H:%M:%S.{ms:03d} %Z"  # With milliseconds for per-entry stamps

# Line width for text logs
LOG_LINE_WIDTH = 80
SEP_CHAR = "─"
HEADER_CHAR = "═"


def _format_session_header(mission_name: str, version: str, mode: str, zmq_addr: str,
                           *, operator: str = "", station: str = "", host: str = "") -> str:
    """Render the text-log banner. Adds Operator: / Station: lines when supplied."""
    session_ts = datetime.now().astimezone().strftime(TS_FULL)
    identity_lines = ""
    if operator:
        identity_lines += f"  Operator:  {operator}\n"
    if station:
        detail = f" ({host})" if host and host != station else ""
        identity_lines += f"  Station:   {station}{detail}\n"
    return (
        f"{HEADER_CHAR * LOG_LINE_WIDTH}\n"
        f"  {mission_name} Ground Station Log  v{version}\n"
        f"  Mode:      {mode}\n"
        f"  Session:   {session_ts}\n"
        f"  ZMQ:       {zmq_addr}\n"
        f"{identity_lines}"
        f"{HEADER_CHAR * LOG_LINE_WIDTH}\n\n"
    )


def _compose_log_paths(log_dir: str, prefix: str, tag: str,
                       station: str = "", operator: str = "") -> tuple[str, str, str]:
    """Return (text_path, jsonl_path, session_id) under log_dir/text and log_dir/json.

    The session_id equals the file stem — callers use it to stamp every
    JSONL record so SQL ingest has a stable session key matching the
    filename on disk.

    *tag*, *station*, *operator* must be pre-sanitized — callers handle it."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = [prefix, ts]
    if station:
        parts.append(station)
    if operator:
        parts.append(operator)
    if tag:
        parts.append(tag)
    name = "_".join(parts)
    return (
        os.path.join(log_dir, "text", f"{name}.txt"),
        os.path.join(log_dir, "json", f"{name}.jsonl"),
        name,
    )


class _BaseLog:
    """Shared JSONL + text log infrastructure.

    All file I/O runs on a dedicated background thread so that callers
    (typically the Textual event loop) never block on disk flushes.
    """

    _SENTINEL = None  # poison pill to stop the writer thread

    def __init__(self, log_dir, prefix, version, mode, zmq_addr, mission_name=DEFAULT_MISSION_NAME,
                 *, mission_id: str = "", station: str = "", operator: str = "", host: str = ""):
        self._log_dir = log_dir
        self._prefix = prefix
        self._version = version
        self._mode = mode
        self._zmq_addr = zmq_addr
        self._mission_name = mission_name
        self._mission_id = mission_id
        self._station = station
        self._operator = operator
        self._host = host
        self._q_lock = threading.Lock()
        self.session_id = ""
        os.makedirs(os.path.join(log_dir, "text"), exist_ok=True)
        os.makedirs(os.path.join(log_dir, "json"), exist_ok=True)
        self._open_files()

    @property
    def mission_id(self) -> str:
        """Active mission id stamped onto JSONL records by the platform builders."""
        return self._mission_id

    def set_zmq_addr(self, zmq_addr: str) -> None:
        """Update the ZMQ endpoint embedded in subsequent session headers."""
        self._zmq_addr = zmq_addr

    _FLUSH_EVERY_N = 64
    _FLUSH_EVERY_S = 0.5

    def _writer_loop(self):
        """Drain the write queue until sentinel, flushing in batches.

        Cadence:
          - Every _FLUSH_EVERY_N items (throughput-driven) OR
          - Every _FLUSH_EVERY_S seconds when idle (latency-driven,
            via the queue.get() timeout raising queue.Empty) OR
          - On sentinel receipt (durability at close()).
        """
        unflushed = 0
        while True:
            try:
                item = self._q.get(timeout=self._FLUSH_EVERY_S)
            except queue.Empty:
                if unflushed > 0:
                    self._flush_handles()
                    unflushed = 0
                continue

            if item is self._SENTINEL:
                while not self._q.empty():
                    try:
                        remaining = self._q.get_nowait()
                        if remaining is self._SENTINEL:
                            continue
                        self._process_item(remaining)
                    except Exception:
                        break
                self._flush_handles()
                break

            try:
                self._process_item(item)
            except Exception as e:
                print(f"WARNING: log write failed ({e}), continuing", file=sys.stderr)
                continue
            unflushed += 1
            if unflushed >= self._FLUSH_EVERY_N:
                self._flush_handles()
                unflushed = 0

    def _flush_handles(self):
        """Flush both file handles, tolerating a handle that was just rotated out."""
        for handle in (self._jsonl_f, self._text_f):
            try:
                handle.flush()
            except (ValueError, OSError):
                pass

    def _process_item(self, item):
        """Process a single queue item (write only — flushing is batched)."""
        kind, data = item
        if kind == "jsonl":
            self._jsonl_f.write(data)
        elif kind == "text":
            self._text_f.write(data)
        elif kind == "rename":
            new_text, new_jsonl = data
            self._flush_handles()
            self._text_f.close(); self._jsonl_f.close()
            os.rename(self.text_path, new_text)
            os.rename(self.jsonl_path, new_jsonl)
            self.text_path, self.jsonl_path = new_text, new_jsonl
            self.session_id = os.path.splitext(os.path.basename(new_jsonl))[0]
            self._text_f = open(new_text, "a")
            self._jsonl_f = open(new_jsonl, "a")

    def _separator(self, label, extras="", *, ts_ms: int | None = None):
        """Build thin separator: ──── #1  timestamp  extras ────────

        If *ts_ms* is supplied, the timestamp is stamped from that exact
        moment (matching the JSONL record's ts_ms); otherwise the current
        wall clock is used. Callers writing per-entry records should pass
        ts_ms so the text log stays aligned with the JSONL timeline.
        """
        if ts_ms is not None:
            dt = datetime.fromtimestamp(ts_ms / 1000).astimezone()
            ts = dt.strftime(TS_FULL_MS).format(ms=ts_ms % 1000)
        else:
            ts = datetime.now().astimezone().strftime(TS_FULL)
        content = f"{SEP_CHAR * 4} {label}  {ts}  {extras}".rstrip()
        pad = max(0, LOG_LINE_WIDTH - len(content) - 1)
        return content + " " + SEP_CHAR * pad

    @staticmethod
    def _field(label, value):
        """Format a labeled field: '  LABEL       value'"""
        return f"  {label:<12}{value}"

    @staticmethod
    def _hex_lines(data, label="HEX"):
        """Format hex dump at 16 bytes/line with label on first line."""
        if not data:
            return []
        hex_str = data.hex(" ")
        chunk_w = 47
        lines = []
        offset = 0
        first = True
        while offset < len(hex_str):
            chunk = hex_str[offset:offset + chunk_w].rstrip()
            if first:
                lines.append(f"  {label:<12}{chunk}")
                first = False
            else:
                lines.append(f"  {'':12}{chunk}")
            offset += chunk_w + 1
        return lines

    def write_jsonl(self, record):
        """Queue one pre-built envelope dict for the writer thread to persist."""
        with self._q_lock:
            self._q.put(("jsonl", json.dumps(record) + "\n"))

    def _write_entry(self, lines):
        """Write a complete log entry (list of lines + trailing blank)."""
        with self._q_lock:
            self._q.put(("text", "\n".join(lines) + "\n\n"))

    def _open_files(self, tag=""):
        """Open new log files with fresh timestamp, write header, start writer thread."""
        tag      = re.sub(r'[^\w\-.]', '_', tag.strip()).strip('_') if tag else ""
        station  = re.sub(r'[^\w\-.]', '_', self._station.strip()).strip('_') if self._station else ""
        operator = re.sub(r'[^\w\-.]', '_', self._operator.strip()).strip('_') if self._operator else ""
        self.text_path, self.jsonl_path, self.session_id = _compose_log_paths(
            self._log_dir, self._prefix, tag, station=station, operator=operator,
        )
        self._text_f = open(self.text_path, "w")
        self._jsonl_f = open(self.jsonl_path, "a")
        self._text_f.write(_format_session_header(
            self._mission_name, self._version, self._mode, self._zmq_addr,
            operator=self._operator, station=self._station, host=self._host,
        ))
        self._text_f.flush()
        self._q = queue.Queue()
        self._writer = threading.Thread(target=self._writer_loop, name="log-writer", daemon=True)
        self._writer.start()

    def prepare_new_session(self, tag=""):
        """Open new log files WITHOUT closing old ones (prepare phase)."""
        tag      = re.sub(r'[^\w\-.]', '_', tag.strip()).strip('_') if tag else ""
        station  = re.sub(r'[^\w\-.]', '_', self._station.strip()).strip('_') if self._station else ""
        operator = re.sub(r'[^\w\-.]', '_', self._operator.strip()).strip('_') if self._operator else ""
        new_text_path, new_jsonl_path, new_session_id = _compose_log_paths(
            self._log_dir, self._prefix, tag, station=station, operator=operator,
        )
        new_text_f = None
        new_jsonl_f = None
        try:
            os.makedirs(os.path.join(self._log_dir, "text"), exist_ok=True)
            os.makedirs(os.path.join(self._log_dir, "json"), exist_ok=True)
            new_text_f = open(new_text_path, "w")
            new_jsonl_f = open(new_jsonl_path, "a")
            new_text_f.write(_format_session_header(
                self._mission_name, self._version, self._mode, self._zmq_addr,
                operator=self._operator, station=self._station, host=self._host,
            ))
            new_text_f.flush()
        except Exception:
            if new_text_f:
                try: new_text_f.close()
                except Exception: pass
            if new_jsonl_f:
                try: new_jsonl_f.close()
                except Exception: pass
            for p in (new_text_path, new_jsonl_path):
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except OSError:
                    pass
            raise
        return {
            "text_path": new_text_path,
            "jsonl_path": new_jsonl_path,
            "session_id": new_session_id,
            "text_f": new_text_f,
            "jsonl_f": new_jsonl_f,
        }

    def commit_new_session(self, prepared):
        """Swap to new file handles from *prepared* dict (commit phase)."""
        old_jsonl = self.jsonl_path
        old_text = self.text_path
        with self._q_lock:
            self._q.put(self._SENTINEL)
        self._writer.join(timeout=5.0)
        if self._writer.is_alive():
            prepared["text_f"].close()
            prepared["jsonl_f"].close()
            raise RuntimeError("old writer thread did not stop within timeout — commit aborted")
        self._text_f.close()
        self._jsonl_f.close()
        try:
            if os.path.isfile(old_jsonl) and os.path.getsize(old_jsonl) == 0:
                os.remove(old_jsonl)
                if os.path.isfile(old_text):
                    os.remove(old_text)
        except OSError:
            pass
        self.text_path = prepared["text_path"]
        self.jsonl_path = prepared["jsonl_path"]
        self.session_id = prepared["session_id"]
        self._text_f = prepared["text_f"]
        self._jsonl_f = prepared["jsonl_f"]
        self._q = queue.Queue()
        self._writer = threading.Thread(target=self._writer_loop,
                                        name="log-writer", daemon=True)
        self._writer.start()

    def compute_rename_paths(self, tag):
        """Compute new file paths for a rename operation. Returns (new_text, new_jsonl)."""
        tag = re.sub(r'[^\w\-.]', '_', tag.strip()).strip('_')
        if not tag:
            return None, None
        def _new_path(path):
            base, ext = os.path.splitext(path)
            return f"{base}_{tag}{ext}"
        return _new_path(self.text_path), _new_path(self.jsonl_path)

    def rename_preflight(self, tag):
        """Check that rename targets do not already exist.

        Returns (new_text, new_jsonl) on success or raises FileExistsError.
        """
        new_text, new_jsonl = self.compute_rename_paths(tag)
        if new_text is None:
            raise ValueError("empty tag after sanitization")
        if os.path.exists(new_text):
            raise FileExistsError(f"target already exists: {new_text}")
        if os.path.exists(new_jsonl):
            raise FileExistsError(f"target already exists: {new_jsonl}")
        return new_text, new_jsonl

    def rename(self, tag):
        """Rename log files by appending a sanitized tag before the extension."""
        tag = re.sub(r'[^\w\-.]', '_', tag.strip()).strip('_')
        if not tag:
            return
        def _new_path(path):
            base, ext = os.path.splitext(path)
            return f"{base}_{tag}{ext}"
        new_text, new_jsonl = _new_path(self.text_path), _new_path(self.jsonl_path)
        if sys.platform == "win32":
            self._q.put(("rename", (new_text, new_jsonl)))
        else:
            os.rename(self.text_path, new_text)
            os.rename(self.jsonl_path, new_jsonl)
            self.text_path, self.jsonl_path = new_text, new_jsonl
            self.session_id = os.path.splitext(os.path.basename(new_jsonl))[0]

    def close(self):
        """Stop the writer thread and close both file handles.

        Drains queued items, flushes, then unlinks an empty pair so sessions
        that never received a packet don't litter the log directory.
        """
        self._q.put(self._SENTINEL)
        self._writer.join(timeout=5.0)
        if not self._writer.is_alive():
            self._jsonl_f.close()
            self._text_f.close()
        try:
            if os.path.isfile(self.jsonl_path) and os.path.getsize(self.jsonl_path) == 0:
                os.remove(self.jsonl_path)
                if os.path.isfile(self.text_path):
                    os.remove(self.text_path)
        except OSError:
            pass
