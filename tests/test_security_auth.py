"""Tests for web_runtime.security auth helpers."""

import asyncio
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mav_gss_lib.server.security import (
    authorize_websocket,
    origin_allowed,
    require_api_token,
)
from mav_gss_lib.server.state import PORT


class _FakeRuntime:
    def __init__(self, token: str = "correct-token"):
        self.session_token = token


class _FakeApp:
    """FastAPI app stand-in whose `.state.runtime` is the real WebRuntime.

    Important: use SimpleNamespace (not MagicMock) so `hasattr(state, "runtime")`
    is True ONLY when we actually set it. A MagicMock would answer True for any
    attribute, which defeats `get_runtime()`'s holder-vs-app disambiguation.
    """

    def __init__(self, runtime):
        self.state = types.SimpleNamespace(runtime=runtime)


class _FakeWebSocket:
    def __init__(self, *, token: str, origin: str | None, host: str | None, runtime):
        self.query_params = {"token": token}
        self.headers = {}
        if origin is not None:
            self.headers["origin"] = origin
        if host is not None:
            self.headers["host"] = host
        self.app = _FakeApp(runtime)
        # Per-WS scope state — must NOT carry a `.runtime` attribute so
        # get_runtime() falls through to self.app.state.runtime.
        self.state = types.SimpleNamespace()
        self.closed_with: int | None = None

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


class _FakeRequest:
    def __init__(self, *, token: str, runtime):
        self.headers = {"x-gss-token": token}
        self.app = _FakeApp(runtime)
        # Same rationale as _FakeWebSocket: keep request.state free of
        # `runtime` so get_runtime() reads app.state.runtime.
        self.state = types.SimpleNamespace()


class TestOriginAllowed(unittest.TestCase):
    def test_no_origin_is_allowed(self):
        self.assertTrue(origin_allowed(None, "anything"))

    def test_matching_localhost_origin_allowed(self):
        self.assertTrue(origin_allowed(f"http://127.0.0.1:{PORT}", f"127.0.0.1:{PORT}"))

    def test_matching_host_origin_allowed(self):
        self.assertTrue(origin_allowed("http://myhost", "myhost"))

    def test_mismatched_origin_rejected(self):
        self.assertFalse(origin_allowed("http://evil.example", f"127.0.0.1:{PORT}"))

    def test_origin_without_host_rejected(self):
        self.assertFalse(origin_allowed("http://anywhere", None))


class TestRequireApiToken(unittest.TestCase):
    def test_correct_token_returns_none(self):
        runtime = _FakeRuntime(token="secret")
        req = _FakeRequest(token="secret", runtime=runtime)
        self.assertIsNone(require_api_token(req))

    def test_wrong_token_returns_403(self):
        runtime = _FakeRuntime(token="secret")
        req = _FakeRequest(token="wrong", runtime=runtime)
        resp = require_api_token(req)
        self.assertIsNotNone(resp)
        self.assertEqual(resp.status_code, 403)

    def test_missing_token_returns_403(self):
        runtime = _FakeRuntime(token="secret")
        req = _FakeRequest(token="", runtime=runtime)
        resp = require_api_token(req)
        self.assertIsNotNone(resp)
        self.assertEqual(resp.status_code, 403)


class TestAuthorizeWebSocket(unittest.TestCase):
    def test_correct_token_and_origin_accepts(self):
        runtime = _FakeRuntime(token="secret")
        ws = _FakeWebSocket(
            token="secret",
            origin=f"http://127.0.0.1:{PORT}",
            host=f"127.0.0.1:{PORT}",
            runtime=runtime,
        )
        result = asyncio.run(authorize_websocket(ws))
        self.assertTrue(result)
        self.assertIsNone(ws.closed_with)

    def test_wrong_token_closes_1008(self):
        runtime = _FakeRuntime(token="secret")
        ws = _FakeWebSocket(
            token="wrong",
            origin=f"http://127.0.0.1:{PORT}",
            host=f"127.0.0.1:{PORT}",
            runtime=runtime,
        )
        result = asyncio.run(authorize_websocket(ws))
        self.assertFalse(result)
        self.assertEqual(ws.closed_with, 1008)

    def test_missing_token_closes_1008(self):
        runtime = _FakeRuntime(token="secret")
        ws = _FakeWebSocket(
            token="",
            origin=f"http://127.0.0.1:{PORT}",
            host=f"127.0.0.1:{PORT}",
            runtime=runtime,
        )
        result = asyncio.run(authorize_websocket(ws))
        self.assertFalse(result)
        self.assertEqual(ws.closed_with, 1008)

    def test_bad_origin_closes_1008(self):
        runtime = _FakeRuntime(token="secret")
        ws = _FakeWebSocket(
            token="secret",
            origin="http://attacker.example",
            host=f"127.0.0.1:{PORT}",
            runtime=runtime,
        )
        result = asyncio.run(authorize_websocket(ws))
        self.assertFalse(result)
        self.assertEqual(ws.closed_with, 1008)

    def test_no_origin_header_is_accepted(self):
        """origin_allowed returns True when no Origin header is present."""
        runtime = _FakeRuntime(token="secret")
        ws = _FakeWebSocket(
            token="secret",
            origin=None,
            host=f"127.0.0.1:{PORT}",
            runtime=runtime,
        )
        result = asyncio.run(authorize_websocket(ws))
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
