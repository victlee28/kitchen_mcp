"""The MCP server over HTTP for other machines of the LAN (``python server.py --http``): every request must carry the key
``KITCHEN_MCP_TOKEN`` as ``Authorization: Bearer <key>``; the server does not start without one.

A pure ASGI gate in front of the MCP app (streamable HTTP at ``/mcp``). The key is compared in constant time and never logged."""
from __future__ import annotations

import hmac
import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
App = Callable[[Scope, Receive, Send], Awaitable[None]]

MIN_TOKEN = 16      # characters: a shorter key is refused (python -c "import secrets; print(secrets.token_urlsafe(32))" makes one)


class TokenError(ValueError):
    """No key, or a key too short to protect the server."""


def check_token(token: str | None) -> str:
    if not token:
        raise TokenError("KITCHEN_MCP_TOKEN is not set: the HTTP MCP server needs a key (see README, 'MCP qua mạng LAN')")
    if len(token) < MIN_TOKEN:
        raise TokenError(f"KITCHEN_MCP_TOKEN is too short: at least {MIN_TOKEN} characters")
    return token


class BearerGate:
    """Lets through only HTTP requests whose ``Authorization`` header is ``Bearer <token>``; others get 401. Lifespan and other
    scope types pass untouched."""

    def __init__(self, app: App, token: str) -> None:
        self.app = app
        self._expected = f"Bearer {check_token(token)}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") in ("http", "websocket"):
            headers: list[tuple[bytes, bytes]] = list(scope.get("headers") or [])
            got = next((v for k, v in headers if k.lower() == b"authorization"), b"")
            if not hmac.compare_digest(got, self._expected):
                body = json.dumps({"error": "unauthorized", "message": "missing or wrong bearer key"}).encode()
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b'Bearer realm="kitchen-design"'),
                                        (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def serve(mcp_app: App, token: str, host: str, port: int) -> None:
    """Run ``mcp_app`` (``MCPServer.streamable_http_app(...)``) behind the gate with uvicorn."""
    import uvicorn
    uvicorn.run(BearerGate(mcp_app, token), host=host, port=port, log_level="info")
