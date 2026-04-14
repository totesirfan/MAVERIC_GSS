"""
mav_gss_lib.missions.maveric.imaging -- Image Chunk Reassembly + REST API

Collects image chunks from img_get_chunk packets and reassembles them
into complete image files.  Auto-saves to disk on every chunk so the
operator can view partial images at any time.

Individual chunks are persisted to a .chunks/ directory so non-contiguous
transfers survive server restarts. A .meta.json sidecar tracks progress.

Also provides a FastAPI router for the imaging plugin REST endpoints.

Author:  Irfan Annuar - USC ISI SERC
"""

import json
import os
import shutil
from pathlib import Path


class ImageAssembler:
    """Collects image chunks and reassembles them into files.

    Each chunk is saved individually to:
        <output_dir>/.chunks/<filename>/<chunk_num>.bin

    The assembled image is written to:
        <output_dir>/<filename>

    Progress metadata is tracked in:
        <output_dir>/<filename>.meta.json
    """

    def __init__(self, output_dir="images"):
        self.output_dir = output_dir
        self.totals = {}      # {filename: total_chunk_count}
        self.received = {}    # {filename: set of chunk indices with real data}
        self.chunk_sizes = {} # {filename: chunk_size_in_bytes}
        self.completed = {}   # {filename: total_chunk_count}
        os.makedirs(output_dir, exist_ok=True)
        self._restore_state()

    def _chunks_dir(self, filename):
        """Directory for individual chunk files."""
        return os.path.join(self.output_dir, ".chunks", filename)

    def _meta_path(self, filename):
        return os.path.join(self.output_dir, filename + ".meta.json")

    def _save_meta(self, filename):
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

    def _save_chunk(self, filename, chunk_num, data):
        """Write one chunk to its individual file."""
        chunk_dir = self._chunks_dir(filename)
        os.makedirs(chunk_dir, exist_ok=True)
        with open(os.path.join(chunk_dir, f"{chunk_num}.bin"), "wb") as f:
            f.write(data)

    def _read_chunk(self, filename, chunk_num):
        """Read one chunk from disk. Returns bytes or None."""
        path = os.path.join(self._chunks_dir(filename), f"{chunk_num}.bin")
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            return f.read()

    def _restore_state(self):
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

    def set_total(self, filename, total):
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

    def feed_chunk(self, filename, chunk_num, data, chunk_size=None):
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

    def _is_complete(self, filename):
        """True if total is known and all chunks have been received."""
        total = self.totals.get(filename)
        if total is None:
            return False
        received = self.received.get(filename, set())
        return len(received) >= total

    def is_complete(self, filename):
        return filename in self.completed

    def progress(self, filename):
        """Returns (received_count, total_or_None)."""
        if filename in self.completed:
            total = self.completed[filename]
            return total, total
        received = len(self.received.get(filename, set()))
        return received, self.totals.get(filename)

    def status(self):
        files = []
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

    def get_chunks(self, filename):
        """Return sorted list of received chunk indices."""
        if filename in self.completed:
            return list(range(self.completed[filename]))
        return sorted(self.received.get(filename, set()))

    def list_files(self):
        if not os.path.isdir(self.output_dir):
            return []
        return sorted(
            f for f in os.listdir(self.output_dir)
            if os.path.isfile(os.path.join(self.output_dir, f))
            and not f.startswith('.')
            and not f.endswith('.meta.json')
        )

    def delete_file(self, filename):
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

    def _assemble(self, filename):
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


# =============================================================================
#  REST API ROUTER
# =============================================================================

def get_imaging_router(assembler: "ImageAssembler"):
    from fastapi import APIRouter
    from fastapi.responses import FileResponse, JSONResponse

    router = APIRouter(prefix="/api/plugins/imaging", tags=["imaging"])

    @router.get("/status")
    async def imaging_status():
        return JSONResponse(assembler.status())

    @router.get("/files")
    async def imaging_files():
        return JSONResponse({"files": assembler.list_files()})

    @router.get("/chunks/{filename:path}")
    async def imaging_chunks(filename: str):
        return JSONResponse({"filename": filename, "chunks": assembler.get_chunks(filename)})

    @router.delete("/file/{filename:path}")
    async def imaging_delete(filename: str):
        assembler.delete_file(filename)
        return JSONResponse({"ok": True, "filename": filename})

    @router.get("/preview/{filename:path}")
    async def imaging_preview(filename: str):
        path = Path(assembler.output_dir) / filename
        if not path.is_file():
            return JSONResponse({"error": "not found"}, status_code=404)
        stat = path.stat()
        if stat.st_size == 0:
            return JSONResponse({"error": "no image data yet"}, status_code=404)
        etag = f'"{stat.st_mtime_ns}-{stat.st_size}"'
        return FileResponse(
            path,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "no-cache",
                "ETag": etag,
            },
        )

    return router
