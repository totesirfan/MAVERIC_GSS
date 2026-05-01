"""Format-agnostic chunked-file persistence engine.

Owns: per-chunk persistence under ``.chunks/``, ``.meta.json`` sidecar
for restore-on-startup, dedup, gap-aware contiguous assembly into a
single file, completion cleanup, source/kind namespacing, plus a small
``extras`` dict per ref so adapters can persist private metadata
(e.g. AII ``valid`` flag) without re-reading files on every status call.

Does NOT know about: packets, cmd_ids, MIME, JPEG, JSON, NVG, MAVERIC.
This module must not import anything from
``mav_gss_lib.missions.maveric.*``. Enforced by
``tests.test_chunk_file_store::StoreHasNoMavericImportsTests``.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import PurePosixPath
import shutil
from typing import Any


@dataclass(frozen=True, slots=True)
class FileRef:
    """Stable identity for a downlinked file.

    ``kind`` namespaces image/aii/mag products that may share filenames.
    ``source`` namespaces the spacecraft node (HLNV vs ASTR) so two
    nodes downlinking ``capture.jpg`` never collide.
    """

    kind: str
    source: str | None
    filename: str

    @property
    def id(self) -> str:
        clean_source = _normalise(self.source)
        if clean_source:
            return f"{self.kind}/{clean_source}/{self.filename}"
        return f"{self.kind}/{self.filename}"


@dataclass(frozen=True, slots=True)
class ChunkFeedResult:
    received: int
    total: int | None
    complete: bool
    path: str  # absolute path to the assembled file (always exists after the call)


def _normalise(source: str | None) -> str | None:
    if source is None:
        return None
    text = str(source).strip()
    return text or None


def _segment(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value) or "_"


def _safe_relative_path(filename: str) -> str:
    name = str(filename).strip().replace("\\", "/")
    path = PurePosixPath(name)
    if not name or path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"unsafe filename: {filename!r}")
    return os.path.join(*path.parts)


def _safe_join(root: str, relative_path: str) -> str:
    root_abs = os.path.abspath(root)
    path = os.path.abspath(os.path.join(root_abs, relative_path))
    if os.path.commonpath([root_abs, path]) != root_abs:
        raise ValueError(f"unsafe path: {relative_path!r}")
    return path


class ChunkFileStore:
    """Persists chunked-file downlinks. Format-blind.

    On-disk layout::

        <root>/<kind>/<source>/<filename>            # assembled file
        <root>/<kind>/<source>/<filename>.meta.json  # progress sidecar (incl. extras)
        <root>/.chunks/<kind>/<source>/<filename>/<n>.bin   # individual chunks

    Note: ``feed_chunk`` re-walks all on-disk chunks per call (legacy
    behavior — O(N) per call, O(N**2) total for an N-chunk transfer).
    Acceptable at MAVERIC scale (typical files are tens of chunks).
    """

    def __init__(self, root: str) -> None:
        self.root = root
        self.totals: dict[FileRef, int] = {}
        self.received: dict[FileRef, set[int]] = {}
        self.chunk_sizes: dict[FileRef, int] = {}
        self.completed: dict[FileRef, int] = {}
        self.extras: dict[FileRef, dict[str, Any]] = {}
        os.makedirs(root, exist_ok=True)
        self._restore_state()

    # -- Public API ------------------------------------------------

    def set_total(self, ref: FileRef, total: int) -> None:
        ref = self._validate_ref(ref)
        total = int(total)
        existing = self.totals.get(ref)
        if existing == total and (ref in self.received or ref in self.completed):
            return  # idempotent -- same in-flight transfer
        self.totals[ref] = total
        self.completed.pop(ref, None)
        self.received.pop(ref, None)
        self.extras.pop(ref, None)  # new transfer => stale extras
        chunk_dir = self.chunks_dir_for(ref)
        if os.path.isdir(chunk_dir):
            shutil.rmtree(chunk_dir, ignore_errors=True)
        path = self._file_path_internal(ref)
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "wb").close()
        self._save_meta(ref)

    def feed_chunk(
        self,
        ref: FileRef,
        chunk_num: int,
        data: bytes,
        *,
        chunk_size: int | None = None,
    ) -> ChunkFeedResult:
        ref = self._validate_ref(ref)
        idx = int(chunk_num)
        # Already-complete transfers are sealed: a late duplicate must
        # not recreate received state, rewrite the assembled file, or
        # corrupt completion bookkeeping.
        if ref in self.completed:
            total = self.completed[ref]
            return ChunkFeedResult(total, total, True, self._file_path_internal(ref))
        # Reject out-of-range indices. A FILE packet with chunk_idx
        # outside [0, total) is corrupt; logging and dropping is safer
        # than admitting it into received[].
        total = self.totals.get(ref)
        if idx < 0 or (total is not None and idx >= total):
            raise ValueError(f"chunk_num {idx} out of range for total={total}")
        if ref not in self.received:
            self.received[ref] = set()
        if idx in self.received[ref]:
            received, _ = self.progress(ref)
            return ChunkFeedResult(received, total, False, self._file_path_internal(ref))
        self._save_chunk(ref, idx, data)
        self.received[ref].add(idx)
        if chunk_size is not None and ref not in self.chunk_sizes:
            self.chunk_sizes[ref] = int(chunk_size)
        self._assemble(ref)
        self._save_meta(ref)
        complete = self._is_complete(ref)
        if complete:
            total = self.totals.get(ref)
            if total is not None:
                self.completed[ref] = total
            self.received.pop(ref, None)
            chunk_dir = self.chunks_dir_for(ref)
            if os.path.isdir(chunk_dir):
                shutil.rmtree(chunk_dir, ignore_errors=True)
            self._save_meta(ref)
        received, total = self.progress(ref)
        return ChunkFeedResult(received, total, complete, self._file_path_internal(ref))

    def progress(self, ref: FileRef) -> tuple[int, int | None]:
        ref = self._validate_ref(ref)
        if ref in self.completed:
            t = self.completed[ref]
            return t, t
        return len(self.received.get(ref, set())), self.totals.get(ref)

    def is_complete(self, ref: FileRef) -> bool:
        return self._validate_ref(ref) in self.completed

    def known_files(self, *, kind: str | None = None) -> list[FileRef]:
        refs = set(self.totals) | set(self.received) | set(self.completed)
        if kind is not None:
            refs = {r for r in refs if r.kind == kind}
        return sorted(refs, key=lambda r: (r.kind, r.source or "", r.filename))

    def get_chunks(self, ref: FileRef) -> list[int]:
        ref = self._validate_ref(ref)
        if ref in self.completed:
            return list(range(self.completed[ref]))
        return sorted(self.received.get(ref, set()))

    def chunk_size(self, ref: FileRef) -> int | None:
        return self.chunk_sizes.get(self._validate_ref(ref))

    def file_path(self, ref: FileRef) -> str:
        return self._file_path_internal(self._validate_ref(ref))

    def meta_path(self, ref: FileRef) -> str:
        return self._meta_path_internal(self._validate_ref(ref))

    def chunks_dir_for(self, ref: FileRef) -> str:
        return self._chunks_dir_internal(self._validate_ref(ref))

    def meta_mtime_ms(self, ref: FileRef) -> int | None:
        path = self.meta_path(ref)
        if not os.path.isfile(path):
            return None
        try:
            return int(os.path.getmtime(path) * 1000)
        except OSError:
            return None

    def delete_file(self, ref: FileRef) -> None:
        ref = self._validate_ref(ref)
        for path in (self._file_path_internal(ref), self._meta_path_internal(ref)):
            if os.path.isfile(path):
                os.remove(path)
        chunk_dir = self._chunks_dir_internal(ref)
        if os.path.isdir(chunk_dir):
            shutil.rmtree(chunk_dir, ignore_errors=True)
        self.totals.pop(ref, None)
        self.received.pop(ref, None)
        self.chunk_sizes.pop(ref, None)
        self.completed.pop(ref, None)
        self.extras.pop(ref, None)

    def set_extras(self, ref: FileRef, **kwargs: Any) -> None:
        """Merge ``kwargs`` into the adapter-private extras dict and persist."""
        ref = self._validate_ref(ref)
        slot = self.extras.setdefault(ref, {})
        slot.update(kwargs)
        self._save_meta(ref)

    def get_extras(self, ref: FileRef) -> dict[str, Any]:
        return dict(self.extras.get(self._validate_ref(ref), {}))

    # -- Internal helpers ------------------------------------------

    def _validate_ref(self, ref: FileRef) -> FileRef:
        kind = str(ref.kind).strip()
        if not kind:
            raise ValueError("FileRef.kind must be non-empty")
        filename = str(ref.filename).strip()
        _safe_relative_path(filename)
        return FileRef(kind=kind, source=_normalise(ref.source), filename=filename)

    def _kind_root(self, ref: FileRef) -> str:
        return os.path.join(self.root, _segment(ref.kind))

    def _file_root(self, ref: FileRef) -> str:
        kind_root = self._kind_root(ref)
        if ref.source:
            return os.path.join(kind_root, _segment(ref.source))
        return kind_root

    def _file_path_internal(self, ref: FileRef) -> str:
        return _safe_join(self._file_root(ref), _safe_relative_path(ref.filename))

    def _chunks_dir_internal(self, ref: FileRef) -> str:
        root = os.path.join(self.root, ".chunks", _segment(ref.kind))
        if ref.source:
            root = os.path.join(root, _segment(ref.source))
        return _safe_join(root, _safe_relative_path(ref.filename))

    def _meta_path_internal(self, ref: FileRef) -> str:
        return _safe_join(self._file_root(ref), _safe_relative_path(ref.filename + ".meta.json"))

    def _save_meta(self, ref: FileRef) -> None:
        meta: dict[str, Any] = {
            "kind": ref.kind,
            "source": ref.source,
            "filename": ref.filename,
            "total": self.totals.get(ref),
            "chunks": sorted(self.received.get(ref, set())),
            "complete": ref in self.completed,
        }
        if ref in self.chunk_sizes:
            meta["chunk_size"] = self.chunk_sizes[ref]
        if ref in self.extras and self.extras[ref]:
            meta["extras"] = dict(self.extras[ref])
        try:
            path = self._meta_path_internal(ref)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(meta, f)
        except Exception:
            pass

    def _save_chunk(self, ref: FileRef, chunk_num: int, data: bytes) -> None:
        chunk_dir = self._chunks_dir_internal(ref)
        os.makedirs(chunk_dir, exist_ok=True)
        with open(os.path.join(chunk_dir, f"{chunk_num}.bin"), "wb") as f:
            f.write(data)

    def _is_complete(self, ref: FileRef) -> bool:
        """True only when every index in [0, total) is present.

        Defends against a corrupt sequence (e.g. chunks {1, 2} with
        total=2) that has the right *count* but the wrong *coverage* --
        the assembled file would be missing chunk 0.
        """
        total = self.totals.get(ref)
        if total is None or total <= 0:
            return False
        received = self.received.get(ref, set())
        if len(received) < total:
            return False
        return all(i in received for i in range(total))

    def _assemble(self, ref: FileRef) -> None:
        chunk_dir = self._chunks_dir_internal(ref)
        if not os.path.isdir(chunk_dir):
            return
        if not os.path.isfile(os.path.join(chunk_dir, "0.bin")):
            return
        path = self._file_path_internal(ref)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as out:
            i = 0
            while True:
                cp = os.path.join(chunk_dir, f"{i}.bin")
                if not os.path.isfile(cp):
                    break
                with open(cp, "rb") as cf:
                    out.write(cf.read())
                i += 1

    def _restore_state(self) -> None:
        if not os.path.isdir(self.root):
            return
        for current, dirnames, filenames in os.walk(self.root):
            if ".chunks" in dirnames:
                dirnames.remove(".chunks")
            for name in filenames:
                if not name.endswith(".meta.json"):
                    continue
                meta_path = os.path.join(current, name)
                try:
                    meta = json.loads(open(meta_path).read())
                except Exception:
                    continue
                if not isinstance(meta, dict):
                    continue
                kind = meta.get("kind")
                source = meta.get("source")
                filename = meta.get("filename")
                if not kind or not filename:
                    continue
                try:
                    ref = self._validate_ref(FileRef(kind=kind, source=source, filename=filename))
                except ValueError:
                    continue
                total = meta.get("total")
                if total is not None:
                    try:
                        self.totals[ref] = int(total)
                    except (ValueError, TypeError):
                        pass
                if meta.get("chunk_size"):
                    try:
                        self.chunk_sizes[ref] = int(meta["chunk_size"])
                    except (ValueError, TypeError):
                        pass
                extras = meta.get("extras")
                if isinstance(extras, dict):
                    self.extras[ref] = dict(extras)
                if meta.get("complete") and ref in self.totals:
                    self.completed[ref] = self.totals[ref]
                else:
                    chunk_dir = self._chunks_dir_internal(ref)
                    real = set()
                    if os.path.isdir(chunk_dir):
                        for cf in os.listdir(chunk_dir):
                            if cf.endswith(".bin"):
                                try:
                                    real.add(int(cf[:-4]))
                                except ValueError:
                                    pass
                    self.received[ref] = real
