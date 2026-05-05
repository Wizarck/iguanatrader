"""FastAPI app factory — slice 4 ``auth-jwt-cookie`` minimal pre-pattern.

Slice 5 (``api-foundation-rfc7807``) layers RFC 7807 exception handlers
+ dynamic-discovery via :func:`pkgutil.iter_modules` + OpenAPI typegen
on top of this factory; slice 4 ships the smallest possible factory
that:

1. Configures structlog so every log line is JSON (test fixtures + dev
   smoke get the same shape — no per-environment branching).
2. Attaches the slowapi :class:`Limiter` to ``app.state.limiter`` and
   registers the 429 RFC 7807 handler.
3. Installs :class:`BufferLoginEmailMiddleware` so the limiter's
   compound ``(ip, email)`` key works (per design D5).
4. Manually registers the auth router. Slice 5 will refactor this to
   discover routers via ``pkgutil`` over :mod:`iguanatrader.api.routes`.

This module is also the entrypoint for the dev/smoke uvicorn runner via
:mod:`iguanatrader.api.__main__`.
"""

from __future__ import annotations

import logging
import sys

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from iguanatrader.api.limiting import BufferLoginEmailMiddleware, limiter
from iguanatrader.api.routes.auth import router as auth_router


def _configure_structlog() -> None:
    """Configure structlog for JSON output to stdout.

    Idempotent — calling twice is a no-op (structlog tracks the config
    state internally). Slice O1 will replace this with a richer config
    (e.g., per-level filtering, dev pretty-printer, OTLP forwarding).
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    """RFC 7807 + ``Retry-After`` for slowapi 429.

    slowapi raises :class:`RateLimitExceeded` with an attached limit
    description; we surface ``retry_after`` from the limiter's view of
    the window (slowapi exposes this on the exception when available).
    The structlog event ``auth.login.rate_limited`` matches the spec
    scenario "6th attempt within 60s".
    """
    log = structlog.get_logger("iguanatrader.api.app")
    log.info("auth.login.rate_limited")

    # slowapi's RateLimitExceeded carries the limit description on .detail.
    detail_text = (
        getattr(exc, "detail", None) or "Too many login attempts. Try again shortly."
    )

    # Conservative Retry-After: the smallest window slowapi enforces on
    # the login route is 60s ("5/minute"). We surface 60 unconditionally
    # rather than racing the limiter for a precise remainder; the client
    # is expected to ticker-down its own banner.
    retry_after = 60

    body = {
        "type": "urn:iguanatrader:error:rate-limit",
        "title": "Too Many Requests",
        "status": 429,
        "detail": str(detail_text),
        "retry_after": retry_after,
    }
    return JSONResponse(
        status_code=429,
        content=body,
        media_type="application/problem+json",
        headers={"Retry-After": str(retry_after)},
    )


def create_app() -> FastAPI:
    """Build and return the FastAPI app.

    Tests construct the app via this factory (one app per test module
    is fine — the slowapi in-memory store is process-local and
    isolated across pytest workers via :mod:`pytest-xdist`'s default
    process boundaries; for in-test resets see the integration test
    fixture in ``test_auth_flow.py``).
    """
    _configure_structlog()

    app = FastAPI(
        title="iguanatrader API",
        version="slice-4",
        docs_url="/docs",
        redoc_url=None,
    )

    # Body-buffering middleware MUST run before the slowapi route
    # decorator pulls the key — install it first.
    app.add_middleware(BufferLoginEmailMiddleware)

    # slowapi wiring (per design D5).
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

    # Manual router registration — slice 5 replaces with dynamic
    # discovery via pkgutil.iter_modules over iguanatrader.api.routes.
    app.include_router(auth_router, prefix="/api/v1")

    return app


__all__ = [
    "create_app",
]
