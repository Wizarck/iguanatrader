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
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Literal
from uuid import UUID

import structlog
import structlog.contextvars
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import text
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

#: Slice ``auth-password-aging-warning``. Default thresholds (in days)
#: for the soft "rotate your password" banner emitted by
#: :func:`_classify_password_aging`. ``ageing`` (heads-up / 60d default)
#: maps to the dashboard warning banner; ``stale`` (action-requested /
#: 90d default) maps to the danger banner. Operators can shift the
#: boundaries via :envvar:`IGUANATRADER_AUTH_PASSWORD_AGEING_DAYS` and
#: :envvar:`IGUANATRADER_AUTH_PASSWORD_STALE_DAYS`. The 90d ceiling is
#: the NIST SP 800-63B baseline; 60d gives the user a 30-day window to
#: act before the danger banner fires.
_DEFAULT_PASSWORD_AGEING_DAYS: int = 60
_DEFAULT_PASSWORD_STALE_DAYS: int = 90
_PASSWORD_AGEING_DAYS_ENV: str = "IGUANATRADER_AUTH_PASSWORD_AGEING_DAYS"
_PASSWORD_STALE_DAYS_ENV: str = "IGUANATRADER_AUTH_PASSWORD_STALE_DAYS"

#: Type alias for the password-aging classifier output. ``fresh`` means
#: no banner; ``ageing`` and ``stale`` map to the two banner variants
#: rendered by :mod:`apps/web/src/lib/components/PasswordAgeingBanner.svelte`.
PasswordAgingState = Literal["fresh", "ageing", "stale"]


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


async def bootstrap_load_user_by_id(session: AsyncSession, user_id: UUID) -> User | None:
    """Bootstrap-path User lookup that bypasses the slice-3 tenant listener.

    Per design D7 + ``docs/gotchas.md`` #23: :func:`get_current_user` and
    :func:`iguanatrader.api.routes.auth.login` need to load a User BEFORE
    they know which tenant to set on :data:`tenant_id_var`. The slice-3
    ORM listener raises :class:`TenantContextMissingError` for any ORM
    SELECT when :data:`tenant_id_var` is unset (even queries that touch
    only non-scoped tables — slice-3 design did not implement the
    "absent ContextVar = no filter" branch promised in slice-4 design).

    Raw SQL via :func:`sqlalchemy.text` bypasses the listener entirely
    (gotcha #23). The query is parameterised by ``id`` only; cross-tenant
    exposure is bounded by the JWT trust boundary (the JWT subject is
    asserted by HS256 signature, an attacker can't forge a sub for
    another tenant).

    Returns a transient (not session-attached) :class:`User` instance
    suitable for read-only use in the request lifecycle. Slice O1 will
    fix the slice-3 listener to skip filter injection for queries that
    only touch non-scoped tables, after which this helper can collapse
    back to ORM ``select(User).where(...)``.
    """
    sql = text(
        "SELECT id, tenant_id, email, password_hash, role, created_at, updated_at, "
        "must_change_password, password_changed_at, "
        "telegram_chat_id, whatsapp_phone "
        "FROM users WHERE id = :uid LIMIT 1"
    )
    # SQLAlchemy 2.x ``Uuid`` column on SQLite stores as 32-char hex
    # without hyphens (no native UUID type). Pass ``user_id.hex`` so the
    # comparison hits the storage representation; the ORM-mapped User
    # lookup wouldn't have this issue but raw SQL skips that conversion.
    result = await session.execute(sql, {"uid": user_id.hex})
    row = result.first()
    if row is None:
        return None
    return _row_to_user(row)


