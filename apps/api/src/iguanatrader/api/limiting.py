"""slowapi rate-limiter wiring — single shared :class:`Limiter` instance.

Per design D5: the login limit is keyed on the compound ``(ip, email)``
tuple. slowapi's ``key_func`` is synchronous and runs BEFORE the
FastAPI route handler parses the body, so the email is not yet
available to the limiter at decoration time.

The fix is :class:`BufferLoginEmailMiddleware`, an ASGI middleware that
intercepts ``POST /api/v1/auth/login`` requests, reads the body, parses
the email out of either JSON or form-urlencoded shapes, stashes it on
``request.state.login_email``, and **re-injects** the body so the route
can still consume it normally. The ``key_func`` then reads the email
from ``request.state``.

This separate module exists to avoid an import cycle between
:mod:`iguanatrader.api.app` and :mod:`iguanatrader.api.routes.auth`
(routes need the ``limiter`` at decoration time; ``app.py`` registers
the middleware + 429 handler).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs

import structlog
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = structlog.get_logger("iguanatrader.api.limiting")

LOGIN_PATH: str = "/api/v1/auth/login"


def _login_key_func(request: Request) -> str:
    """Compose the rate-limit key from ``(ip, email)``.

    Reads the email from ``request.state.login_email`` (set by
    :class:`BufferLoginEmailMiddleware`); falls back to empty string if
    the middleware did not run (which would happen for non-login
    requests routed through this limiter — the empty-email key is then
    effectively per-IP, which is fine because no other route uses this
    limiter today).
    """
    ip = get_remote_address(request)
    email = getattr(request.state, "login_email", "") or ""
    return f"{ip}:{email}"


limiter: Limiter = Limiter(key_func=_login_key_func)
"""The single shared :class:`Limiter` instance.

slice 4 attaches one decoration: ``@limiter.limit("5/minute")`` on the
login route. Future slices may add their own decorations against this
same limiter; the in-memory store is shared across the process.
"""


class BufferLoginEmailMiddleware:
    """ASGI middleware: read+buffer login body, expose ``request.state.login_email``.

    Only acts on ``POST /api/v1/auth/login``. For every other request
    the middleware passes through with no work.

    Body buffering: ASGI streams the body via ``receive()``; once a
    coroutine has consumed it, a second ``receive()`` returns
    ``http.disconnect``. We read the full body upfront, parse the email,
    then replace ``receive`` with a closure that yields the buffered
    body once and then ``http.disconnect`` exactly as the original
    transport would have.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        if scope.get("method") != "POST" or scope.get("path") != LOGIN_PATH:
            await self.app(scope, receive, send)
            return

        body = await self._read_body(receive)
        email = self._extract_email(scope, body)

        # Stash on scope.state-equivalent so request.state.login_email reads
        # it inside FastAPI handlers + the slowapi key_func.
        state = scope.setdefault("state", {})
        state["login_email"] = email

        # Replace receive() so the downstream app sees the buffered body
        # exactly once and then http.disconnect. Use a flag closure
        # because ASGI semantics expect "more_body=False" on the final
        # chunk and an http.disconnect after that.
        body_yielded = False

        async def replay_receive() -> Message:
            nonlocal body_yielded
            if not body_yielded:
                body_yielded = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _read_body(receive: Receive) -> bytes:
        chunks: list[bytes] = []
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                break
            chunks.append(message.get("body", b""))
            more_body = message.get("more_body", False)
        return b"".join(chunks)

    @staticmethod
    def _extract_email(scope: Scope, body: bytes) -> str:
        """Best-effort email extraction from JSON or form-urlencoded body.

        Returns an empty string on any parse failure — the caller falls
        back to per-IP keying which is still useful (just less granular).
        """
        if not body:
            return ""
        content_type = ""
        for header_name, header_val in scope.get("headers", []):
            if header_name == b"content-type":
                content_type = header_val.decode("latin-1", errors="replace").lower()
                break

        try:
            if "application/json" in content_type:
                payload: Any = json.loads(body)
                if isinstance(payload, dict):
                    email = payload.get("email", "")
                    return email if isinstance(email, str) else ""
                return ""
            if "application/x-www-form-urlencoded" in content_type:
                form = parse_qs(body.decode("utf-8", errors="replace"))
                values = form.get("email", [])
                return values[0] if values else ""
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ""
        return ""


__all__ = [
    "LOGIN_PATH",
    "BufferLoginEmailMiddleware",
    "limiter",
]
