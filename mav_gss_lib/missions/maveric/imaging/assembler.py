"""Image chunk reassembly for the MAVERIC imaging plugin.

Collects image chunks from img_get_chunks packets and reassembles them
into complete image files. Auto-saves to disk on every chunk so the
operator can view partial images at any time.

Individual chunks are persisted to a .chunks/ directory so non-contiguous
transfers survive server restarts. A .meta.json sidecar tracks progress.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import json
import os
import shutil
from typing import Any


def derive_thumb_filename(full_filename: str, prefix: str | None) -> str | None:
    """Given a full image filename, return the thumb counterpart.

    Returns None if the prefix is empty or None (pairing disabled).
    """
    if not prefix:
        return None
    return f"{prefix}{full_filename}"


def derive_full_filename(thumb_filename: str, prefix: str | None) -> str | None:
    """Given a thumb image filename, return the full counterpart.

    Returns None if the prefix is empty, None, or the thumb filename
    doesn't start with the prefix (i.e. it isn't actually a thumb).
    """
    if not prefix:
        return None
    if not thumb_filename.startswith(prefix):
        return None
    return thumb_filename[len(prefix):]


class ImageAssembler:
    """Collects image chunks and reassembles them into files.

    Each chunk is saved individually to:
        <output_dir>/.chunks/<filename>/<chunk_num>.bin

    The assembled image is written to:
        <output_dir>/<filename>

    Progress metadata is tracked in:
        <output_dir>/<filename>.meta.json
    """

    def __init__(self, output_dir: str = "images") -> None:
        self.output_dir = output_dir
        self.totals: dict[str, int] = {}
        self.received: dict[str, set[int]] = {}
        self.chunk_sizes: dict[str, int] = {}
        self.completed: dict[str, int] = {}
        os.makedirs(output_dir, exist_ok=True)
        self._restore_state()

    def _chunks_dir(self, filename: str) -> str:
        """Directory for individual chunk files."""
        return os.path.join(self.output_dir, ".chunks", filename)

    def _meta_path(self, filename: str) -> str:
        return os.path.join(self.output_dir, filename + ".meta.json")

    def _save_meta(self, filename: str) -> None:
        meta = {
            "total": self.totals.get(filename),
            "chunks": sorted(self.received.get(filename, set())),
            "complete": filename in self.completed,
        }
        if filename in self.chunk_sizes:
            meta["chunk_size"] = self.chunk_sizes[filename]
        try:
            with open(self._meta_path(filename), "w") as f:
                json.dump(meta, f)
        except Exception:
            pass

    def _save_chunk(self, filename: str, chunk_num: int, data: bytes) -> None:
        """Write one chunk to its individual file."""
        chunk_dir = self._chunks_dir(filename)
        os.makedirs(chunk_dir, exist_ok=True)
        with open(os.path.join(chunk_dir, f"{chunk_num}.bin"), "wb") as f:
            f.write(data)

    def _read_chunk(self, filename: str, chunk_num: int) -> bytes | None:
        """Read one chunk from disk. Returns bytes or None."""
        path = os.path.join(self._chunks_dir(filename), f"{chunk_num}.bin")
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            return f.read()

    def _restore_state(self) -> None:
        """Scan output directory for .meta.json sidecars and restore state."""
        if not os.path.isdir(self.output_dir):
            return
        for name in os.listdir(self.output_dir):
            if not name.endswith(".meta.json"):
                continue
            filename = name[:-len(".meta.json")]
            try:
                with open(os.path.join(self.output_dir, name)) as f:
                    meta = json.load(f)
            except Exception:
                continue
            total = meta.get("total")
            if total is not None:
                self.totals[filename] = total
            if meta.get("chunk_size"):
                self.chunk_sizes[filename] = meta["chunk_size"]
            if meta.get("complete"):
                self.completed[filename] = total
            else:
                # Verify which chunks actually exist on disk
                chunk_dir = self._chunks_dir(filename)
                real_chunks = set()
                if os.path.isdir(chunk_dir):
                    for cf in os.listdir(chunk_dir):
                        if cf.endswith(".bin"):
                            try:
                                real_chunks.add(int(cf[:-4]))
                            except ValueError:
                                pass
                self.received[filename] = real_chunks

    def set_total(self, filename: str, total: int) -> None:
        """Register the expected chunk count for a file (from img_cnt_chunks).

        Only resets state if the total changes (new transfer for same file).
        """
        total = int(total)
        existing_total = self.totals.get(filename)
        if existing_total == total and (filename in self.received or filename in self.completed):
            return
        self.totals[filename] = total
        self.completed.pop(filename, None)
        self.received.pop(filename, None)
        # Clean old chunk files for a fresh transfer
        chunk_dir = self._chunks_dir(filename)
        if os.path.isdir(chunk_dir):
            shutil.rmtree(chunk_dir, ignore_errors=True)
        # Create placeholder so file appears in images/
        path = os.path.join(self.output_dir, filename)
        if not os.path.exists(path):
            with open(path, "wb") as f:
                pass
        self._save_meta(filename)

    def feed_chunk(
        self,
        filename: str,
        chunk_num: int,
        data: bytes,
        chunk_size: int | None = None,
    ) -> tuple[int, int | None, bool]:
        """Store a chunk and auto-save the current image state to disk.

        Returns (received, total_or_None, complete).
        """
        if filename not in self.received:
            self.received[filename] = set()
        key = int(chunk_num)
        if key in self.received[filename]:
            return self.progress(filename) + (False,)
        # Save chunk to its own file
        self._save_chunk(filename, key, data)
        self.received[filename].add(key)
        if chunk_size is not None and filename not in self.chunk_sizes:
            try:
                self.chunk_sizes[filename] = int(chunk_size)
            except (ValueError, TypeError):
                pass
        # Reassemble contiguous image from chunk files
        self._assemble(filename)
        self._save_meta(filename)
        complete = self._is_complete(filename)
        if complete:
            total = self.totals.get(filename)
            self.completed[filename] = total
            self.received.pop(filename, None)
            # Clean up chunk files — image is complete on disk
            chunk_dir = self._chunks_dir(filename)
            if os.path.isdir(chunk_dir):
                shutil.rmtree(chunk_dir, ignore_errors=True)
            self._save_meta(filename)
        return self.progress(filename) + (complete,)

    def _is_complete(self, filename: str) -> bool:
        """True if total is known and all chunks have been received."""
        total = self.totals.get(filename)
        if total is None:
            return False
        received = self.received.get(filename, set())
        return len(received) >= total

    def is_complete(self, filename: str) -> bool:
        return filename in self.completed

    def known_filenames(self) -> list[str]:
        """Every filename the assembler has state for (pending or complete)."""
        return sorted(set(self.totals) | set(self.received) | set(self.completed))

    def _meta_mtime_ms(self, filename: str) -> int | None:
        """Wall-clock millis of the last state change for a file, or None.

        The meta sidecar is rewritten on every set_total / feed_chunk call,
        so its mtime is the most accurate 'last activity' signal we have.
        """
        path = self._meta_path(filename)
        if not os.path.isfile(path):
            return None
        try:
            return int(os.path.getmtime(path) * 1000)
        except OSError:
            return None

    def progress(self, filename: str) -> tuple[int, int | None]:
        """Returns (received_count, total_or_None)."""
        if filename in self.completed:
            total = self.completed[filename]
            return total, total
        received = len(self.received.get(filename, set()))
        return received, self.totals.get(filename)

    def status(self) -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        all_filenames = set(self.totals.keys()) | set(self.received.keys()) | set(self.completed.keys())
        for fn in sorted(all_filenames):
            received, total = self.progress(fn)
            files.append({
                "filename": fn,
                "received": received,
                "total": total,
                "complete": self.is_complete(fn),
            })
        return {"files": files}

    def paired_status(self, prefix: str | None) -> dict[str, Any]:
        """Return file list grouped into (full, thumb) pairs via prefix.

        When ``prefix`` is empty/None, every file appears as its own
        unpaired entry with ``thumb`` = None.

        When ``prefix`` is set, every pair always has BOTH sides populated.
        If the assembler has only seen one side (the common case for
        scheduled captures where the GSS missed the cam_capture RX),
        the other side is a placeholder leaf with ``total: None,
        received: 0, complete: False`` and a filename derived from the
        prefix. This lets the operator recover a paired view by running
        ``img_cnt_chunks`` against either the real or derived filename.

        Each leaf dict has: ``filename``, ``received``, ``total``,
        ``complete``, ``chunk_size``. The outer dict has: ``stem``,
        ``full``, ``thumb``.
        """
        all_filenames = (
            set(self.totals.keys())
            | set(self.received.keys())
            | set(self.completed.keys())
        )

        def real_leaf(fn: str) -> dict[str, Any]:
            received, total = self.progress(fn)
            return {
                "filename": fn,
                "received": received,
                "total": total,
                "complete": self.is_complete(fn),
                "chunk_size": self.chunk_sizes.get(fn),
            }

        def placeholder_leaf(fn: str) -> dict[str, Any]:
            return {
                "filename": fn,
                "received": 0,
                "total": None,
                "complete": False,
                "chunk_size": None,
            }

        def pair_mtime(*filenames: str) -> int:
            """Max mtime across the real sides of a pair, or 0 if none."""
            best = 0
            for fn in filenames:
                if fn not in all_filenames:
                    continue
                m = self._meta_mtime_ms(fn)
                if m and m > best:
                    best = m
            return best

        if not prefix:
            unpaired = [
                {
                    "stem": fn,
                    "full": real_leaf(fn),
                    "thumb": None,
                    "last_activity_ms": self._meta_mtime_ms(fn),
                }
                for fn in all_filenames
            ]
            unpaired.sort(key=lambda p: p["last_activity_ms"] or 0, reverse=True)
            return {"files": unpaired}

        # First pass — collect the stems present in assembler state.
        stems: set[str] = set()
        for fn in all_filenames:
            stem = fn[len(prefix):] if fn.startswith(prefix) else fn
            stems.add(stem)

        # Second pass — build each pair with real or placeholder leaves.
        pairs = []
        for stem in stems:
            full_fn = stem
            thumb_fn = f"{prefix}{stem}"
            full = real_leaf(full_fn) if full_fn in all_filenames else placeholder_leaf(full_fn)
            thumb = real_leaf(thumb_fn) if thumb_fn in all_filenames else placeholder_leaf(thumb_fn)
            mtime = pair_mtime(full_fn, thumb_fn)
            pairs.append({
                "stem": stem,
                "full": full,
                "thumb": thumb,
                "last_activity_ms": mtime or None,
            })

        # Newest-first — files touched most recently (set_total or new
        # chunk) float to the top of the operator's picker. Falls back to
        # stem for stable ordering within the same-mtime bucket.
        pairs.sort(key=lambda p: (-(p["last_activity_ms"] or 0), p["stem"]))
        return {"files": pairs}

    def get_chunks(self, filename: str) -> list[int]:
        """Return sorted list of received chunk indices."""
        if filename in self.completed:
            return list(range(self.completed[filename]))
        return sorted(self.received.get(filename, set()))

    def list_files(self) -> list[str]:
        if not os.path.isdir(self.output_dir):
            return []
        return sorted(
            f for f in os.listdir(self.output_dir)
            if os.path.isfile(os.path.join(self.output_dir, f))
            and not f.startswith('.')
            and not f.endswith('.meta.json')
        )

    def delete_file(self, filename: str) -> None:
        """Remove all state for a file: image, meta, chunk dir, in-memory state."""
        for path in (
            os.path.join(self.output_dir, filename),
            self._meta_path(filename),
        ):
            if os.path.isfile(path):
                os.remove(path)
        chunk_dir = self._chunks_dir(filename)
        if os.path.isdir(chunk_dir):
            shutil.rmtree(chunk_dir, ignore_errors=True)
        self.totals.pop(filename, None)
        self.received.pop(filename, None)
        self.chunk_sizes.pop(filename, None)
        self.completed.pop(filename, None)

    def _assemble(self, filename: str) -> None:
        """Reassemble contiguous chunks from disk into the image file.

        Reads chunk files 0, 1, 2, ... until a gap. Appends JPEG EOI
        marker if the data starts with a JPEG SOI and doesn't already
        end with one (truncated/in-progress transfers get the safety EOI;
        complete transfers where the OBC already wrote EOI stay intact).
        """
        chunk_dir = self._chunks_dir(filename)
        if not os.path.isdir(chunk_dir):
            return
        # Check chunk 0 exists
        chunk0_path = os.path.join(chunk_dir, "0.bin")
        if not os.path.isfile(chunk0_path):
            return
        path = os.path.join(self.output_dir, filename)
        with open(path, "wb") as out:
            i = 0
            first_bytes = None
            last_bytes = b""
            while True:
                cp = os.path.join(chunk_dir, f"{i}.bin")
                if not os.path.isfile(cp):
                    break
                with open(cp, "rb") as cf:
                    data = cf.read()
                if i == 0:
                    first_bytes = data[:2]
                if data:
                    last_bytes = (last_bytes + data)[-2:]
                out.write(data)
                i += 1
            # Append JPEG EOI so partial transfers are still viewable,
            # unless the OBC already terminated the stream with one.
            if first_bytes == b"\xff\xd8" and last_bytes != b"\xff\xd9":
                out.write(b"\xff\xd9")
