"""
MAV_RX -- MAVERIC Ground Station Monitor (Textual Dashboard)

STATUS: MAVERIC-only legacy. Backup Textual TUI for RX monitoring.
Not on the platform/adapter migration path. The web UI (MAV_WEB.py)
is the primary operational interface.

Author:  Irfan Annuar - USC ISI SERC
"""

import argparse
import os
import queue
import sys
from pathlib import Path

# Ensure mav_gss_lib is importable when running from backup_control/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Input

from mav_gss_lib.protocol import init_nodes, load_command_defs, resolve_ptype
from mav_gss_lib.transport import (init_zmq_sub, receive_pdu,
                                   poll_monitor, SUB_STATUS, zmq_cleanup)
from mav_gss_lib.parsing import RxPipeline, build_rx_log_record
from mav_gss_lib.logging import SessionLog
from mav_gss_lib.tui_common import (StatusMessage, SplashScreen,
                                    Hints, HelpScreen, ConfigScreen, MavAppBase,
                                    dispatch_common, TS_FULL,
                                    STATUS_BRIEF, STATUS_NORMAL, STATUS_LONG, STATUS_STARTUP)
from mav_gss_lib.config import load_gss_config, get_command_defs_path, get_decoder_yml_path
from mav_gss_lib.imaging import ImageAssembler
from mav_gss_lib.tui_rx import (
    RxHeader, PacketList, PacketDetail,
    RX_HELP_LINES, RX_CONFIG_FIELDS, rx_config_get_values, rx_help_info,
)

CFG = load_gss_config()
init_nodes(CFG)
VERSION = CFG["general"]["version"]
ZMQ_ADDR = CFG["rx"]["zmq_addr"]
ZMQ_RECV_TIMEOUT_MS = 200
LOG_DIR = CFG["general"]["log_dir"]
CMD_DEFS_PATH = get_command_defs_path(CFG)
DECODER_YML_PATH = get_decoder_yml_path(CFG)
MISSION_NAME = CFG["general"].get("mission_name", "Mission")
RX_TITLE = CFG["general"].get("rx_title", f"{MISSION_NAME} Downlink")
MAX_PACKETS = 500
MAX_SEEN_FPS = 10_000
DRAIN_BATCH_MAX = 50
RECEIVING_TIMEOUT = 2.0
SPINNER = ["▸", "▸▸", "▸▸▸", "▸▸▸▸", "▸▸▸▸▸"]


def _load_tx_frequencies(path):
    """Load transmitter frequency labels from the decoder YAML for display."""
    try:
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        return {n: f"{float(i.get('frequency',0))/1e6:.3f} MHz"
                for n, i in data.get("transmitters", {}).items()
                if i.get("frequency") is not None}
    except Exception as e:
        print(f"WARNING: failed to load TX frequencies: {e}", file=sys.stderr)
        return {}


# =============================================================================
#  STATE — widgets read this directly via self.s reference
# =============================================================================

@dataclass
class RxState:
    """All mutable state for the RX downlink monitor.

    Driven by a 60fps tick interval. The ZMQ receiver thread pushes
    raw PDUs into a queue; the UI drains and processes them via RxPipeline.
    Widgets read this dataclass directly via a shared reference.
    """
    packets: deque
    pipeline: RxPipeline
    log: SessionLog | None
    cmd_defs: dict
    session_start: float
    last_watchdog: float
    zmq_addr: str = ""
    first_pkt_ts: str | None = None
    last_pkt_ts: str | None = None
    selected_idx: int = -1
    scroll_offset: int = 0
    detail_open: bool = True
    show_hex: bool = False
    show_wrapper: bool = False
    hide_uplink: bool = True
    logging_enabled: bool = True
    receiving: bool = False
    receiving_unknown: bool = False
    frequency: str = "--"
    error_status: StatusMessage = field(default_factory=StatusMessage)
    status: StatusMessage = field(default_factory=StatusMessage)
    spinner: list = field(default_factory=list)
    spin_idx: int = 0
    _spin_acc: float = 0.0
    # Computed per-tick (avoid recalculating in widgets)
    silence_secs: float = 0.0
    pkt_count: int = 0
    rate_per_min: float = 0.0
    version: str = ""
    schema_count: int = 0
    schema_path: str = ""
    pkt_gen: int = 0
    rx_title: str = "Mission Downlink"
    image_assembler: ImageAssembler = field(default_factory=ImageAssembler)


