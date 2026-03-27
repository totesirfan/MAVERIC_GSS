"""
MAV_RX -- MAVERIC Ground Station Monitor (Textual Dashboard)

Author:  Irfan Annuar - USC ISI SERC
"""

import argparse
import gc
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Input

from mav_gss_lib.protocol import init_nodes, load_command_defs
from mav_gss_lib.transport import (init_zmq_sub, receive_pdu,
                                   poll_monitor, _SUB_STATUS, zmq_cleanup)
from mav_gss_lib.parsing import RxPipeline, build_rx_log_record
from mav_gss_lib.logging import SessionLog
from mav_gss_lib.tui_common import (StatusMessage, SplashScreen,
                                    Hints, HelpPanel, ConfigScreen)
from mav_gss_lib.config import load_gss_config
from mav_gss_lib.tui_rx import (
    RxHeader, PacketList, PacketDetail, RxStatusBar,
    RX_HELP_LINES, RX_CONFIG_FIELDS, rx_config_get_values, _rx_help_info,
)

CFG = load_gss_config()
init_nodes(CFG)
VERSION = CFG["general"]["version"]
ZMQ_ADDR = CFG["rx"]["zmq_addr"]
ZMQ_RECV_TIMEOUT_MS = 200
LOG_DIR = CFG["general"]["log_dir"]
CMD_DEFS_PATH = CFG["general"]["command_defs"]
DECODER_YML_PATH = CFG["general"]["decoder_yml"]
MAX_PACKETS = 500
MAX_SEEN_FPS = 10_000
GC_INTERVAL = 300
RECEIVING_TIMEOUT = 2.0
SPINNER = ["█", "▓", "▒", "░", "▒", "▓"]


def _load_tx_frequencies(path):
    try:
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        return {n: f"{float(i.get('frequency',0))/1e6:.3f} MHz"
                for n, i in data.get("transmitters", {}).items()
                if i.get("frequency") is not None}
    except Exception:
        return {}


# =============================================================================
#  STATE — widgets read this directly via self.s reference
# =============================================================================

@dataclass
class RxState:
    packets: list
    pipeline: RxPipeline
    log: SessionLog | None
    cmd_defs: dict
    session_start: float
    last_watchdog: float
    zmq_addr: str = ""
    first_pkt_ts: str | None = None
    last_pkt_ts: str | None = None
    last_gc: float = 0.0
    selected_idx: int = -1
    scroll_offset: int = 0
    detail_open: bool = True
    help_open: bool = False
    show_hex: bool = True
    logging_enabled: bool = True
    receiving: bool = False
    frequency: str = "--"
    error_status: StatusMessage = field(default_factory=StatusMessage)
    status: StatusMessage = field(default_factory=StatusMessage)
    spin_idx: int = 0
    # Computed per-tick (avoid recalculating in widgets)
    silence_secs: float = 0.0
    pkt_count: int = 0
    rate_per_min: float = 0.0
    version: str = ""
    schema_count: int = 0
    schema_path: str = ""


# =============================================================================
#  ZMQ + DRAIN + LOGGING
# =============================================================================

def _receiver_thread(sock, pkt_queue, stop_event, monitor, status_holder,
                     on_error=None):
    while not stop_event.is_set():
        result = receive_pdu(sock, on_error=on_error)
        if result is not None:
            pkt_queue.put(result)
        status_holder[0] = poll_monitor(monitor, _SUB_STATUS, status_holder[0])


def _drain_rx_queue(state, pkt_queue):
    while True:
        try:
            meta, raw = pkt_queue.get_nowait()
        except queue.Empty:
            break
        state.last_watchdog = time.time()
        if state.first_pkt_ts is None:
            state.first_pkt_ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        try:
            pkt_record = state.pipeline.process(meta, raw)
        except Exception as e:
            state.error_status.set(f"Packet error: {e}", 5)
            continue
        if state.pipeline.frequency is not None:
            state.frequency = state.pipeline.frequency
        state.last_pkt_ts = pkt_record["gs_ts"]
        if state.logging_enabled and state.log:
            try:
                state.log.write_jsonl(build_rx_log_record(pkt_record, VERSION, meta))
                state.log.write_packet(pkt_record)
            except Exception as e:
                state.error_status.set(f"Log error: {e}", 5)
        state.packets.append(pkt_record)
        if len(state.packets) > MAX_PACKETS:
            del state.packets[:len(state.packets) - MAX_PACKETS]
        if state.selected_idx != -1 and state.selected_idx >= len(state.packets) - 1:
            state.selected_idx = len(state.packets) - 1
    state.receiving = (time.time() - state.last_watchdog) < RECEIVING_TIMEOUT


