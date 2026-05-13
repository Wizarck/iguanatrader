"""Unit tests for the slice ``auth-change-password`` gate middleware.

Three cases (proposal §Tests):

1. Flag OFF on a gated path → middleware passes through (no 403).
2. Flag ON but path is in the allow-list → middleware passes through.
3. Flag ON on a gated path → middleware returns 403 RFC 7807.

The tests build a tiny ad-hoc Starlette app with one stub route +
:class:`MustChangePasswordMiddleware`, then drive it via
:class:`httpx.AsyncClient` + :class:`httpx.ASGITransport`. The DB is
faked via the ``session_factory_provider`` injection — no real
SQLAlchemy engine, no real Alembic, no real persistence package.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient
from iguanatrader.api.auth import encode_jwt
from iguanatrader.api.deps import COOKIE_NAME
from iguanatrader.api.middleware import (
    MUST_CHANGE_PASSWORD_ALLOW_LIST,
    MustChangePasswordMiddleware,
)
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_JWT_SECRET", "x" * 64)


class _FakeRow:
    def __init__(self, must_change: bool) -> None:
        self.must_change_password = 1 if must_change else 0


class _FakeResult:
    def __init__(self, row: _FakeRow | None) -> None:
        self._row = row

    def first(self) -> _FakeRow | None:
        return self._row


class _FakeSession:
    def __init__(self, must_change: bool) -> None:
        self._must_change = must_change

    async def execute(self, _statement: Any, _params: Any) -> _FakeResult:
        return _FakeResult(_FakeRow(self._must_change))

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None


class _FakeSessionMaker:
    def __init__(self, must_change: bool) -> None:
        self._must_change = must_change

    def __call__(self) -> _FakeSession:
        return _FakeSession(self._must_change)


def _build_app(*, must_change: bool) -> Starlette:
    """Build a minimal Starlette app gated by the middleware under test."""

    async def _gated_endpoint(_request: Any) -> JSONResponse:
        return JSONResponse({"ok": True})

    async def _logout_endpoint(_request: Any) -> JSONResponse:
        return JSONResponse({"ok": True})

    routes = [
        Route("/api/v1/portfolio/summary", _gated_endpoint, methods=["GET"]),
        Route("/api/v1/auth/logout", _logout_endpoint, methods=["POST"]),
    ]
    app = Starlette(routes=routes)
    # Cast the fake sessionmaker as the production type — the middleware
    # only calls ``provider()`` then ``maker()`` then ``execute()``, so
    # duck-typing is what's actually exercised at runtime. mypy --strict
    # needs the cast to accept the duck shape.
    provider = cast(
        "Any",
        lambda: _FakeSessionMaker(must_change=must_change),
    )
    app.add_middleware(
        MustChangePasswordMiddleware,
        session_factory_provider=provider,
    )
    return app


def _make_token() -> str:
    return encode_jwt(
        {
            "sub": str(uuid.uuid4()),
            "tenant_id": str(uuid.uuid4()),
            "role": "tenant_user",
            "login_at": int(time.time()),
        }
    )


# --------------------------------------------------------------------------- #
# 1 — flag OFF: gate passes through
# --------------------------------------------------------------------------- #


async def test_flag_off_passes_through() -> None:
    app = _build_app(must_change=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as c:
        c.cookies.set(COOKIE_NAME, _make_token())
        resp = await c.get("/api/v1/portfolio/summary")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


# --------------------------------------------------------------------------- #
# 2 — flag ON + allow-list path: gate passes through
# --------------------------------------------------------------------------- #


async def test_flag_on_allow_listed_path_passes_through() -> None:
    app = _build_app(must_change=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as c:
        c.cookies.set(COOKIE_NAME, _make_token())
        # /api/v1/auth/logout IS in the allow-list.
        assert ("POST", "/api/v1/auth/logout") in MUST_CHANGE_PASSWORD_ALLOW_LIST
        resp = await c.post("/api/v1/auth/logout")
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# 3 — flag ON + gated path: 403 RFC 7807
# --------------------------------------------------------------------------- #


async def test_flag_on_gated_path_returns_403() -> None:
    app = _build_app(must_change=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as c:
        c.cookies.set(COOKIE_NAME, _make_token())
        resp = await c.get("/api/v1/portfolio/summary")
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 403
    assert body["type"] == "urn:iguanatrader:error:password-change-required"
    assert "POST /api/v1/auth/change-password" in body["detail"]
