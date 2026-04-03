"""
MAV_IMG -- Live Image Downlink Viewer

Subscribes to the same ZMQ feed as MAV_RX and progressively renders
images line-by-line as chunks arrive, like a Mars rover downlink.

Usage:
    python3 MAV_IMG.py               # live from ZMQ
    python3 MAV_IMG.py --replay      # replay from logged JSONL files

Author:  Irfan Annuar - USC ISI SERC
"""

import argparse
import io
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk

from PIL import Image, ImageFile, ImageTk

from mav_gss_lib.config import load_gss_config
from mav_gss_lib.protocol import (init_nodes, load_command_defs,
                                  try_parse_command, apply_schema,
                                  resolve_ptype)
from mav_gss_lib.transport import (init_zmq_sub, receive_pdu,
                                   poll_monitor, SUB_STATUS, zmq_cleanup)
from mav_gss_lib.parsing import RxPipeline
from mav_gss_lib.imaging import ImageAssembler

ImageFile.LOAD_TRUNCATED_IMAGES = True

IMG_FULL = (640, 480)
IMG_THUMB = (320, 240)

CFG = load_gss_config()
init_nodes(CFG)
CMD_DEFS, _ = load_command_defs()
ZMQ_ADDR = CFG["rx"]["zmq_addr"]
FILE_PTYPE = resolve_ptype("FILE")
RES_PTYPE = resolve_ptype("RES")
POLL_MS = 200


# =============================================================================
#  PACKET → IMAGE CHUNK EXTRACTION
# =============================================================================

def extract_image_event(pkt):
    """Extract image assembler events from a processed Packet.

    Returns one of:
        ("cnt", total)                          -- img_cnt_chunks RES
        ("chunk", filename, chunk_num, chunk_size, data)  -- img_get_chunk FILE
        None                                    -- not image-related
    """
    cmd = pkt.cmd
    if not cmd or pkt.is_uplink_echo:
        return None
    cmd_id = cmd.get("cmd_id", "")

    if cmd_id == "img_cnt_chunks" and cmd.get("pkt_type") == RES_PTYPE:
        args = cmd.get("args", [])
        if args:
            try:
                return ("cnt", int(args[0]))
            except (ValueError, TypeError):
                pass

    elif cmd_id == "img_get_chunk" and cmd.get("pkt_type") == FILE_PTYPE:
        typed = cmd.get("typed_args")
        if not typed:
            return None
        blob_data = filename = chunk_num = chunk_size = None
        for ta in typed:
            if ta["type"] == "blob":
                blob_data = ta["value"]
            elif ta["name"] == "Filename":
                filename = ta["value"]
            elif ta["name"] == "Chunk Number":
                chunk_num = ta["value"]
            elif ta["name"] == "Chunk Size":
                chunk_size = ta["value"]
        # Validate chunk_size is numeric
        try:
            if chunk_size is not None:
                int(chunk_size)
        except (ValueError, TypeError):
            return None
        if blob_data and filename and chunk_num is not None:
            return ("chunk", filename, chunk_num, chunk_size, blob_data)

    return None


# =============================================================================
#  ZMQ RECEIVER THREAD
# =============================================================================

def zmq_receiver(addr, pkt_queue, stop_event):
    """Background thread: subscribe to ZMQ and enqueue raw PDUs."""
    ctx, sock, monitor = init_zmq_sub(addr)
    status = [None]
    try:
        while not stop_event.is_set():
            result = receive_pdu(sock)
            if result is not None:
                pkt_queue.put(result)
            status[0] = poll_monitor(monitor, SUB_STATUS, status[0])
    finally:
        zmq_cleanup(monitor, SUB_STATUS, status[0], sock, ctx)


def replay_receiver(log_dir, pkt_queue, stop_event, delay=0.02):
    """Background thread: replay logged JSONL files as if live."""
    json_dir = os.path.join(log_dir, "json")
    files = sorted(f for f in os.listdir(json_dir)
                   if f.startswith("downlink_") and f.endswith(".jsonl"))
    for fname in files:
        if stop_event.is_set():
            break
        with open(os.path.join(json_dir, fname)) as f:
            for line in f:
                if stop_event.is_set():
                    break
                rec = json.loads(line)
                raw = bytes.fromhex(rec["raw_hex"])
                meta = {"transmitter": rec.get("tx_meta", "")}
                pkt_queue.put((meta, raw))
                time.sleep(delay)


# =============================================================================
#  VIEWER
# =============================================================================

