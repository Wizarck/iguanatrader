"""FastAPI dependencies — DB session, current user, role gating.

Owned by slice 4 (``auth-jwt-cookie``). Slice 5 (``api-foundation-rfc7807``)
may relocate :func:`get_db` into a shared dependency module once additional
route families need it; for now the engine + session factory are wired
lazily via ``functools.lru_cache`` so the first request constructs them
and every subsequent request reuses them.

Design references:

* design D7 — :func:`get_current_user` sets :data:`tenant_id_var` BEFORE
  any tenant-scoped query runs in the request lifecycle. The user lookup
  itself runs with :data:`tenant_id_var` UNSET (bootstrap path); the
  slice-3 tenant listener treats absent ContextVar as "no filter".
* design D3 — JWT auto-rotation when ``exp`` is within
  :data:`JWT_ROTATION_THRESHOLD_SECONDS` of expiring. The cookie's
  effective ``Max-Age`` budget is computed from the ``login_at`` claim,
  NOT extended on rotation (7-day ceiling is hard).
* design D10 — :func:`requires_role` factory pattern.

structlog correlation: rather than introducing additional Python
``ContextVar`` instances for ``user_id``/``correlation_id``,
:func:`get_current_user` calls
:func:`structlog.contextvars.bind_contextvars` so subsequent log records
automatically carry those fields. Only :data:`tenant_id_var` needs to be
a Python contextvar because the SQLAlchemy event listener reads it.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from functools import lru_cache

import structlog
import structlog.contextvars
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from iguanatrader.api.auth import (
    COOKIE_CEILING_SECONDS,
    JWT_DEFAULT_EXP_SECONDS,
    Role,
    decode_jwt,
    encode_jwt,
    should_rotate,
)
from iguanatrader.persistence import (
    AsyncEngine,
    User,
    engine_factory,
    session_factory,
)
from iguanatrader.shared.contextvars import tenant_id_var

log = structlog.get_logger("iguanatrader.api.deps")

COOKIE_NAME: str = "iguana_session"
"""Session cookie name (per design D2)."""

_DEFAULT_DB_URL: str = "sqlite+aiosqlite:///./data/iguanatrader.db"
_DB_URL_ENV: str = "IGUANA_DATABASE_URL"


@lru_cache(maxsize=1)
def _get_engine() -> AsyncEngine:
    return engine_factory(os.getenv(_DB_URL_ENV) or _DEFAULT_DB_URL)


@lru_cache(maxsize=1)
def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    return session_factory(_get_engine())


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield an :class:`AsyncSession` per request.

    Slice 5 may replace this with a session middleware that also binds
    the session to :data:`iguanatrader.shared.contextvars.session_var`
    so domain repositories outside the api package can pick it up.
    """
    sessionmaker = _get_session_factory()
    async with sessionmaker() as session:
        yield session


def _is_secure_cookie() -> bool:
    """Return ``True`` iff the cookie should carry the ``Secure`` flag.

    Default ``True``. Dev-only override
    ``IGUANATRADER_DEV_INSECURE_COOKIE=1`` permits HTTP cookies on
    localhost — gotcha #25 documents the trade-off.
    """
    return os.getenv("IGUANATRADER_DEV_INSECURE_COOKIE") != "1"


async def get_current_user(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the session cookie.

    Order of operations (per design D7):

    1. Read ``iguana_session`` cookie. Absent → 401.
    2. Decode JWT (HS256). Invalid / expired / tampered → 401.
    3. Check 7-day cookie ceiling via ``login_at`` claim. Exceeded → 401.
    4. Load :class:`User` from DB with :data:`tenant_id_var` UNSET
       (bootstrap path — slice-3 listener applies no filter).
    5. Set :data:`tenant_id_var` so subsequent tenant-scoped queries
       are filtered by the slice-3 listener.
    6. Bind structlog contextvars (``tenant_id``, ``user_id``,
       ``correlation_id``) for the rest of the request.
    7. If the JWT ``exp`` is within :data:`JWT_ROTATION_THRESHOLD_SECONDS`
       of expiring, encode a fresh JWT and attach ``Set-Cookie`` to the
       response. The cookie ``Max-Age`` is computed from the original
       ``login_at`` (the 7-day ceiling is NOT extended).
    8. Return the :class:`User`.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    claims = decode_jwt(token)
    if claims is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    now = int(time.time())
    login_at_raw = claims.get("login_at")
    if not isinstance(login_at_raw, int) or login_at_raw <= 0:
        log.warning("auth.session.invalid_login_at_claim")
        raise HTTPException(status_code=401, detail="Invalid token claims")
    if (now - login_at_raw) >= COOKIE_CEILING_SECONDS:
        log.info("auth.session.ceiling_reached", login_at=login_at_raw, now=now)
        raise HTTPException(status_code=401, detail="Session ceiling reached")

    user_id_raw = claims.get("sub")
    if not isinstance(user_id_raw, str) or not user_id_raw:
        raise HTTPException(status_code=401, detail="Invalid token claims")

    # Bootstrap path: tenant_id_var is UNSET here. Slice-3 tenant listener
    # treats absent ContextVar as "no filter", which is what we need to
    # find the user in the first place.
    user = (
        await session.execute(select(User).where(User.id == user_id_raw))
    ).scalar_one_or_none()
    if user is None:
        log.warning("auth.user.not_found", user_id=user_id_raw)
        raise HTTPException(status_code=401, detail="User not found")

    # Now set the tenant ContextVar so any subsequent query in the request
    # is tenant-isolated.
    tenant_id_var.set(uuid.UUID(user.tenant_id))

    # Bind structlog contextvars so log records automatically carry
    # tenant_id / user_id / correlation_id.
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    structlog.contextvars.bind_contextvars(
        tenant_id=user.tenant_id,
        user_id=user.id,
        correlation_id=correlation_id,
    )

    # JWT auto-rotation (design D3).
    exp_raw = claims.get("exp")
    if isinstance(exp_raw, int) and should_rotate(exp_raw, now):
        new_token = encode_jwt(
            {
                "sub": user.id,
                "tenant_id": user.tenant_id,
                "role": user.role,
                "login_at": login_at_raw,
            },
            exp_seconds=JWT_DEFAULT_EXP_SECONDS,
        )
        max_age_remaining = COOKIE_CEILING_SECONDS - (now - login_at_raw)
        response.set_cookie(
            COOKIE_NAME,
            new_token,
            max_age=max_age_remaining,
            httponly=True,
            secure=_is_secure_cookie(),
            samesite="strict",
            path="/",
        )
        log.info("auth.session.rotated", user_id=user.id)

    return user


def requires_role(*roles: Role) -> Callable[..., Awaitable[User]]:
    """FastAPI dependency factory — gate a route to one of ``roles``.

    Usage::

        @router.post("/strategies/{id}/config")
        async def update_strategy(
            id: UUID,
            body: StrategyConfig,
            user: User = Depends(requires_role(Role.tenant_user)),
        ):
            ...

    On role mismatch raises 403 with structlog event ``auth.role.mismatch``.
    The wrapped :func:`get_current_user` dependency runs first, so an
    unauthenticated caller still gets 401 (not 403).
    """

    async def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role_enum not in roles:
            log.warning(
                "auth.role.mismatch",
                user_id=user.id,
                user_role=user.role,
                required_roles=[r.value for r in roles],
            )
            raise HTTPException(status_code=403, detail="Forbidden: role mismatch")
        return user

    return _checker


__all__ = [
    "COOKIE_NAME",
    "get_current_user",
    "get_db",
    "requires_role",
]
