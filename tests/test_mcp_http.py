"""The MCP server over HTTP for the LAN (``server.py --http``, ``mcp_http``): no key, no answer."""
from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mcp_http  # noqa: E402

TOKEN = "k" * 24


def call(app, headers):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": headers}
    asyncio.run(app(scope, receive, send))
    return sent


class TestGate(unittest.TestCase):
    def setUp(self):
        self.reached = []

        async def inner(scope, receive, send):
            self.reached.append(scope["type"])
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
        self.gate = mcp_http.BearerGate(inner, TOKEN)

    def test_no_key_or_a_wrong_key_gets_401_and_never_reaches_the_server(self):
        for headers in ([], [(b"authorization", b"Bearer wrong")], [(b"authorization", TOKEN.encode())]):
            with self.subTest(headers=headers):
                sent = call(self.gate, headers)
                self.assertEqual(sent[0]["status"], 401)
        self.assertEqual(self.reached, [])

    def test_the_right_key_goes_through(self):
        sent = call(self.gate, [(b"Authorization", f"Bearer {TOKEN}".encode())])
        self.assertEqual(sent[0]["status"], 200)
        self.assertEqual(self.reached, ["http"])

    def test_lifespan_passes(self):
        async def receive():
            return {"type": "lifespan.startup"}

        async def send(_):
            return None
        asyncio.run(self.gate({"type": "lifespan"}, receive, send))
        self.assertEqual(self.reached, ["lifespan"])

    def test_a_missing_or_short_key_refuses_to_start(self):
        for bad in (None, "", "short"):
            with self.subTest(bad=bad), self.assertRaises(mcp_http.TokenError):
                mcp_http.check_token(bad)


class TestServer(unittest.TestCase):
    """The real MCP app behind the gate, on a free port of 127.0.0.1."""

    def test_initialize_needs_the_key(self):
        import uvicorn
        import server
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        srv = uvicorn.Server(uvicorn.Config(mcp_http.BearerGate(server.http_app(), TOKEN), host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=srv.run, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if srv.started:
                    break
                time.sleep(0.05)
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}).encode()

            def post(headers):
                req = urllib.request.Request(f"http://127.0.0.1:{port}/mcp", data=body, method="POST", headers={
                    "content-type": "application/json", "accept": "application/json, text/event-stream", **headers})
                try:
                    with urllib.request.urlopen(req, timeout=10) as r:
                        return r.status, r.read().decode()
                except urllib.error.HTTPError as e:
                    return e.code, e.read().decode()
            self.assertEqual(post({})[0], 401)
            self.assertEqual(post({"authorization": "Bearer nope-nope-nope-nope"})[0], 401)
            status, text = post({"authorization": f"Bearer {TOKEN}"})
            self.assertEqual(status, 200, text)
            self.assertIn("kitchen-design", text)
        finally:
            srv.should_exit = True
            thread.join(timeout=10)


if __name__ == "__main__":
    unittest.main()