async def bootstrap_load_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Bootstrap-path counterpart of :func:`bootstrap_load_user_by_id`.

    Used by ``POST /auth/login`` before any tenant context is established.
    See :func:`bootstrap_load_user_by_id` docstring for rationale.
    """
    sql = text(
        "SELECT id, tenant_id, email, password_hash, role, created_at, updated_at, "
        "must_change_password, password_changed_at, "
        "telegram_chat_id, whatsapp_phone "
        "FROM users WHERE email = :email LIMIT 1"
    )
    result = await session.execute(sql, {"email": email})
    row = result.first()
    if row is None:
        return None
    return _row_to_user(row)


def _row_to_user(row: Any) -> User:
    """Construct a transient :class:`User` from a raw SQL row.

    The returned instance is NOT attached to a session (no identity-map
    membership, no lazy loading); it's a plain DTO for read paths. The
    ``role_enum`` property still works because it's a pure-Python
    property.
    """
    raw_id = row.id
    raw_tid = row.tenant_id
    # ``must_change_password`` was added by slice ``auth-change-password``
    # (migration 0013). Pre-migration tests may construct rows without it;
    # default to False for forward compatibility. SQLite stores BOOLEAN as
    # INTEGER 0/1 — coerce via ``bool()`` so the ORM attribute is a real
    # Python bool regardless of driver shape.
    must_change_raw = getattr(row, "must_change_password", 0)
    password_changed_at_raw = getattr(row, "password_changed_at", None)
    # Slice ``auth-forgot-password-flow`` (migration 0014). Pre-migration
    # rows lack these columns; default to None for forward compatibility.
    telegram_chat_id_raw = getattr(row, "telegram_chat_id", None)
    whatsapp_phone_raw = getattr(row, "whatsapp_phone", None)
    return User(
        id=raw_id if isinstance(raw_id, UUID) else UUID(raw_id),
        tenant_id=raw_tid if isinstance(raw_tid, UUID) else UUID(raw_tid),
        email=row.email,
        password_hash=row.password_hash,
        role=row.role,
        created_at=row.created_at,
        updated_at=row.updated_at,
        must_change_password=bool(must_change_raw),
        password_changed_at=password_changed_at_raw,
        telegram_chat_id=telegram_chat_id_raw,
        whatsapp_phone=whatsapp_phone_raw,
    )


def is_secure_cookie() -> bool:
    """Return ``True`` iff the cookie should carry the ``Secure`` flag.

    Default ``True``. Dev-only override
    ``IGUANATRADER_DEV_INSECURE_COOKIE=1`` permits HTTP cookies on
    localhost — gotcha #25 documents the trade-off.

    Slice-O1 carry-forward (D9 item b): when the dev override is set
    AND ``IGUANATRADER_ENV=production``, raises :class:`ConfigError`
    via :func:`iguanatrader.config.settings.enforce_dev_insecure_cookie_prod_guard`.
    The guard is enforced on every cookie write, so any login attempt
    on a misconfigured production deployment fails loudly with an
    RFC 7807 500 response (instead of silently shipping a cookie
    without the ``Secure`` flag — a security hole).
    """
    from iguanatrader.config.settings import (  # local import: lifecycle isolation
        enforce_dev_insecure_cookie_prod_guard,
    )

    enforce_dev_insecure_cookie_prod_guard()
    return os.getenv("IGUANATRADER_DEV_INSECURE_COOKIE") != "1"


def _read_env_threshold(name: str, default: int) -> int:
    """Read a positive integer threshold from the environment.

    Used by :func:`_classify_password_aging` for the two configurable
    boundaries (``IGUANATRADER_AUTH_PASSWORD_AGEING_DAYS`` /
    ``IGUANATRADER_AUTH_PASSWORD_STALE_DAYS``). Non-numeric / non-positive
    overrides fall back to ``default`` rather than raising — the banner
    is a soft UX hint, not a security gate, so a misconfigured env
    should not 500 the ``/me`` endpoint on every request.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        parsed = int(raw)
    except ValueError:
        log.warning(
            "auth.password_aging.invalid_threshold_env",
            env_var=name,
            raw_value=raw,
            fallback=default,
        )
        return default
    if parsed <= 0:
        log.warning(
            "auth.password_aging.non_positive_threshold_env",
            env_var=name,
            parsed=parsed,
            fallback=default,
        )
        return default
    return parsed