# =============================================================================
#  ZMQ + DRAIN + LOGGING
# =============================================================================

def _receiver_thread(sock, pkt_queue, stop_event, monitor, status_holder,
                     on_error=None):
    """Background thread: polls ZMQ SUB socket and enqueues received PDUs."""
    while not stop_event.is_set():
        result = receive_pdu(sock, on_error=on_error)
        if result is not None:
            pkt_queue.put(result)
        status_holder[0] = poll_monitor(monitor, SUB_STATUS, status_holder[0])


def _drain_rx_queue(state, pkt_queue):
    """Drain all pending packets from the queue into state, processing each via RxPipeline.

    Returns True if any packets were drained (dirty flag for rendering).
    """
    dirty = False
    drained = 0
    while drained < DRAIN_BATCH_MAX:
        try:
            meta, raw = pkt_queue.get_nowait()
        except queue.Empty:
            break
        dirty = True
        drained += 1
        if state.first_pkt_ts is None:
            state.first_pkt_ts = datetime.now().astimezone().strftime(TS_FULL)
        try:
            pkt_record = state.pipeline.process(meta, raw)
        except Exception as e:
            state.error_status.set(f"Packet error: {e}", STATUS_LONG)
            continue
        if not pkt_record.is_uplink_echo:
            state.last_watchdog = time.time()
            state.receiving_unknown = pkt_record.is_unknown
        if state.pipeline.frequency is not None:
            state.frequency = state.pipeline.frequency
        state.last_pkt_ts = pkt_record.gs_ts
        if state.logging_enabled and state.log:
            try:
                state.log.write_jsonl(build_rx_log_record(pkt_record, VERSION, meta))
                state.log.write_packet(pkt_record)
            except Exception as e:
                state.error_status.set(f"Log error: {e}", STATUS_LONG)
        # Image chunk reassembly
        _feed_image_assembler(state, pkt_record)
        was_full = len(state.packets) >= state.packets.maxlen
        state.packets.append(pkt_record)
        state.pkt_gen += 1
        if was_full and state.selected_idx != -1:
            state.selected_idx = max(-1, state.selected_idx - 1)
    state.receiving = (time.time() - state.last_watchdog) < RECEIVING_TIMEOUT
    return dirty


def _feed_image_assembler(state, pkt):
    """Feed image-related packets to the ImageAssembler."""
    cmd = pkt.cmd
    if not cmd or pkt.is_uplink_echo:
        return
    cmd_id = cmd.get("cmd_id", "")
    if cmd_id == "img_cnt_chunks" and cmd.get("pkt_type") == resolve_ptype("RES"):
        # RES response only contains the count, no filename —
        # store as pending and apply when the first img_get_chunk arrives
        args = cmd.get("args", [])
        if args:
            try:
                state.image_assembler.pending_total = int(args[0])
                state.status.set(
                    f"Image chunk count: {args[0]}", STATUS_NORMAL)
            except (ValueError, TypeError):
                pass
    elif cmd_id == "img_get_chunk" and cmd.get("pkt_type") == resolve_ptype("FILE"):
        typed = cmd.get("typed_args")
        if not typed:
            return
        blob_data = None
        filename = chunk_num = chunk_size = None
        for ta in typed:
            if ta["type"] == "blob":
                blob_data = ta["value"]
            elif ta["name"] == "Filename":
                filename = ta["value"]
            elif ta["name"] == "Chunk Number":
                chunk_num = ta["value"]
            elif ta["name"] == "Chunk Size":
                chunk_size = ta["value"]
        # Validate chunk_size is numeric — old-format packets without
        # a chunk size field cause misparsed args and must be skipped
        try:
            if chunk_size is not None:
                int(chunk_size)
        except (ValueError, TypeError):
            return
        if blob_data and filename and chunk_num is not None:
            # Apply pending total from img_cnt_chunks if not yet set
            asm = state.image_assembler
            pending = getattr(asm, "pending_total", None)
            if pending is not None and filename not in asm.totals:
                asm.set_total(filename, pending)
                asm.pending_total = None
            received, total, complete = asm.feed_chunk(
                filename, chunk_num, blob_data, chunk_size)
            if complete:
                state.status.set(
                    f"Image complete: images/{filename} ({received} chunks)",
                    STATUS_LONG)


