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

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from iguanatrader.api.errors import register_error_handlers
from iguanatrader.api.limiting import BufferLoginEmailMiddleware, limiter
from iguanatrader.api.middleware import MustChangePasswordMiddleware
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


@asynccontextmanager
async def _production_adapter_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan — bootstraps production adapters per env.

    Slice deployment-foundation §3.D.2: when ``IGUANATRADER_ENV`` is
    paper/live/production AND the production scrape deps are installed,
    rebind the ladder's Tier-2 entry to Playwright. The fake stub
    remains for dev/test envs.

    Slice ``llm-observability-and-signals``: also bootstraps the
    Langfuse SaaS client when ``LANGFUSE_PUBLIC_KEY`` +
    ``LANGFUSE_SECRET_KEY`` are set. Runs unconditionally on ALL envs
    (not gated on paper/live/production) because dev environments
    benefit from LLM trace visibility too; missing creds short-circuit
    to a no-op (the Langfuse wrapper logs the disabled-state event).

    Idempotent + degradation-tolerant: a missing playwright dep logs a
    warning and lets the API boot anyway (Tier-1 webfetch still works).
    Teardown closes the playwright browser on shutdown (no-op if never
    bootstrapped) AND flushes the Langfuse queue.
    """
    log = structlog.get_logger("iguanatrader.api.app")
    env = (os.environ.get("IGUANATRADER_ENV") or "").strip().lower()

    # Wire the SQLAlchemy global listeners — tenant_id auto-stamp on
    # INSERT + append-only UPDATE/DELETE guard. The
    # ``register_global_listeners`` docstring explicitly names the
    # FastAPI lifespan as the boot site; this call was missing before
    # the 2026-05-17 NVDA refresh incident, which surfaced as
    # ``NOT NULL constraint failed: research_briefs.tenant_id`` because
    # the listener never fired. Idempotent — safe to call once per
    # worker boot.
    from iguanatrader.persistence import register_global_listeners

    register_global_listeners()

    # Langfuse bootstrap — runs on every env (no-op when creds absent).
    try:
        from iguanatrader.contexts.observability.langfuse_client import init_langfuse

        init_langfuse(env or "dev")
    except Exception as exc:  # pragma: no cover — defensive
        log.warning(
            "api.lifespan.langfuse_bootstrap_failed",
            env=env,
            error=str(exc),
            error_type=type(exc).__name__,
        )

    if env in {"paper", "live", "production"}:
        try:
            from iguanatrader.contexts.research.scraping.tier2_playwright import (
                bootstrap_production_tier2,
            )

            bootstrap_production_tier2()
            log.info("api.lifespan.tier2_playwright_bootstrapped", env=env)
        except Exception as exc:
            log.warning(
                "api.lifespan.tier2_playwright_bootstrap_failed",
                env=env,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    yield

    # Flush Langfuse queue before the worker exits so in-flight spans
    # actually reach the SaaS endpoint.
    try:
        from iguanatrader.contexts.observability.langfuse_client import (
            shutdown_langfuse,
        )

        shutdown_langfuse()
    except Exception as exc:  # pragma: no cover — defensive
        log.warning(
            "api.lifespan.langfuse_shutdown_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )

    if env in {"paper", "live", "production"}:
        try:
            from iguanatrader.contexts.research.scraping.tier2_playwright import (
                shutdown_playwright,
            )

            await shutdown_playwright()
        except Exception as exc:
            log.warning(
                "api.lifespan.tier2_playwright_shutdown_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )


#: #18: env vars deployers use to set the worker/process count. Any of
#: these > 1 means the process-local state (slowapi login limiter, budget
#: WARN_80 dedup cache, LLM throttle, the #12 per-tenant budget lock) is
#: duplicated per worker, so every limit is silently multiplied by the
#: worker count — a money cap or a brute-force login cap that does not
#: actually hold.
_WORKER_COUNT_ENV_VARS = ("WEB_CONCURRENCY", "GUNICORN_WORKERS", "UVICORN_WORKERS")
_ALLOW_MULTIWORKER_ENV = "IGUANATRADER_ALLOW_MULTIWORKER"


def _assert_single_worker_or_opted_in() -> None:
    """#18: refuse to boot with >1 worker while limits live in memory.

    The escape hatch ``IGUANATRADER_ALLOW_MULTIWORKER=true`` is for when a
    shared store (Redis/DB) backs those limits — set it only once the
    process-local state has actually been externalised. Default-deny so a
    casual ``--workers 4`` cannot quietly defeat the caps.
    """
    if os.environ.get(_ALLOW_MULTIWORKER_ENV, "").strip().lower() in ("1", "true", "yes", "on"):
        return
    for var in _WORKER_COUNT_ENV_VARS:
        raw = os.environ.get(var)
        if not raw:
            continue
        try:
            count = int(raw.strip())
        except ValueError:
            continue
        if count > 1:
            raise RuntimeError(
                f"{var}={count} requests multiple workers, but rate-limit / budget / "
                "throttle state is process-local — running >1 worker multiplies every "
                f"limit by the worker count. Set {_ALLOW_MULTIWORKER_ENV}=true ONLY after "
                "moving that state to a shared store (Redis/DB), or run a single worker."
            )


def create_app() -> FastAPI:
    """Build and return the FastAPI app.

    Tests construct the app via this factory (one app per test module
    is fine — the slowapi in-memory store is process-local and
    isolated across pytest workers via :mod:`pytest-xdist`'s default
    process boundaries; for in-test resets see the integration test
    fixtures under ``apps/api/tests/integration/conftest.py``).
    """
    _assert_single_worker_or_opted_in()
    _configure_structlog()

    app = FastAPI(
        title="iguanatrader API",
        version="slice-5",
        docs_url="/docs",
        redoc_url=None,
        lifespan=_production_adapter_lifespan,
    )

    # Body-buffering middleware MUST run before the slowapi route
    # decorator pulls the key — install it first.
    app.add_middleware(BufferLoginEmailMiddleware)

    # Slice ``auth-change-password``: gate every non-allow-listed API
    # route for users with ``users.must_change_password=TRUE``. The
    # middleware decodes the session cookie + runs a one-column DB
    # lookup; allow-listed paths (login, logout, me, change-password,
    # healthz, docs) bypass entirely. Failure modes (no cookie, invalid
    # JWT, deleted user, DB blip) fail open so downstream auth still
    # gets to render its 401 — the gate ONLY adds a 403 on the
    # explicit ``must_change_password=TRUE`` branch.
    app.add_middleware(MustChangePasswordMiddleware)

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

    # Liveness probe for compose / docker healthchecks. Stays outside
    # the /api/v1 prefix so orchestrators don't have to know the API
    # versioning scheme.
    @app.get("/healthz", include_in_schema=False)
    async def _healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


__all__ = [
    "create_app",
]
