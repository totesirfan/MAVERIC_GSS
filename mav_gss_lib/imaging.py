"""
mav_gss_lib.imaging -- Image Chunk Reassembly

Collects image chunks from img_get_chunk packets and reassembles them
into complete image files.  Auto-saves to disk on every chunk so the
operator can view partial images at any time.

Author:  Irfan Annuar - USC ISI SERC
"""

import os


class ImageAssembler:
    """Collects image chunks and reassembles them into files.

    Usage:
        asm = ImageAssembler("images/")
        asm.set_total("a.jpg", 100)                  # from img_cnt_chunks
        asm.feed_chunk("a.jpg", 0, chunk_bytes)       # from img_get_chunk
        ...
        # Auto-saves to images/a.jpg on every chunk.
        # Clears from memory once all chunks are received.
    """

    def __init__(self, output_dir="images"):
        self.output_dir = output_dir
        self.chunks = {}      # {filename: {chunk_num: bytes}}
        self.totals = {}      # {filename: total_chunk_count}
        self.chunk_sizes = {} # {filename: chunk_size_in_bytes}
        os.makedirs(output_dir, exist_ok=True)

    def set_total(self, filename, total):
        """Register the expected chunk count for a file (from img_cnt_chunks)."""
        self.totals[filename] = int(total)

    def feed_chunk(self, filename, chunk_num, data, chunk_size=None):
        """Store a chunk and auto-save the current image state to disk.

        Returns (received, total_or_None, complete).
        """
        if filename not in self.chunks:
            self.chunks[filename] = {}
        key = int(chunk_num)
        if key in self.chunks[filename]:
            return self.progress(filename) + (False,)
        self.chunks[filename][key] = data
        if chunk_size is not None and filename not in self.chunk_sizes:
            try:
                self.chunk_sizes[filename] = int(chunk_size)
            except (ValueError, TypeError):
                pass
        self._save(filename)
        complete = self.is_complete(filename)
        if complete:
            self.chunks.pop(filename, None)
        return self.progress(filename) + (complete,)

    def is_complete(self, filename):
        """True if total is known and all chunks have been received."""
        total = self.totals.get(filename)
        received = len(self.chunks.get(filename, {}))
        return total is not None and received >= total

    def progress(self, filename):
        """Returns (received_count, total_or_None)."""
        received = len(self.chunks.get(filename, {}))
        return received, self.totals.get(filename)

    def _save(self, filename):
        """Write the contiguous run of chunks starting from chunk 0.

        Skips gaps — JPEG and other compressed formats can't survive
        zero-padded holes.  Appends a JPEG EOI marker (ff d9) so
        viewers can open truncated files.
        """
        file_chunks = self.chunks.get(filename)
        if not file_chunks or 0 not in file_chunks:
            return
        path = os.path.join(self.output_dir, filename)
        with open(path, "wb") as f:
            i = 0
            while i in file_chunks:
                f.write(file_chunks[i])
                i += 1
            if file_chunks[0][:2] == b"\xff\xd8":
                f.write(b"\xff\xd9")