def _toggle_logging(state):
    if state.logging_enabled:
        state.logging_enabled = False
        if state.log:
            try:
                state.log.write_summary(
                    state.pipeline.packet_count, state.session_start,
                    state.first_pkt_ts, state.last_pkt_ts,
                    unique=len(state.pipeline.seen_fps),
                    duplicates=state.pipeline.packet_count - len(state.pipeline.seen_fps),
                    unknown=state.pipeline.unknown_count,
                    uplink_echoes=state.pipeline.uplink_echo_count)
            except Exception: pass
            finally:
                try: state.log.close()
                except Exception: pass
                state.log = None
        return "Logging OFF", 2
    try:
        state.log = SessionLog(LOG_DIR, ZMQ_ADDR, version=VERSION)
    except Exception as e:
        state.log = None
        return f"Log error: {e}", 5
    state.logging_enabled = True
    return f"Logging ON: {state.log.text_path}", 3


def _dispatch_rx_command(state, line):
    cmd = line.lower()
    if cmd in ('q', 'quit', 'exit'): return "break"
    if cmd == 'help':
        state.help_open = not state.help_open
    elif cmd in ('cfg', 'config'):
        state.help_open = False; return "open_config"
    elif cmd == 'hex':
        state.show_hex = not state.show_hex
        state.status.set(f"HEX {'ON' if state.show_hex else 'OFF'}", 2)
    elif cmd == 'log':
        msg, dur = _toggle_logging(state)
        state.status.set(msg, dur)
    elif cmd == 'detail':
        state.detail_open = not state.detail_open
    elif cmd == 'hclear':
        if state.packets:
            state.status.set(f"Cleared {len(state.packets)} packets", 2)
            state.packets.clear(); state.selected_idx = -1; state.scroll_offset = 0
        else: state.status.set("History already empty", 2)
    elif cmd == 'live': state.selected_idx = -1
    else: state.status.set(f"Unknown command: {line}", 3)
    return True


# =============================================================================
#  APP
# =============================================================================

