"""Tests for the AX.25 noise filter (gr-satellites garbage-frame drop)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.protocols.frame_detect import is_noise_frame


class TestIsNoiseFrame(unittest.TestCase):
    """Unit tests for the pure detector."""

    def test_ax25_without_delimiter_is_noise(self):
        self.assertTrue(is_noise_frame("AX.25", b"\x01\x02\x03\x04\x05"))

    def test_ax25_with_delimiter_is_not_noise(self):
        payload = b"\xaa" * 14 + b"\x03\xf0" + b"payload"
        self.assertFalse(is_noise_frame("AX.25", payload))

    def test_ax25_with_delimiter_at_offset_zero_is_not_noise(self):
        self.assertFalse(is_noise_frame("AX.25", b"\x03\xf0" + b"whatever"))

    def test_asm_golay_without_delimiter_is_not_noise(self):
        self.assertFalse(is_noise_frame("ASM+GOLAY", b"\x01\x02\x03\x04\x05"))

    def test_unknown_frame_type_is_not_noise(self):
        self.assertFalse(is_noise_frame("UNKNOWN", b"\x01\x02\x03\x04"))

    def test_empty_ax25_payload_is_noise(self):
        self.assertTrue(is_noise_frame("AX.25", b""))


from mav_gss_lib.web_runtime.state import create_runtime


META_AX25 = {"transmitter": "9k6 FSK AX.25 downlink"}
META_GOLAY = {"transmitter": "4k8 FSK AX100 ASM+Golay downlink"}


class TestRxServiceShouldDropNoise(unittest.TestCase):
    """RxService._should_drop_noise mirrors the _should_drop_rx pattern."""

    def setUp(self):
        self.runtime = create_runtime()

    def test_drops_ax25_without_delimiter(self):
        self.assertTrue(self.runtime.rx._should_drop_noise(META_AX25, b"\x01\x02\x03\x04"))

    def test_keeps_ax25_with_delimiter(self):
        payload = b"\xaa" * 14 + b"\x03\xf0" + b"payload"
        self.assertFalse(self.runtime.rx._should_drop_noise(META_AX25, payload))

    def test_keeps_asm_golay_without_delimiter(self):
        self.assertFalse(self.runtime.rx._should_drop_noise(META_GOLAY, b"\x01\x02\x03\x04"))

    def test_keeps_unknown_transmitter(self):
        self.assertFalse(
            self.runtime.rx._should_drop_noise({"transmitter": "mystery"}, b"\x01\x02")
        )


import asyncio
import json


class TestBroadcastLoopSuppressesNoise(unittest.TestCase):
    """End-to-end: a noise PDU queued into RxService produces no side effects.

    Covers the full side-effect table from the spec:
      - RxPipeline counters untouched
      - SessionLog not called
      - self.packets deque stays empty
      - No packet broadcasts to /ws/rx clients
      - No traffic_status broadcast to /ws/session clients
      - self.last_rx_at stays 0
      - Adapter on_packet_received hook not invoked
    """

    def setUp(self):
        self.runtime = create_runtime()
        self.rx = self.runtime.rx

        # broadcast_loop uses the module-level broadcast_safe for BOTH packet
        # broadcasts (to self.clients) and session traffic_status (to
        # runtime.session_clients). Distinguish by client-list identity.
        self.rx_clients_msgs: list = []
        self.session_clients_msgs: list = []

        rx_client_list_id = id(self.rx.clients)
        session_client_list_id = id(self.runtime.session_clients)

        async def _capture_broadcast(clients, lock, text):
            if id(clients) == rx_client_list_id:
                self.rx_clients_msgs.append(text)
            elif id(clients) == session_client_list_id:
                self.session_clients_msgs.append(text)
            else:
                raise AssertionError(f"broadcast to unknown client list: {clients!r}")

        import mav_gss_lib.web_runtime.rx_service as rx_mod
        self._orig_broadcast_safe = rx_mod.broadcast_safe
        rx_mod.broadcast_safe = _capture_broadcast

        # Spy on the adapter plugin hook if present.
        self.hook_calls: list = []
        original_hook = getattr(self.runtime.adapter, "on_packet_received", None)

        def _spy(pkt):
            self.hook_calls.append(pkt)
            return None

        self.runtime.adapter.on_packet_received = _spy
        self._orig_hook = original_hook

        # Spy on the SessionLog so we can assert write_jsonl / write_packet
        # are not called for filtered noise. Using a real truthy object (not
        # None) is required — the live broadcast_loop guards writes with
        # `if self.log:`, so a None value would silently pass the suppression
        # assertion and tell us nothing about the guard's behaviour.
        class _SpyLog:
            def __init__(self) -> None:
                self.jsonl_calls: list = []
                self.packet_calls: list = []

            def write_jsonl(self, record) -> None:
                self.jsonl_calls.append(record)

            def write_packet(self, pkt, adapter=None) -> None:
                self.packet_calls.append((pkt, adapter))

        self.spy_log = _SpyLog()
        self.rx.log = self.spy_log

    def tearDown(self):
        import mav_gss_lib.web_runtime.rx_service as rx_mod
        rx_mod.broadcast_safe = self._orig_broadcast_safe
        if self._orig_hook is None:
            try:
                delattr(self.runtime.adapter, "on_packet_received")
            except AttributeError:
                pass
        else:
            self.runtime.adapter.on_packet_received = self._orig_hook

    def _run_loop_until_drained(self):
        """Run broadcast_loop once: drain the queue then exit via broadcast_stop."""
        self.rx.broadcast_stop = True
        asyncio.run(self.rx.broadcast_loop())

    def _packet_broadcasts(self):
        out = []
        for text in self.rx_clients_msgs:
            try:
                obj = json.loads(text)
            except ValueError:
                continue
            if obj.get("type") == "packet":
                out.append(obj)
        return out

    def _traffic_status_broadcasts(self):
        out = []
        for text in self.session_clients_msgs:
            try:
                obj = json.loads(text)
            except ValueError:
                continue
            if obj.get("type") == "traffic_status":
                out.append(obj)
        return out

    def test_noise_frame_produces_no_side_effects(self):
        meta = {"transmitter": "9k6 FSK AX.25 downlink"}
        raw = b"\x01\x02\x03\x04\x05\x06"  # no 03 F0 anywhere
        self.rx.queue.put((self.runtime.session.generation, meta, raw))

        self._run_loop_until_drained()

        self.assertEqual(self.rx.pipeline.total_count, 0)
        self.assertEqual(self.rx.pipeline.unknown_count, 0)
        self.assertEqual(self.rx.pipeline.packet_count, 0)
        self.assertIsNone(self.rx.pipeline.last_arrival)
        self.assertEqual(list(self.rx.pipeline.pkt_times), [])

        self.assertEqual(self._packet_broadcasts(), [])
        self.assertEqual(self._traffic_status_broadcasts(), [])
        self.assertEqual(len(self.rx.packets), 0)

        self.assertEqual(self.rx.last_rx_at, 0.0)
        self.assertFalse(self.rx._was_traffic_active)

        self.assertEqual(self.hook_calls, [])

        self.assertEqual(self.spy_log.jsonl_calls, [])
        self.assertEqual(self.spy_log.packet_calls, [])

    def test_real_ax25_frame_still_flows_through(self):
        """Regression guard: a well-formed AX.25 packet is NOT filtered."""
        from mav_gss_lib.protocols.ax25 import AX25Config
        from mav_gss_lib.protocols.csp import CSPConfig
        from mav_gss_lib.missions.maveric.wire_format import build_cmd_raw

        csp = CSPConfig()
        ax25 = AX25Config()
        raw_cmd = build_cmd_raw(6, 2, "com_ping", "")
        payload = ax25.wrap(csp.wrap(raw_cmd))

        meta = {"transmitter": "9k6 FSK AX.25 downlink"}
        self.rx.queue.put((self.runtime.session.generation, meta, payload))

        self._run_loop_until_drained()

        self.assertEqual(self.rx.pipeline.total_count, 1)
        self.assertEqual(len(self._packet_broadcasts()), 1)
        self.assertTrue(self.rx._was_traffic_active)
        self.assertEqual(len(self._traffic_status_broadcasts()), 1)
        self.assertEqual(len(self.rx.packets), 1)
        self.assertEqual(len(self.hook_calls), 1)
        self.assertEqual(len(self.spy_log.jsonl_calls), 1)
        self.assertEqual(len(self.spy_log.packet_calls), 1)

    def test_ax25_with_delimiter_but_unparseable_payload_still_reaches_ui(self):
        """Spec requirement: the filter is framing-only, NOT parse-result-based."""
        meta = {"transmitter": "9k6 FSK AX.25 downlink"}
        payload = (b"\xaa" * 14) + b"\x03\xf0" + b"\x00\x01\x02\x03"
        self.rx.queue.put((self.runtime.session.generation, meta, payload))

        self._run_loop_until_drained()

        self.assertEqual(self.rx.pipeline.total_count, 1)
        self.assertEqual(self.rx.pipeline.unknown_count, 1)
        packets = self._packet_broadcasts()
        self.assertEqual(len(packets), 1)
        self.assertTrue(packets[0]["data"]["is_unknown"])

    def test_asm_golay_without_delimiter_still_flows_through(self):
        """Spec requirement: the filter is scoped to AX.25 only."""
        from mav_gss_lib.protocols.csp import CSPConfig
        from mav_gss_lib.missions.maveric.wire_format import build_cmd_raw

        csp = CSPConfig()
        raw_cmd = build_cmd_raw(6, 2, "com_ping", "")
        payload = csp.wrap(raw_cmd)

        meta = {"transmitter": "4k8 FSK AX100 ASM+Golay downlink"}
        self.rx.queue.put((self.runtime.session.generation, meta, payload))

        self._run_loop_until_drained()

        self.assertEqual(self.rx.pipeline.total_count, 1)
        self.assertEqual(len(self._packet_broadcasts()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
