r"""Auth routes — ``POST /login``, ``POST /logout``, ``GET /me``.

The router is mounted at ``/api/v1/auth`` via the dynamic-discovery
loop in :mod:`iguanatrader.api.routes` (slice 5
``api-foundation-rfc7807``). Slice 4 used a manual
``app.include_router(...)`` call; slice 5 picks the router up
automatically because this module exports a top-level
``router: APIRouter``.

Design references (from slice 4 ``openspec/changes/auth-jwt-cookie/design.md``):

* D2 — cookie config (HttpOnly + Secure + SameSite=Strict + 7d Max-Age,
  cookie name ``iguana_session``).
* D3 — login_at claim drives the 7-day cookie ceiling that NOT extends
  on rotation.
* D4 — Argon2id verify against a fixed dummy hash on the
  email-not-found branch keeps timing constant (defeats user enumeration).
* D5 — slowapi 5/min keyed by ``(ip, email)`` — the actual ``key_func``
  + body-buffering middleware live in :mod:`iguanatrader.api.app`.
* D6 — zero-tenant bootstrap returns 503 RFC 7807. Slice 5 design D9
  canonicalises the type URI to ``urn:iguanatrader:error:not-bootstrapped``
  via the new :class:`BootstrapNotReadyError` (was URL-form in slice 4).
* D9 — ``redirect_to`` allow-list at the SvelteKit form-action level;
  FastAPI also applies a defensive check (single leading ``/``, no ``//``,
  no ``://``, no ``\``) — anything that fails falls back to ``/``.

Hard rules per AGENTS.md §4:

* ``application/problem+json`` for every error response (now via the
  global :class:`IguanaError` handler — routes ``raise``, the handler renders).
* structlog event names: ``auth.<entity>.<action>``.
* Email NEVER logged in plaintext — :func:`hash_email_for_log` digests it.
"""

from __future__ import annotations

import time

import structlog
import structlog.contextvars
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
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
    bootstrap_load_user_by_email,
    get_current_user,
    get_db,
    is_secure_cookie,
)
from iguanatrader.api.dtos.auth import LoginRequest, LoginResponse, MeResponse
from iguanatrader.api.limiting import limiter
from iguanatrader.persistence import User
from iguanatrader.shared.errors import AuthError, BootstrapNotReadyError

log = structlog.get_logger("iguanatrader.api.routes.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

#: Fixed dummy Argon2id hash used when the supplied email has no matching
#: ``User`` row. The verify against this hash keeps the response time
#: constant regardless of whether the email exists, defeating user
#: enumeration via timing side-channel (per slice 4 design D4).
#:
#: Computed once at import time (not at every request) — ``hash_password``
#: with a randomly-generated plaintext yields a real Argon2id encoded
#: string with the project's configured params. The plaintext is
#: discarded; only the hash is retained.
_DUMMY_PASSWORD_HASH: str = hash_password("not-a-real-user-password-placeholder")


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

    1. Zero-tenant guard → ``raise BootstrapNotReadyError`` → 503.
    2. Lookup user by email (with ``tenant_id_var`` UNSET — bootstrap path
       — slice-3 listener applies no filter).
    3. Verify password (or against dummy hash if user absent — timing parity).
    4. On any failure: ``raise AuthError`` → 401 uniform Problem Detail,
       emit ``auth.login.failure``.
    5. On success: encode JWT, set cookie, return ``LoginResponse``,
       emit ``auth.login.success``.
    """
    email_hash = hash_email_for_log(body.email)

    # 1. Zero-tenant bootstrap guard. Raw SQL via text() — gotcha #23
    #    documents the bypass; the slice-3 listener raises on every ORM
    #    SELECT when tenant_id_var is unset (even queries against
    #    non-tenant-scoped tables like ``tenants``). Slice-O1 follow-up
    #    will fix the listener to skip filter injection for queries that
    #    only touch non-scoped tables; until then, raw SQL is the contract.
    tenant_count_row = (await session.execute(text("SELECT COUNT(*) AS n FROM tenants"))).first()
    tenant_count = int(tenant_count_row.n) if tenant_count_row is not None else 0
    if tenant_count == 0:
        log.info("auth.login.bootstrap_required", email_hash=email_hash)
        raise BootstrapNotReadyError(
            detail=(
                "Run `iguanatrader admin bootstrap-tenant <slug>` to create "
                "the first tenant + admin user."
            ),
        )

    # 2. User lookup. tenant_id_var is UNSET here on purpose (we don't yet
    #    know which tenant the email belongs to — chicken-and-egg). The
    #    raw-SQL helper bypasses the slice-3 listener (gotcha #23); JWT
    #    trust boundary keeps cross-tenant exposure scoped to the
    #    submitted email's owner only.
    user = await bootstrap_load_user_by_email(session, body.email)

    # 3 + 4. Verify (or dummy-verify), uniform 401 on any failure.
    plaintext = body.password.get_secret_value()
    if user is None:
        verify_password(plaintext, _DUMMY_PASSWORD_HASH)  # constant-time burn
        log.info(
            "auth.login.failure",
            email_hash=email_hash,
            reason="email_not_found",
        )
        raise AuthError(detail="Invalid email or password.")

    if not verify_password(plaintext, user.password_hash):
        log.info(
            "auth.login.failure",
            email_hash=email_hash,
            reason="wrong_password",
            user_id=str(user.id),
        )
        raise AuthError(detail="Invalid email or password.")

    # 5. Success — encode JWT + set cookie + return LoginResponse.
    now = int(time.time())
    token = encode_jwt(
        {
            "sub": str(user.id),
            "tenant_id": str(user.tenant_id),
            "role": user.role,
            "login_at": now,
        },
        exp_seconds=JWT_DEFAULT_EXP_SECONDS,
    )

    safe_redirect = _validate_redirect_to(redirect_to)
    if redirect_to and safe_redirect != redirect_to:
        log.warning(
            "auth.login.redirect_rejected",
            user_id=str(user.id),
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
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
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
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        role=user.role_enum,
        created_at=user.created_at,
    )


__all__ = [
    "router",
]