def _toggle_flag(state, attr, label):
    """Toggle a boolean state flag and show a brief ON/OFF status."""
    setattr(state, attr, not getattr(state, attr))
    state.status.set(f"{label} {'ON' if getattr(state, attr) else 'OFF'}", STATUS_BRIEF)

def _dispatch_rx_command(state, line):
    """Dispatch an RX-specific command (hex, ul, wrapper, detail, hclear, live)."""
    cmd = line.lower()
    common = dispatch_common(state, cmd)
    if isinstance(common, tuple) and common[0] == "tag":
        tag = common[1]
        if not tag.strip():
            state.status.set("Usage: tag <name>", STATUS_NORMAL); return True
        if state.log:
            state.log.rename(tag)
            state.status.set(f"Log tagged: {tag}", STATUS_BRIEF)
        else:
            state.status.set("Logging disabled", STATUS_BRIEF)
        return True
    if isinstance(common, tuple) and common[0] == "log":
        tag = common[1]
        if state.log:
            state.log.write_summary(state.pipeline.packet_count, state.session_start,
                state.first_pkt_ts, state.last_pkt_ts,
                unique=len(state.pipeline.seen_fps),
                duplicates=state.pipeline.packet_count - len(state.pipeline.seen_fps),
                unknown=state.pipeline.unknown_count,
                uplink_echoes=state.pipeline.uplink_echo_count)
            state.log.new_session(tag)
            state.pipeline.reset_counts()
            state.session_start = time.time()
            state.first_pkt_ts = None; state.last_pkt_ts = None
            state.status.set(f"New log: {os.path.basename(state.log.text_path)}", STATUS_BRIEF)
        else:
            state.status.set("Logging disabled", STATUS_BRIEF)
        return True
    if common is not None: return common
    if cmd == 'hex': _toggle_flag(state, 'show_hex', 'HEX')
    elif cmd == 'ul': _toggle_flag(state, 'hide_uplink', 'Hide Uplink')
    elif cmd == 'wrapper': _toggle_flag(state, 'show_wrapper', 'Wrapper')
    elif cmd == 'detail':
        state.detail_open = not state.detail_open
    elif cmd == 'hclear':
        if state.packets:
            state.status.set(f"Cleared {len(state.packets)} packets", STATUS_BRIEF)
            state.packets.clear(); state.selected_idx = -1; state.scroll_offset = 0; state.pkt_gen += 1
        else: state.status.set("History already empty", STATUS_BRIEF)
    elif cmd == 'live': state.selected_idx = -1
    else: state.status.set(f"Unknown command: {line}", STATUS_NORMAL)
    return True


# =============================================================================
#  APP
# =============================================================================

