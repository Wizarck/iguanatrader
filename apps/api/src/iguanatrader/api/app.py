"""FastAPI app factory — slice 5 ``api-foundation-rfc7807`` shape.

Slice 4 (``auth-jwt-cookie``) shipped a minimal factory with a single
manual ``app.include_router(auth_router, prefix="/api/v1")`` call and
no global exception handler. Slice 5 layers the foundation pre-pattern
on top:

1. Configures structlog so every log line is JSON.
2. Attaches the slowapi :class:`Limiter` to ``app.state.limiter`` and
   registers the 429 RFC 7807 handler.
3. Installs :class:`BufferLoginEmailMiddleware` so the limiter's
   compound ``(ip, email)`` key works (per design D5 of slice 4).
4. Discovers and mounts every ``routes/<name>.py`` via
   :func:`iguanatrader.api.routes.register_routers` (per design D1).
5. Discovers and mounts every ``sse/<name>.py`` via
   :func:`iguanatrader.api.sse.register_sse` (per design D2).
6. Registers the global :class:`IguanaError` + ``Exception`` handlers
   via :func:`iguanatrader.api.errors.register_error_handlers`
   (per design D3).

Adding a new route family or SSE feed is a single-file change under
``routes/`` or ``sse/``; this factory does NOT need to be touched.

Entrypoint for the dev/smoke uvicorn runner: :mod:`iguanatrader.api.__main__`.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from iguanatrader.api.errors import register_error_handlers
from iguanatrader.api.limiting import BufferLoginEmailMiddleware, limiter
from iguanatrader.api.routes import register_routers
from iguanatrader.api.sse import register_sse
from iguanatrader.contexts.observability.structlog_config import (
    configure_logging,
    get_env,
)


def _configure_structlog() -> None:
    """Configure structlog via the observability bounded context.

    Added 2026-05-06 by slice O1 (``observability-cost-meter``) per
    design D6 — this is the single deliberate exception to the
    "slice O1 doesn't edit shared infra" scope clause. Justification:
    NFR-O3 requires log rotation + 7-day retention; the only sensible
    owner is the observability context. Pushing the config there +
    leaving a one-liner delegate here is the cleanest factoring; future
    enhancements (OTLP forwarding, dev TTY pretty-printer) edit
    :mod:`iguanatrader.contexts.observability.structlog_config`, never
    this file.

    Idempotent — calling twice replaces the existing config.
    """
    configure_logging(get_env())


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

    detail_text = getattr(exc, "detail", None) or "Too many login attempts. Try again shortly."

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
    fixtures under ``apps/api/tests/integration/conftest.py``).
    """
    _configure_structlog()

    app = FastAPI(
        title="iguanatrader API",
        version="slice-5",
        docs_url="/docs",
        redoc_url=None,
    )

    # Body-buffering middleware MUST run before the slowapi route
    # decorator pulls the key — install it first.
    app.add_middleware(BufferLoginEmailMiddleware)

    # slowapi wiring (per slice 4 design D5).
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

    # Slice 5: dynamic discovery + global error rendering. Order:
    # routers + SSE first (so their endpoints exist on the app),
    # then error handlers (handler registration is order-sensitive
    # per slice-5 design D10 — see register_error_handlers docstring).
    register_routers(app)
    register_sse(app)
    register_error_handlers(app)

    return app


__all__ = [
    "create_app",
]
