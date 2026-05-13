"""``must_change_password`` route gate (slice ``auth-change-password``).

When an authenticated user has ``users.must_change_password = TRUE``
(provisional credential issued by an admin or forgot-password flow),
every API route is gated behind a 403 RFC 7807 Problem until the user
rotates the password. A short allow-list lets the user actually CALL
the change-password / logout / me endpoints without tripping the gate.

Allow-list (proposal §Middleware gate):

* ``POST /api/v1/auth/change-password`` — the rotation endpoint itself.
* ``POST /api/v1/auth/logout`` — let the user escape if they want.
* ``GET /api/v1/auth/me`` — so the SvelteKit ``hooks.server.ts`` can
  still read the flag and route the user to the change-password page.
* ``POST /api/v1/auth/login`` — login is pre-auth; the gate would never
  fire here anyway but listing it makes the intent explicit.
* ``/healthz``, ``/docs``, ``/openapi.json``, ``/redoc`` — operational
  surfaces.

Implementation: ASGI middleware decodes the JWT directly (mirroring
:func:`iguanatrader.api.deps.get_current_user`'s cookie / claim logic)
and runs a raw-SQL lookup to read just the ``must_change_password``
column. Per-request overhead is one extra DB roundtrip; acceptable for
the MVP, and only fires when a cookie is present.

The :class:`PasswordChangeRequiredError` is raised so the slice-5 RFC
7807 handler chain renders the response uniformly — the middleware
never builds the JSONResponse directly.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from iguanatrader.api.auth import decode_jwt
from iguanatrader.api.deps import COOKIE_NAME
from iguanatrader.shared.errors import PasswordChangeRequiredError

log = structlog.get_logger("iguanatrader.api.middleware.must_change_password")

#: Exact-match path allow-list. Method+path tuples; both must match for
#: the gate to be skipped. Method matching uses the request's
#: ``scope["method"]`` (upper-case ASCII).
MUST_CHANGE_PASSWORD_ALLOW_LIST: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/v1/auth/change-password"),
        ("POST", "/api/v1/auth/logout"),
        ("GET", "/api/v1/auth/me"),
        ("POST", "/api/v1/auth/login"),
    }
)

#: Prefix-match allow-list. Any request whose ``path`` starts with one
#: of these strings is exempt regardless of HTTP method. Reserved for
#: operational surfaces (health, docs).
MUST_CHANGE_PASSWORD_ALLOW_PREFIXES: tuple[str, ...] = (
    "/healthz",
    "/docs",
    "/openapi.json",
    "/redoc",
)


def _is_allow_listed(method: str, path: str) -> bool:
    """Return True iff ``(method, path)`` is in the allow-list."""
    if (method, path) in MUST_CHANGE_PASSWORD_ALLOW_LIST:
        return True
    for prefix in MUST_CHANGE_PASSWORD_ALLOW_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


SessionFactoryProvider = Callable[[], async_sessionmaker[Any]]


#: Module-level override hook. When set to a callable returning an
#: :class:`async_sessionmaker`, the middleware uses THIS instead of the
#: lru-cached production factory in :mod:`iguanatrader.api.deps`. Tests
#: set this in their conftest because Starlette middleware can NOT be
#: intercepted via FastAPI ``dependency_overrides``.
_session_factory_override: SessionFactoryProvider | None = None


def set_session_factory_override(provider: SessionFactoryProvider | None) -> None:
    """Test-only — override the DB session factory used by the gate.

    Pass ``None`` to clear the override. Mirrors the
    ``FastAPI.dependency_overrides`` pattern but for Starlette
    middleware (which is constructed once at app boot, before
    ``dependency_overrides`` can intercept anything).
    """
    global _session_factory_override
    _session_factory_override = provider


class MustChangePasswordMiddleware(BaseHTTPMiddleware):
    """Block routes for users with ``must_change_password=TRUE``.

    The ``session_factory_provider`` callable is injected at construction
    time so tests can override the DB session source without touching
    the FastAPI dependency-overrides surface (which only intercepts
    FastAPI ``Depends``, not Starlette middleware). The default reads
    the cached engine via :func:`iguanatrader.api.deps._get_session_factory`.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        session_factory_provider: SessionFactoryProvider | None = None,
    ) -> None:
        super().__init__(app)
        self._session_factory_provider = session_factory_provider

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        method = request.scope.get("method", "").upper()
        path = request.url.path

        if _is_allow_listed(method, path):
            return await call_next(request)

        token = request.cookies.get(COOKIE_NAME)
        if not token:
            # No session — let downstream auth handle the 401.
            return await call_next(request)

        claims = decode_jwt(token)
        if claims is None:
            return await call_next(request)

        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            return await call_next(request)
        try:
            user_uuid = uuid.UUID(sub)
        except ValueError:
            return await call_next(request)

        # Resolve the session factory lazily. Tests inject a
        # ``session_factory_provider`` returning a real
        # :class:`async_sessionmaker`; production reads the lru-cached
        # factory from :mod:`iguanatrader.api.deps`.
        sessionmaker = self._resolve_session_factory()
        if sessionmaker is None:
            # No DB wired (eg. a unit test using TestClient without the
            # full app fixture). Fail open — the gate can't be enforced
            # without a DB; let downstream auth do its thing.
            return await call_next(request)

        try:
            async with sessionmaker() as session:
                row = (
                    await session.execute(
                        text("SELECT must_change_password FROM users " "WHERE id = :uid LIMIT 1"),
                        {"uid": user_uuid.hex},
                    )
                ).first()
        except Exception:
            # Defensive: a DB blip should not silently bypass the gate
            # but it also should not 500 every request. Log + fail open
            # so observability surfaces it.
            log.warning(
                "auth.must_change_password.db_lookup_failed",
                exc_info=True,
                path=path,
                method=method,
            )
            return await call_next(request)

        if row is None:
            # User was deleted between login and now; let downstream auth
            # render its 401 — not our gate's concern.
            return await call_next(request)

        must_change = bool(row.must_change_password)
        if not must_change:
            return await call_next(request)

        log.info(
            "auth.password.change_required",
            user_id=str(user_uuid),
            path=path,
            method=method,
        )
        exc = PasswordChangeRequiredError(
            detail=(
                "Password change is required before any further API access. "
                "POST /api/v1/auth/change-password to rotate it."
            ),
        )
        return JSONResponse(
            status_code=exc.status,
            content=exc.to_problem_dict(),
            media_type="application/problem+json",
        )

    def _resolve_session_factory(
        self,
    ) -> async_sessionmaker[Any] | None:
        """Return an :class:`async_sessionmaker` or ``None`` if unavailable.

        Tests inject ``session_factory_provider`` directly. Production
        falls back to :func:`iguanatrader.api.deps._get_session_factory`.
        Guard against the lru-cache mis-resolving in environments where
        :envvar:`IGUANA_DATABASE_URL` is unset and the default sqlite
        file path is read-only (eg. CI containers without the data
        volume) — the cache raises, we catch + return None.
        """
        provider = self._session_factory_provider or _session_factory_override
        if provider is not None:
            try:
                return provider()
            except Exception:
                log.warning(
                    "auth.must_change_password.session_factory_provider_failed",
                    exc_info=True,
                )
                return None
        try:
            from iguanatrader.api.deps import (  # local import — avoid cycle
                _get_session_factory,
            )

            return _get_session_factory()
        except Exception:
            return None


__all__ = [
    "MUST_CHANGE_PASSWORD_ALLOW_LIST",
    "MUST_CHANGE_PASSWORD_ALLOW_PREFIXES",
    "MustChangePasswordMiddleware",
    "SessionFactoryProvider",
    "set_session_factory_override",
]