class MavRxApp(MavAppBase):
    """Textual app for real-time downlink packet monitoring.

    Subscribes to GNU Radio's ZMQ PUB socket, decodes CSP/command
    frames via RxPipeline, and renders a scrollable packet list with
    toggleable detail panel. Supports hex view, uplink echo filtering,
    duplicate detection, and session logging.
    """
    CSS = """
    Screen { background: black; padding-right: 1; }
    SplashScreen { background: rgba(0, 0, 0, 0.5); }
    SplashScreen * { background: transparent; }
    #main-area { height: 1fr; }
    #content-area { width: 1fr; }
    #bottom-bar { dock: bottom; height: 2; }
    #rx-input { height: 1; border: none; padding: 0; }
    #rx-input:focus .input--cursor { background: #00bfff; color: #000000; }
    """
    _WIDGET_QUERY = "RxHeader, PacketList, PacketDetail"
    _INPUT_ID = "rx-input"
    BINDINGS = [
        Binding("ctrl+c", "quit_or_close", "Quit", priority=True),
        Binding("escape", "close_panel", "Close", show=False),
        Binding("tab", "toggle_focus", "Tab", show=False),
        Binding("up", "select_prev", "Up", show=False),
        Binding("down", "select_next", "Down", show=False),
        Binding("pageup", "page_up", "PgUp", show=False),
        Binding("pagedown", "page_down", "PgDn", show=False),
        Binding("shift+down", "jump_bottom", "Jump Bottom", show=False),
    ]

    def __init__(self, show_splash=True):
        super().__init__()
        self._show_splash = show_splash
        self._tx_freq_map = _load_tx_frequencies(DECODER_YML_PATH)
        now = time.time()
        cmd_defs, self._schema_warning = load_command_defs(CMD_DEFS_PATH)
        self.state = RxState(
            packets=deque(maxlen=MAX_PACKETS), pipeline=RxPipeline(cmd_defs, self._tx_freq_map, MAX_SEEN_FPS),
            log=SessionLog(LOG_DIR, ZMQ_ADDR, version=VERSION), cmd_defs=cmd_defs,
            session_start=now, last_watchdog=now - RECEIVING_TIMEOUT,
            zmq_addr=ZMQ_ADDR, version=VERSION, schema_count=len(cmd_defs),
            schema_path=CMD_DEFS_PATH, spinner=SPINNER, rx_title=RX_TITLE,
            frequency=next(iter(self._tx_freq_map.values()), "N/A"),
        )
        if self._schema_warning:
            self.state.error_status.set(f"SCHEMA: {self._schema_warning}", STATUS_STARTUP)
        self._zmq_ctx, self._sock, self._zmq_monitor = init_zmq_sub(ZMQ_ADDR, ZMQ_RECV_TIMEOUT_MS)
        self._pkt_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._zmq_status = ["OFFLINE"]
        self.result = None

    def compose(self) -> ComposeResult:
        s = self.state
        yield RxHeader(s, self._zmq_status, self._pkt_queue, id="rx-header")
        with Horizontal(id="main-area"):
            with Vertical(id="content-area"):
                yield PacketList(s, id="packet-list")
                yield PacketDetail(s, id="packet-detail")
        with Vertical(id="bottom-bar"):
            yield Input(id="rx-input")
            yield Hints(self._hint_text)

    def on_mount(self):
        if self._show_splash:
            rx_freq = next(iter(self._tx_freq_map.values()), "N/A")
            self.push_screen(SplashScreen(
                subtitle=f"{RX_TITLE}  v{VERSION}",
                config_lines=[("Config", "maveric_gss.yml"), ("ZMQ SUB", ZMQ_ADDR),
                    ("Frequency", rx_freq), ("Decoder", DECODER_YML_PATH),
                    ("Commands", CMD_DEFS_PATH), ("Log Text", f"{LOG_DIR}/text"),
                    ("Log JSON", f"{LOG_DIR}/json")]))
        self._rx_thread = threading.Thread(
            target=_receiver_thread,
            args=(self._sock, self._pkt_queue, self._stop_event,
                  self._zmq_monitor, self._zmq_status,
                  lambda msg: self.state.error_status.set(msg, STATUS_LONG)),
            daemon=True)
        self._rx_thread.start()
        self.set_interval(1/60, self._tick)
        self._last_tick_time = time.time()
        self._last_header_sec = -1
        self.query_one("#rx-input").focus()

    def _tick(self):
        s = self.state
        # Thread watchdog: restart RX thread if it died unexpectedly
        if not self._rx_thread.is_alive() and not self._stop_event.is_set():
            s.error_status.set("RX THREAD DEAD — restarting", STATUS_LONG)
            self._rx_thread = threading.Thread(
                target=_receiver_thread,
                args=(self._sock, self._pkt_queue, self._stop_event,
                      self._zmq_monitor, self._zmq_status,
                      lambda msg: s.error_status.set(msg, STATUS_LONG)),
                daemon=True)
            self._rx_thread.start()
            print("WARNING: RX thread died and was restarted", file=sys.stderr)
        if s.logging_enabled and s.log and not s.log._writer.is_alive():
            s.error_status.set("LOG WRITER DEAD — logging stopped", STATUS_LONG)
            s.logging_enabled = False
            print("WARNING: RX log writer thread died", file=sys.stderr)
        now = time.time()
        dt = now - self._last_tick_time
        self._last_tick_time = now
        pkt_dirty = _drain_rx_queue(s, self._pkt_queue)
        old_spin = s.spin_idx
        s._spin_acc = (s._spin_acc + (30.0 if s.receiving else 3.0) * dt) % 40.0
        s.spin_idx = int(s._spin_acc) % len(SPINNER)
        spin_dirty = (s.spin_idx != old_spin)
        status_dirty = s.error_status.check_expiry() or s.status.check_expiry()
        old_silence = s.silence_secs
        s.silence_secs = time.time() - s.last_watchdog
        silence_dirty = not s.receiving and int(s.silence_secs * 10) != int(old_silence * 10)
        s.pkt_count = s.pipeline.packet_count
        s.rate_per_min = len(s.pipeline.pkt_times)
        if s.selected_idx == -1:
            s.scroll_offset = 0
        self.query_one("#packet-detail").display = s.detail_open
        # Selective refresh: only redraw widgets whose data actually changed
        if pkt_dirty or spin_dirty or status_dirty or silence_dirty:
            self.query_one("#packet-list").refresh()
        if pkt_dirty:
            self.query_one("#packet-detail").refresh()
        now_sec = int(time.time())
        zmq_offline = self._zmq_status[0] != "ONLINE"
        if now_sec != self._last_header_sec or zmq_offline:
            self._last_header_sec = now_sec
            self.query_one("#rx-header").refresh()

    def action_quit_or_close(self):
        self._cleanup(); self.exit()

    def action_close_panel(self):
        s = self.state
        if s.detail_open: s.detail_open = False
        self._act()

    @property
    def _plist(self):
        return self.query_one("#packet-list", PacketList)

    def action_toggle_focus(self):
        if isinstance(self.focused, Input):
            self.query_one("#packet-list", PacketList).focus()
        else:
            self.query_one("#rx-input", Input).focus()

    def on_descendant_focus(self, event):
        self.query_one("Hints").refresh()

    def _hint_text(self):
        if isinstance(self.focused, PacketList):
            ctx = [("↑↓", "select"), ("⏎", "detail"), ("⇧↓", "live")]
            tab_next = "input"
        else:
            ctx = [("cfg", "")]
            tab_next = "packets"
        pinned = [("⇥", tab_next), ("?", "help"), ("^C", "quit")]
        return ctx, pinned

    def _navigate(self, delta):
        """Move selection by one step (negative=up, positive=down)."""
        if isinstance(self.focused, Input): return
        s, pl = self.state, self._plist
        if delta < 0:
            if s.selected_idx == -1:
                s.selected_idx = pl._find_last_visible() if s.packets else 0
            elif s.selected_idx > 0:
                s.selected_idx = pl._find_prev_visible(s.selected_idx)
        elif s.selected_idx != -1:
            s.selected_idx = pl._find_next_visible(s.selected_idx)
        self._act()

    def _navigate_page(self, delta):
        """Move selection by a page (negative=up, positive=down)."""
        if isinstance(self.focused, Input): return
        s, pl = self.state, self._plist
        if delta < 0 and s.selected_idx == -1:
            s.selected_idx = pl._find_last_visible() if s.packets else 0
        if s.selected_idx == -1: self._act(); return
        for _ in range(max(1, self.size.height - 10)):
            nxt = pl._find_prev_visible(s.selected_idx) if delta < 0 else pl._find_next_visible(s.selected_idx)
            if delta < 0 and nxt == s.selected_idx: break
            if delta > 0 and nxt == -1: s.selected_idx = -1; break
            s.selected_idx = nxt
        self._act()

    def action_select_prev(self): self._navigate(-1)
    def action_select_next(self): self._navigate(1)
    def action_page_up(self): self._navigate_page(-1)
    def action_page_down(self): self._navigate_page(1)

    def action_jump_bottom(self):
        if isinstance(self.focused, Input): return
        self.state.selected_idx = -1
        self._act()

    def _dispatch(self, line):
        return _dispatch_rx_command(self.state, line)

    def _open_help(self):
        v, sc, sp, lp = rx_help_info(self.state)
        self.push_screen(HelpScreen(RX_HELP_LINES, version=v,
                                    schema_count=sc, schema_path=sp, log_path=lp))

    def _open_config(self):
        s = self.state
        self.push_screen(ConfigScreen(RX_CONFIG_FIELDS, rx_config_get_values(s)), self._on_config_done)

    def _on_config_done(self, values):
        s = self.state
        def _apply(attr, key, label):
            new = values.get(key, "OFF").upper() == "ON"
            if new != getattr(s, attr):
                setattr(s, attr, new)
                s.status.set(f"{label} {'ON' if new else 'OFF'}", STATUS_BRIEF)
        for label, key, _ in RX_CONFIG_FIELDS:
            _apply(key, key, label)
        self._act()

    # -- Cleanup --------------------------------------------------------------

    def _cleanup(self):
        s = self.state
        self._stop_event.set()
        self._rx_thread.join(timeout=1)
        if self._rx_thread.is_alive():
            print("WARNING: RX thread did not terminate cleanly", file=sys.stderr)
        try:
            if s.log:
                s.log.write_summary(s.pipeline.packet_count, s.session_start,
                    s.first_pkt_ts, s.last_pkt_ts, unique=len(s.pipeline.seen_fps),
                    duplicates=s.pipeline.packet_count - len(s.pipeline.seen_fps),
                    unknown=s.pipeline.unknown_count, uplink_echoes=s.pipeline.uplink_echo_count)
                s.log.close()
        except Exception as e:
            print(f"WARNING: failed to close RX session log: {e}", file=sys.stderr)
        zmq_cleanup(self._zmq_monitor, SUB_STATUS, self._zmq_status[0], self._sock, self._zmq_ctx)
        self.result = {
            "packet_count": s.pipeline.packet_count, "unique": len(s.pipeline.seen_fps),
            "duplicates": s.pipeline.packet_count - len(s.pipeline.seen_fps),
            "unknown": s.pipeline.unknown_count, "uplink_echoes": s.pipeline.uplink_echo_count,
            "duration": time.time() - s.session_start,
            "log_txt": s.log.text_path if s.log else None,
            "log_jsonl": s.log.jsonl_path if s.log else None,
        }


def main():
    parser = argparse.ArgumentParser(description="MAV_RX -- MAVERIC RX Monitor")
    parser.add_argument("--nosplash", action="store_true")
    args = parser.parse_args()
    app = MavRxApp(show_splash=not args.nosplash)
    app.run()
    if app.return_value == "restart":
        print("\n  Restarting...\n")
        argv = sys.argv[:]
        if "--nosplash" not in argv: argv.append("--nosplash")
        os.execv(sys.executable, [sys.executable] + argv)
    r = app.result
    if r:
        print(f"\n  Session ended\n  Packets: {r['packet_count']} "
              f"({r['unique']} unique, {r['duplicates']} dup, {r['unknown']} unknown, "
              f"{r['uplink_echoes']} UL echo)\n  Duration: {r['duration']:.0f}s")
        if r.get("log_txt"): print(f"  Log: {r['log_txt']}")
        print()


if __name__ == "__main__":
    main()
