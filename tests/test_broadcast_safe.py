"""Direct tests for web_runtime._broadcast.broadcast_safe."""

import asyncio
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mav_gss_lib.server._broadcast import broadcast_safe


class _RecordingWS:
    def __init__(self, *, raises: bool = False):
        self.sent: list[str] = []
        self.raises = raises

    async def send_text(self, text: str) -> None:
        if self.raises:
            raise RuntimeError("dead socket")
        self.sent.append(text)


class TestBroadcastSafeDeliversToAll(unittest.TestCase):
    def test_live_clients_all_receive_payload(self):
        clients = [_RecordingWS(), _RecordingWS(), _RecordingWS()]
        lock = threading.Lock()
        asyncio.run(broadcast_safe(clients, lock, "hello"))
        for ws in clients:
            self.assertEqual(ws.sent, ["hello"])


class TestBroadcastSafeEvictsDeadClients(unittest.TestCase):
    def test_dead_client_is_removed_from_list(self):
        live_a = _RecordingWS()
        dead = _RecordingWS(raises=True)
        live_b = _RecordingWS()
        clients = [live_a, dead, live_b]
        lock = threading.Lock()
        asyncio.run(broadcast_safe(clients, lock, "hello"))
        self.assertNotIn(dead, clients)
        self.assertIn(live_a, clients)
        self.assertIn(live_b, clients)

    def test_dead_client_does_not_break_delivery_to_others(self):
        live_a = _RecordingWS()
        dead = _RecordingWS(raises=True)
        live_b = _RecordingWS()
        clients = [live_a, dead, live_b]
        lock = threading.Lock()
        asyncio.run(broadcast_safe(clients, lock, "payload-x"))
        self.assertEqual(live_a.sent, ["payload-x"])
        self.assertEqual(live_b.sent, ["payload-x"])


class TestBroadcastSafeHandlesEmptyList(unittest.TestCase):
    def test_no_clients_is_a_noop(self):
        clients: list = []
        lock = threading.Lock()
        asyncio.run(broadcast_safe(clients, lock, "hello"))
        self.assertEqual(clients, [])


class TestBroadcastSafeSnapshotsBeforeIterating(unittest.TestCase):
    def test_mutation_during_iteration_does_not_raise(self):
        """Concurrent connect/disconnect must not RuntimeError during broadcast."""
        live_a = _RecordingWS()
        live_b = _RecordingWS()
        clients = [live_a, live_b]
        lock = threading.Lock()

        class _MutatingWS:
            def __init__(self):
                self.sent = []

            async def send_text(self, text):
                # Mutate the underlying list mid-iteration.
                clients.append(_RecordingWS())
                self.sent.append(text)

        mutator = _MutatingWS()
        clients.insert(1, mutator)
        asyncio.run(broadcast_safe(clients, lock, "m"))
        # live_a and mutator should have sent; no exception raised.
        self.assertEqual(live_a.sent, ["m"])
        self.assertEqual(mutator.sent, ["m"])


if __name__ == "__main__":
    unittest.main()