def _classify_password_aging(
    password_changed_at: datetime | None,
    *,
    now: datetime | None = None,
) -> tuple[int | None, PasswordAgingState]:
    """Classify a user's password age into a banner state.

    Slice ``auth-password-aging-warning``. The banner is rendered by the
    ``(app)/+layout.svelte`` shell when this returns anything other than
    ``"fresh"`` — see :class:`PasswordAgeingBanner` for the markup.

    Contract:

    * ``password_changed_at is None`` (legacy users planted before
      ``migrations/0013_user_password_metadata``) → ``(None, "fresh")``.
      Grandfather rule: we have no signal so we do not nag.
    * ``age_days < ageing_threshold`` → ``"fresh"``.
    * ``ageing_threshold <= age_days < stale_threshold`` → ``"ageing"``.
    * ``age_days >= stale_threshold`` → ``"stale"``.

    Thresholds are read from the env on every call (cheap; one
    ``os.getenv`` + ``int()``); :func:`_read_env_threshold` falls back to
    :data:`_DEFAULT_PASSWORD_AGEING_DAYS` / :data:`_DEFAULT_PASSWORD_STALE_DAYS`
    on missing or invalid values.

    Datetime handling: ``password_changed_at`` is stored as
    ``TIMESTAMP WITH TIME ZONE`` on PostgreSQL but SQLite (the MVP
    backend) returns a naive ``datetime`` even when the column was
    declared with ``DateTime(timezone=True)``. We treat naive timestamps
    as UTC (the column writers — :func:`change_password`,
    :func:`forgot_password` — use ``CURRENT_TIMESTAMP`` which is UTC on
    SQLite) so the arithmetic stays consistent across backends.
    """
    if password_changed_at is None:
        return (None, "fresh")

    reference_now = now if now is not None else datetime.now(tz=UTC)
    # Normalise naive datetimes (SQLite + Pydantic round-trip) to UTC.
    if reference_now.tzinfo is None:
        reference_now = reference_now.replace(tzinfo=UTC)
    # SQLite TEXT column may return password_changed_at as ISO string when
    # the row was inserted via raw `text()` SQL (tests). SQLAlchemy ORM
    # path returns a real datetime. Coerce defensively.
    pwd_changed: datetime
    if isinstance(password_changed_at, str):
        pwd_changed = datetime.fromisoformat(password_changed_at)
    else:
        pwd_changed = password_changed_at
    if pwd_changed.tzinfo is None:
        pwd_changed = pwd_changed.replace(tzinfo=UTC)

    delta = reference_now - pwd_changed
    # ``delta.days`` floors negative or sub-day diffs to 0; future
    # timestamps (clock skew) classify as ``fresh`` with age=0.
    age_days = max(int(delta.total_seconds() // 86400), 0)

    ageing_threshold = _read_env_threshold(_PASSWORD_AGEING_DAYS_ENV, _DEFAULT_PASSWORD_AGEING_DAYS)
    stale_threshold = _read_env_threshold(_PASSWORD_STALE_DAYS_ENV, _DEFAULT_PASSWORD_STALE_DAYS)

    if age_days >= stale_threshold:
        return (age_days, "stale")
    if age_days >= ageing_threshold:
        return (age_days, "ageing")
    return (age_days, "fresh")


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
    try:
        user_id_uuid = uuid.UUID(user_id_raw)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token claims") from None

    # Bootstrap path: tenant_id_var is UNSET here. Use the raw-SQL helper
    # (gotcha #23) to bypass the slice-3 listener — see helper docstring
    # for rationale + slice-O1 follow-up that collapses this back to ORM.
    user = await bootstrap_load_user_by_id(session, user_id_uuid)
    if user is None:
        log.warning("auth.user.not_found", user_id=user_id_raw)
        raise HTTPException(status_code=401, detail="User not found")

    # Now set the tenant ContextVar so any subsequent query in the request
    # is tenant-isolated. user.tenant_id is already a UUID (Mapped[UUID]).
    tenant_id_var.set(user.tenant_id)

    # Slice ``auth-password-aging-warning``: compute the soft-rotate
    # banner state and stash it on ``request.state`` so :func:`me_endpoint`
    # can surface it via :class:`MeResponse` without re-querying the DB.
    # Using ``request.state`` (Starlette typed as ``State`` / runtime-dict)
    # instead of mutating the transient :class:`User` keeps the
    # SQLAlchemy mapped model untouched (no schema drift, no mypy noise
    # from ad-hoc attribute injection).
    password_age_days, password_aging_state = _classify_password_aging(user.password_changed_at)
    request.state.password_age_days = password_age_days
    request.state.password_aging_state = password_aging_state

    # Bind structlog contextvars so log records automatically carry
    # tenant_id / user_id / correlation_id (rendered as strings for JSON).
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    structlog.contextvars.bind_contextvars(
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
        correlation_id=correlation_id,
    )

    # JWT auto-rotation (design D3).
    exp_raw = claims.get("exp")
    if isinstance(exp_raw, int) and should_rotate(exp_raw, now):
        new_token = encode_jwt(
            {
                "sub": str(user.id),
                "tenant_id": str(user.tenant_id),
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
            secure=is_secure_cookie(),
            samesite="strict",
            path="/",
        )
        log.info("auth.session.rotated", user_id=str(user.id))

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
    "PasswordAgingState",
    "_classify_password_aging",
    "get_current_user",
    "get_db",
    "is_secure_cookie",
    "requires_role",
]