class MavRxApp(App):
    CSS = """
    Screen { background: black; padding-right: 1; }
    SplashScreen { background: rgba(0, 0, 0, 0.5); }
    SplashScreen * { background: transparent; }
    #main-area { height: 1fr; }
    #content-area { width: 1fr; }
    #bottom-bar { dock: bottom; height: 3; }
    #rx-input { height: 1; border: none; padding: 0; }
    """
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("ctrl+c", "quit_or_close", "Quit", priority=True),
        Binding("escape", "close_panel", "Close", show=False),
        Binding("up", "select_prev", "Up", show=False),
        Binding("down", "select_next", "Down", show=False),
        Binding("pageup", "page_up", "PgUp", show=False),
        Binding("pagedown", "page_down", "PgDn", show=False),
    ]

    def __init__(self, show_splash=True):
        super().__init__()
        self._show_splash = show_splash
        self._tx_freq_map = _load_tx_frequencies(DECODER_YML_PATH)
        now = time.time()
        cmd_defs, self._schema_warning = load_command_defs(CMD_DEFS_PATH)
        self.state = RxState(
            packets=[], pipeline=RxPipeline(cmd_defs, self._tx_freq_map, MAX_SEEN_FPS),
            log=SessionLog(LOG_DIR, ZMQ_ADDR, version=VERSION), cmd_defs=cmd_defs,
            session_start=now, last_watchdog=now, last_gc=now,
            zmq_addr=ZMQ_ADDR, version=VERSION, schema_count=len(cmd_defs),
            schema_path=CMD_DEFS_PATH,
            frequency=next(iter(self._tx_freq_map.values()), "N/A"),
        )
        if self._schema_warning:
            self.state.error_status.set(f"SCHEMA: {self._schema_warning}", 10)
        self._zmq_ctx, self._sock, self._zmq_monitor = init_zmq_sub(ZMQ_ADDR, ZMQ_RECV_TIMEOUT_MS)
        self._pkt_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._zmq_status = ["SUB"]
        self.result = None

    def compose(self) -> ComposeResult:
        s = self.state
        yield RxHeader(s, self._zmq_status, self._pkt_queue, id="rx-header")
        with Horizontal(id="main-area"):
            with Vertical(id="content-area"):
                yield PacketList(s, spinner=SPINNER, id="packet-list")
                yield PacketDetail(s, id="packet-detail")
            yield HelpPanel(s, RX_HELP_LINES, "Esc: close", _rx_help_info, id="help-panel")
        with Vertical(id="bottom-bar"):
            yield RxStatusBar(s, id="status-bar")
            yield Input(id="rx-input", placeholder="> ")
            yield Hints(" Enter: detail | cfg | help | Ctrl+C: quit")

    def on_mount(self):
        if self._show_splash:
            rx_freq = next(iter(self._tx_freq_map.values()), "N/A")
            self.push_screen(SplashScreen(
                subtitle=f"MAVERIC RX Monitor  v{VERSION}",
                config_lines=[("Config", "maveric_gss.yml"), ("ZMQ SUB", ZMQ_ADDR),
                    ("Frequency", rx_freq), ("Decoder", DECODER_YML_PATH),
                    ("Commands", CMD_DEFS_PATH), ("Log Text", f"{LOG_DIR}/text"),
                    ("Log JSON", f"{LOG_DIR}/json")]))
        self._rx_thread = threading.Thread(
            target=_receiver_thread,
            args=(self._sock, self._pkt_queue, self._stop_event,
                  self._zmq_monitor, self._zmq_status,
                  lambda msg: self.state.error_status.set(msg, 5)),
            daemon=True)
        self._rx_thread.start()
        self.set_interval(0.1, self._tick)
        self.query_one("#rx-input").focus()

    def _tick(self):
        s = self.state
        _drain_rx_queue(s, self._pkt_queue)
        if time.time() - s.last_gc > GC_INTERVAL:
            gc.collect(); s.last_gc = time.time()
        s.spin_idx = (s.spin_idx + 1) % len(SPINNER)
        s.error_status.check_expiry(); s.status.check_expiry()
        s.silence_secs = time.time() - s.last_watchdog
        s.pkt_count = s.pipeline.packet_count
        now = time.time()
        s.rate_per_min = sum(1 for t in s.pipeline.pkt_times if t > now - 60.0)
        auto = (s.selected_idx == -1)
        if not auto and s.packets:
            actual = s.selected_idx
            plist = self.query_one("#packet-list", PacketList)
            lh = plist.content_size.height - 2
            if lh > 0:
                if actual < s.scroll_offset: s.scroll_offset = actual
                elif actual >= s.scroll_offset + lh: s.scroll_offset = actual - lh + 1
                s.scroll_offset = max(0, s.scroll_offset)
        else:
            s.scroll_offset = 0
        self.query_one("#packet-detail").display = s.detail_open
        self.query_one("#help-panel").display = s.help_open
        for w in self.query("RxHeader, PacketList, PacketDetail, RxStatusBar, HelpPanel"):
            w.refresh()

    def _act(self):
        for w in self.query("RxHeader, PacketList, PacketDetail, RxStatusBar, HelpPanel"):
            w.refresh()

    def action_quit_or_close(self):
        s = self.state
        if s.help_open: s.help_open = False; self._act(); return
        self._cleanup(); self.exit()

    def action_close_panel(self):
        s = self.state
        if s.help_open: s.help_open = False
        elif s.detail_open: s.detail_open = False
        self._act()

    def action_select_prev(self):
        s = self.state
        if s.selected_idx == -1:
            s.selected_idx = len(s.packets) - 1 if s.packets else 0
        elif s.selected_idx > 0: s.selected_idx -= 1
        self._act()

    def action_select_next(self):
        s = self.state
        if s.selected_idx != -1:
            if s.selected_idx < len(s.packets) - 1: s.selected_idx += 1
            else: s.selected_idx = -1
        self._act()

    def action_page_up(self):
        s = self.state
        if s.selected_idx == -1: s.selected_idx = len(s.packets) - 1 if s.packets else 0
        s.selected_idx = max(0, s.selected_idx - max(1, self.size.height - 10))
        self._act()

    def action_page_down(self):
        s = self.state
        if s.selected_idx != -1:
            s.selected_idx = min(len(s.packets) - 1, s.selected_idx + max(1, self.size.height - 10))
        self._act()

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id != "rx-input": return
        s = self.state
        line = event.value.strip()
        self.query_one("#rx-input", Input).value = ""
        if not line: s.detail_open = not s.detail_open; self._act(); return
        result = _dispatch_rx_command(s, line)
        if result == "break": self._cleanup(); self.exit(); return
        if result == "open_config":
            self.push_screen(ConfigScreen(RX_CONFIG_FIELDS, rx_config_get_values(s)), self._on_config_done)
            return
        self._act()

    def _on_config_done(self, values):
        s = self.state
        new_hex = (values.get("show_hex", "OFF").upper() == "ON")
        new_log = (values.get("logging", "OFF").upper() == "ON")
        if new_hex != s.show_hex:
            s.show_hex = new_hex; s.status.set(f"HEX {'ON' if s.show_hex else 'OFF'}", 2)
        if new_log != s.logging_enabled:
            msg, dur = _toggle_logging(s); s.status.set(msg, dur)
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
        except Exception: pass
        zmq_cleanup(self._zmq_monitor, _SUB_STATUS, self._zmq_status[0], self._sock, self._zmq_ctx)
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
    r = app.result
    if r:
        print(f"\n  Session ended\n  Packets: {r['packet_count']} "
              f"({r['unique']} unique, {r['duplicates']} dup, {r['unknown']} unknown, "
              f"{r['uplink_echoes']} UL echo)\n  Duration: {r['duration']:.0f}s")
        if r.get("log_txt"): print(f"  Log: {r['log_txt']}")
        print()


if __name__ == "__main__":
    main()
