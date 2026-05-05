"""Auth routes — ``POST /login``, ``POST /logout``, ``GET /me``.

The router is mounted at ``/api/v1/auth`` via the manual
``app.include_router(...)`` call in :mod:`iguanatrader.api.app` (slice 5
``api-foundation-rfc7807`` will refactor that to dynamic discovery).

Design references (from ``openspec/changes/auth-jwt-cookie/design.md``):

* D2 — cookie config (HttpOnly + Secure + SameSite=Strict + 7d Max-Age,
  cookie name ``iguana_session``).
* D3 — login_at claim drives the 7-day cookie ceiling that NOT extends
  on rotation.
* D4 — Argon2id verify against a fixed dummy hash on the
  email-not-found branch keeps timing constant (defeats user enumeration).
* D5 — slowapi 5/min keyed by ``(ip, email)`` — the actual ``key_func``
  + body-buffering middleware live in :mod:`iguanatrader.api.app`.
* D6 — zero-tenant bootstrap returns 503 with RFC 7807 Problem Detail.
* D9 — ``redirect_to`` allow-list at the SvelteKit form-action level;
  FastAPI also applies a defensive check (single leading ``/``, no ``//``,
  no ``://``, no ``\``) — anything that fails falls back to ``/``.

Hard rules per AGENTS.md §4:

* ``application/problem+json`` for every error response.
* structlog event names: ``auth.<entity>.<action>``.
* Email NEVER logged in plaintext — :func:`hash_email_for_log` digests it.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import structlog
import structlog.contextvars
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.auth import (
    COOKIE_CEILING_SECONDS,
    JWT_DEFAULT_EXP_SECONDS,
    encode_jwt,
    hash_email_for_log,
    hash_password,
    verify_password,
)
from iguanatrader.api.deps import (
    COOKIE_NAME,
    is_secure_cookie,
    get_current_user,
    get_db,
)
from iguanatrader.api.dtos.auth import LoginRequest, LoginResponse, MeResponse
from iguanatrader.api.limiting import limiter
from iguanatrader.persistence import Tenant, User

log = structlog.get_logger("iguanatrader.api.routes.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

#: Fixed dummy Argon2id hash used when the supplied email has no matching
#: ``User`` row. The verify against this hash keeps the response time
#: constant regardless of whether the email exists, defeating user
#: enumeration via timing side-channel (per design D4).
#:
#: Computed once at import time (not at every request) — ``hash_password``
#: with a randomly-generated plaintext yields a real Argon2id encoded
#: string with the project's configured params. The plaintext is
#: discarded; only the hash is retained.
_DUMMY_PASSWORD_HASH: str = hash_password("not-a-real-user-password-placeholder")


def _problem_response(
    status: int,
    type_uri: str,
    title: str,
    detail: str,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    """Return an ``application/problem+json`` response with the given fields."""
    body: dict[str, Any] = {
        "type": type_uri,
        "title": title,
        "status": status,
        "detail": detail,
    }
    if extra:
        body.update(extra)
    return JSONResponse(
        status_code=status,
        content=body,
        media_type="application/problem+json",
    )


def _validate_redirect_to(value: str | None) -> str:
    """Defense-in-depth allow-list (canonical check is in SvelteKit form action — D9).

    Acceptable values: a single leading ``/`` followed by anything that
    is NOT another ``/``, NOT contains ``://``, NOT contains a
    backslash. Anything else falls back to ``/``.
    """
    if not value:
        return "/"
    if not value.startswith("/"):
        return "/"
    if value.startswith("//"):
        return "/"
    if "://" in value:
        return "/"
    if "\\" in value:
        return "/"
    return value


@router.post("/login", response_model=None)
@limiter.limit("5/minute")
async def login(
    request: Request,
    body: LoginRequest,
    redirect_to: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Authenticate credentials, set the session cookie, return redirect target.

    Flow (per spec ``web-authentication`` Requirement 1):

    1. Zero-tenant guard → 503.
    2. Lookup user by email (with ``tenant_id_var`` UNSET — bootstrap path
       — slice-3 listener applies no filter).
    3. Verify password (or against dummy hash if user absent — timing parity).
    4. On any failure: 401 uniform Problem Detail, emit ``auth.login.failure``.
    5. On success: encode JWT, set cookie, return ``LoginResponse``,
       emit ``auth.login.success``.
    """
    email_hash = hash_email_for_log(body.email)

    # 1. Zero-tenant bootstrap guard (D6).
    tenant_count_raw = await session.execute(select(func.count()).select_from(Tenant))
    tenant_count = int(tenant_count_raw.scalar_one())
    if tenant_count == 0:
        log.info("auth.login.bootstrap_required", email_hash=email_hash)
        return _problem_response(
            status=503,
            type_uri="https://iguanatrader.local/problems/not-bootstrapped",
            title="iguanatrader has no tenants yet",
            detail=(
                "Run `iguanatrader admin bootstrap-tenant <slug>` to create "
                "the first tenant + admin user."
            ),
        )

    # 2. User lookup. tenant_id_var is UNSET here on purpose — slice-3
    #    listener treats absent ContextVar as "no filter", which is what
    #    we need to find the user across tenants by their unique email.
    user = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()

    # 3 + 4. Verify (or dummy-verify), uniform 401 on any failure.
    plaintext = body.password.get_secret_value()
    if user is None:
        verify_password(plaintext, _DUMMY_PASSWORD_HASH)  # constant-time burn
        log.info(
            "auth.login.failure",
            email_hash=email_hash,
            reason="email_not_found",
        )
        return _problem_response(
            status=401,
            type_uri="urn:iguanatrader:error:auth",
            title="Authentication Required",
            detail="Invalid email or password.",
        )

    if not verify_password(plaintext, user.password_hash):
        log.info(
            "auth.login.failure",
            email_hash=email_hash,
            reason="wrong_password",
            user_id=user.id,
        )
        return _problem_response(
            status=401,
            type_uri="urn:iguanatrader:error:auth",
            title="Authentication Required",
            detail="Invalid email or password.",
        )

    # 5. Success — encode JWT + set cookie + return LoginResponse.
    now = int(time.time())
    token = encode_jwt(
        {
            "sub": user.id,
            "tenant_id": user.tenant_id,
            "role": user.role,
            "login_at": now,
        },
        exp_seconds=JWT_DEFAULT_EXP_SECONDS,
    )

    safe_redirect = _validate_redirect_to(redirect_to)
    if redirect_to and safe_redirect != redirect_to:
        log.warning(
            "auth.login.redirect_rejected",
            user_id=user.id,
            rejected_value=redirect_to,
        )

    response = JSONResponse(
        status_code=200,
        content=LoginResponse(redirect_to=safe_redirect).model_dump(),
    )
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_CEILING_SECONDS,
        httponly=True,
        secure=is_secure_cookie(),
        samesite="strict",
        path="/",
    )

    structlog.contextvars.bind_contextvars(
        tenant_id=user.tenant_id,
        user_id=user.id,
    )
    log.info("auth.login.success", email_hash=email_hash)
    return response


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, bool]:
    """Clear the session cookie. Idempotent.

    Per spec scenario "Authenticated logout" + "Unauthenticated logout":
    always returns 200; emits ``auth.session.logout`` only if the request
    carried a cookie (best-effort attribution — the JWT may be invalid
    or expired, but we still clear it on the response).
    """
    had_cookie = COOKIE_NAME in request.cookies
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        secure=is_secure_cookie(),
        httponly=True,
        samesite="strict",
    )
    if had_cookie:
        log.info("auth.session.logout")
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(get_current_user)) -> MeResponse:
    """Return the authenticated user's safe payload.

    NEVER includes ``password_hash`` (Pydantic :class:`MeResponse` only
    declares the safe fields; SQLAlchemy ``User`` instance is consumed
    field-by-field, not serialised wholesale).
    """
    return MeResponse(
        user_id=UUID(user.id),
        tenant_id=UUID(user.tenant_id),
        email=user.email,
        role=user.role_enum,
        created_at=user.created_at,
    )


__all__ = [
    "router",
]