class ImageViewer:
    def __init__(self, replay=False):
        self.root = tk.Tk()
        self.root.title("MAVERIC Image Downlink")
        self.root.configure(bg="black")

        # Status bar
        self.status_var = tk.StringVar(value="Waiting for data...")
        status_bar = tk.Label(self.root, textvariable=self.status_var,
                              bg="#1a1a1a", fg="#00ff87", anchor="w",
                              font=("Menlo", 12), padx=8, pady=4)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        # Canvas
        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.photo = None
        self.canvas_img = None

        # Pipeline
        self.pipeline = RxPipeline(CMD_DEFS, {})
        self.assembler = ImageAssembler("images")
        self.pkt_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.pending_total = None
        self.current_file = None
        self.contiguous_count = 0

        # Start receiver thread
        if replay:
            target = replay_receiver
            args = (CFG["general"]["log_dir"], self.pkt_queue, self.stop_event)
        else:
            target = zmq_receiver
            args = (ZMQ_ADDR, self.pkt_queue, self.stop_event)

        self.thread = threading.Thread(target=target, args=args, daemon=True)
        self.thread.start()

        # Set initial window size for full image
        self.root.geometry(f"{IMG_FULL[0]}x{IMG_FULL[1] + 30}")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(POLL_MS, self.poll)
        self.root.mainloop()

    def on_close(self):
        self.stop_event.set()
        self.root.destroy()

    def poll(self):
        """Drain packet queue, process through pipeline, update display."""
        dirty = False
        drained = 0
        while drained < 50:
            try:
                meta, raw = self.pkt_queue.get_nowait()
            except queue.Empty:
                break
            drained += 1
            try:
                pkt = self.pipeline.process(meta, raw)
            except Exception:
                continue

            event = extract_image_event(pkt)
            if event is None:
                continue

            if event[0] == "cnt":
                self.pending_total = event[1]
                self.status_var.set(f"Chunk count received: {event[1]}")

            elif event[0] == "chunk":
                _, filename, chunk_num, chunk_size, data = event
                self.current_file = filename

                # Apply pending total
                if (self.pending_total is not None
                        and filename not in self.assembler.totals):
                    self.assembler.set_total(filename, self.pending_total)
                    self.pending_total = None

                received, total, complete = self.assembler.feed_chunk(
                    filename, chunk_num, data, chunk_size)

                # Count contiguous from 0
                chunks = self.assembler.chunks.get(filename, {})
                i = 0
                while i in chunks:
                    i += 1
                new_contig = i

                if new_contig > self.contiguous_count:
                    self.contiguous_count = new_contig
                    dirty = True

                total_str = str(total) if total else "?"
                pct = f" ({received * 100 // total}%)" if total else ""
                self.status_var.set(
                    f"{filename}  chunk {chunk_num}  "
                    f"[{received}/{total_str}]{pct}  "
                    f"contiguous: 0-{new_contig - 1}")

                if complete:
                    self.status_var.set(
                        f"{filename} COMPLETE — saved to images/{filename}")

        if dirty:
            self.update_image()

        self.root.after(POLL_MS, self.poll)

    def update_image(self):
        """Decode contiguous chunks and render to canvas."""
        if not self.current_file:
            return
        chunks = self.assembler.chunks.get(self.current_file, {})
        if not chunks or 0 not in chunks:
            return

        # Detect thumbnail vs full from filename
        is_thumb = "thumb" in self.current_file.lower()
        img_size = IMG_THUMB if is_thumb else IMG_FULL

        # Build contiguous byte stream + EOI
        data = bytearray()
        i = 0
        while i in chunks:
            data.extend(chunks[i])
            i += 1
        data.extend(b"\xff\xd9")

        # Black canvas at known dimensions
        canvas_img = Image.new("RGB", img_size, (0, 0, 0))

        try:
            img = Image.open(io.BytesIO(bytes(data)))
            decoded = img.convert("RGB")
            canvas_img.paste(decoded, (0, 0))
        except Exception:
            # Not enough data to decode yet — show black canvas
            pass

        self.photo = ImageTk.PhotoImage(canvas_img)
        if self.canvas_img is None:
            self.canvas_img = self.canvas.create_image(
                0, 0, anchor=tk.NW, image=self.photo)
        else:
            self.canvas.itemconfig(self.canvas_img, image=self.photo)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MAVERIC live image viewer")
    parser.add_argument("--replay", action="store_true",
                        help="Replay from log files instead of live ZMQ")
    args = parser.parse_args()
    ImageViewer(replay=args.replay)
