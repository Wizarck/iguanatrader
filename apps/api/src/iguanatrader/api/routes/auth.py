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
    PasswordAgingState,
    bootstrap_load_user_by_email,
    get_current_user,
    get_db,
    is_secure_cookie,
)
from iguanatrader.api.dtos.auth import (
    MIN_PASSWORD_LENGTH,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    LoginResponse,
    MeResponse,
)
from iguanatrader.api.limiting import limiter
from iguanatrader.api.temp_password import generate_temp_password
from iguanatrader.contexts.approval.dispatcher import (
    build_user_channel_dispatcher_from_env,
)
from iguanatrader.persistence import User
from iguanatrader.shared.channel_dispatch import (
    LogOnlyMessageDispatcher,
    MessageDispatcher,
    MultiChannelMessageDispatcher,
    OutboundMessage,
)
from iguanatrader.shared.channel_dispatch.recipients import (
    resolve_recipients_for_user,
)
from iguanatrader.shared.channel_dispatch.templates import render_email_template
from iguanatrader.shared.errors import (
    AuthError,
    AuthMismatchError,
    BootstrapNotReadyError,
    ValidationError,
)

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
async def me(
    request: Request,
    user: User = Depends(get_current_user),
) -> MeResponse:
    """Return the authenticated user's safe payload.

    NEVER includes ``password_hash`` (Pydantic :class:`MeResponse` only
    declares the safe fields; SQLAlchemy ``User`` instance is consumed
    field-by-field, not serialised wholesale).

    Slice ``auth-password-aging-warning``: ``password_age_days`` and
    ``password_aging_state`` are stashed on ``request.state`` by
    :func:`get_current_user` (which already loaded the user and computed
    the classifier). We read them back here instead of re-running the
    classifier so the contract stays single-sourced. Falls back to
    ``(None, "fresh")`` if the attributes were not set — should not
    happen in practice (the dependency always sets them when it runs)
    but defensive defaults keep the response shape stable.
    """
    password_age_days: int | None = getattr(request.state, "password_age_days", None)
    raw_state = getattr(request.state, "password_aging_state", "fresh")
    # Narrow the runtime value to the Literal the DTO expects. The
    # dependency only ever sets one of the three known states; anything
    # else falls back to ``"fresh"`` (defensive: keeps the banner off if
    # ``request.state`` is mutated by an unrelated middleware). The
    # explicit ``if`` ladder lets mypy infer the Literal narrowing —
    # ``in (tuple-of-literals)`` is NOT a guard the type system honours.
    password_aging_state: PasswordAgingState
    if raw_state == "ageing":
        password_aging_state = "ageing"
    elif raw_state == "stale":
        password_aging_state = "stale"
    else:
        password_aging_state = "fresh"
    return MeResponse(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        role=user.role_enum,
        created_at=user.created_at,
        must_change_password=bool(user.must_change_password),
        password_age_days=password_age_days,
        password_aging_state=password_aging_state,
    )


def _validate_new_password(plaintext: str, *, old_plaintext: str) -> None:
    """Enforce the slice ``auth-change-password`` plaintext invariants.

    Raises :class:`ValidationError` (400 + ``urn:iguanatrader:error:
    validation``) on:

    * length < :data:`MIN_PASSWORD_LENGTH` (12)
    * no digit AND no non-alphanumeric character (i.e. all-alpha is
      rejected)
    * equals the old plaintext

    The validator is a private route helper rather than a Pydantic
    validator because the "new != old" rule needs both plaintexts at
    once — Pydantic's field validators only see one field at a time
    (the model validator would work but introduces a less-obvious code
    path; a route-level helper is simpler).
    """
    if len(plaintext) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            detail=(f"New password must be at least {MIN_PASSWORD_LENGTH} characters."),
        )
    has_digit = any(c.isdigit() for c in plaintext)
    has_symbol = any(not c.isalnum() for c in plaintext)
    if not (has_digit or has_symbol):
        raise ValidationError(
            detail="New password must include at least one digit or symbol.",
        )
    if plaintext == old_plaintext:
        raise ValidationError(
            detail="New password must be different from the current password.",
        )


@router.post("/change-password", status_code=204)
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Rotate the authenticated user's password.

    Flow (per slice ``auth-change-password`` proposal §Backend):

    1. Verify ``old_password`` against the stored Argon2id hash. Mismatch
       → 401 ``urn:iguanatrader:error:auth-mismatch``.
    2. Validate ``new_password`` (length ≥ 12, ≥1 digit or symbol,
       NOT equal to ``old_password``). Failure → 400
       ``urn:iguanatrader:error:validation``.
    3. Hash ``new_password`` with Argon2id, ``UPDATE users SET
       password_hash=:hash, must_change_password=0,
       password_changed_at=NOW(), updated_at=NOW() WHERE id=:uid``.
    4. Return 204 No Content.

    Tenant isolation: :func:`get_current_user` already set
    :data:`tenant_id_var` so the slice-3 tenant listener filters the
    UPDATE to the caller's tenant. The ``WHERE id = :uid`` guard makes
    cross-user writes impossible even if the listener were bypassed.

    Email is hashed for logging (``hash_email_for_log``) per AGENTS.md
    §4 — never log raw PII.
    """
    email_hash = hash_email_for_log(user.email)
    old_plaintext = body.old_password.get_secret_value()
    new_plaintext = body.new_password.get_secret_value()

    if not verify_password(old_plaintext, user.password_hash):
        log.info(
            "auth.password.change_failed",
            email_hash=email_hash,
            user_id=str(user.id),
            reason="old_password_mismatch",
        )
        raise AuthMismatchError(detail="Current password is incorrect.")

    _validate_new_password(new_plaintext, old_plaintext=old_plaintext)

    new_hash = hash_password(new_plaintext)

    # Raw SQL UPDATE — bypasses the ORM identity map so we don't need to
    # re-fetch the User row (the dependency yielded a transient instance
    # via the bootstrap-path helper anyway — see :func:`get_current_user`
    # for the gotcha #23 explanation). ``func.now()`` is server-side so
    # the timestamp comes from the DB clock, not the app process.
    await session.execute(
        text(
            "UPDATE users SET password_hash = :hash, "
            "must_change_password = 0, "
            "password_changed_at = CURRENT_TIMESTAMP, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE id = :uid"
        ),
        {"hash": new_hash, "uid": user.id.hex},
    )
    await session.commit()

    log.info(
        "auth.password.changed",
        email_hash=email_hash,
        user_id=str(user.id),
    )

    return Response(status_code=204)


#: Generic forgot-password response message (ES). Same wording whether
#: the email matched a user or not — anti-enumeration. Centralised so
#: copy edits land in one place + tests can import the exact string.
FORGOT_PASSWORD_GENERIC_MESSAGE: str = (
    "Si la dirección está registrada, recibirás instrucciones para recuperar la cuenta."
)

#: Test-only override hook for the channel dispatcher used by the
#: forgot-password endpoint. Production calls
#: :func:`build_user_channel_dispatcher_from_env` once per request (it
#: is cheap — no I/O at construction time). Tests inject a fake
#: :class:`MessageDispatcher` to assert the fan-out without running real
#: SMTP / Telegram / WhatsApp transports.
_forgot_password_dispatcher_override: MessageDispatcher | None = None


def set_forgot_password_dispatcher_override(dispatcher: MessageDispatcher | None) -> None:
    """Test-only — override the channel dispatcher used by ``/forgot-password``.

    Pass ``None`` to clear the override. Mirrors the
    :func:`iguanatrader.api.middleware.set_session_factory_override`
    pattern used by the slice ``auth-change-password`` middleware tests.
    """
    global _forgot_password_dispatcher_override
    _forgot_password_dispatcher_override = dispatcher


def _resolve_forgot_password_dispatcher() -> MessageDispatcher:
    """Return the per-request channel dispatcher (override-aware)."""
    if _forgot_password_dispatcher_override is not None:
        return _forgot_password_dispatcher_override
    return build_user_channel_dispatcher_from_env()


def _dispatcher_can_deliver(dispatcher: MessageDispatcher) -> bool:
    """Return ``True`` iff ``dispatcher`` can actually transmit the temp password.

    Guards slice ``auth-forgot-password-guardrail``. The parent slice
    ``auth-forgot-password-flow`` (PR #135) shipped a footgun: when
    ``IGUANATRADER_CHANNEL_DISPATCHER`` is unset (the default MVP profile)
    OR resolves to a tree whose every leaf is
    :class:`LogOnlyMessageDispatcher`,
    :func:`build_user_channel_dispatcher_from_env` returns a dispatcher
    that emits ``channel_dispatch.log_only.would_send`` (envelope metadata
    only — NO body). The temp password is therefore never readable by
    anyone, yet the route had already rotated ``users.password_hash`` →
    silent account lockout.

    Detection rules:

    * a bare :class:`LogOnlyMessageDispatcher` → ``False``.
    * a :class:`MultiChannelMessageDispatcher` whose every inner
      dispatcher is (transitively) log-only → ``False``. ``ANY`` inner
      non-log-only entry → ``True`` (mixed deliveries are acceptable —
      at least one real channel will carry the credential).
    * any other shape (concrete adapter, test double, custom impl) →
      ``True``. The contract is opt-in: only the in-tree LogOnly path
      is treated as "cannot deliver".
    """
    if isinstance(dispatcher, LogOnlyMessageDispatcher):
        return False
    if isinstance(dispatcher, MultiChannelMessageDispatcher):
        inner = dispatcher._dispatchers.values()
        if not inner:
            return False
        return any(_dispatcher_can_deliver(d) for d in inner)
    return True


def _render_forgot_password_message(*, temp_password: str, correlation_id: str) -> OutboundMessage:
    """Compose the :class:`OutboundMessage` carrying the temp credential.

    Subject is the bare phrase ``Recuperación de contraseña``; the
    :class:`EmailSMTPDispatcher` adds the ``[iguanatrader]`` prefix on
    its own (re-prefixing would yield ``[iguanatrader] [iguanatrader]
    ...``). The HTML body uses :func:`render_email_template` for the
    branded layout; ``message.body`` carries the plain-text alternative
    so Telegram / WhatsApp / text-only mail clients see a readable
    payload.
    """
    headline = "Tu contraseña temporal"
    body_html = (
        "<p>Has solicitado recuperar tu contraseña de iguanatrader. "
        "Usa esta contraseña temporal para entrar y, en el primer login, "
        "se te pedirá que la cambies por una nueva.</p>"
        f'<p class="creds"><strong>{temp_password}</strong></p>'
        "<p><em>You requested a password recovery for iguanatrader. "
        "Use this temporary password to sign in; on first login you "
        "will be required to change it for a new one.</em></p>"
    )
    html, plain_text = render_email_template(
        subject="Recuperación de contraseña",
        preheader="Tu contraseña temporal para iguanatrader",
        headline=headline,
        body_html=body_html,
    )
    return OutboundMessage(
        body=plain_text,
        subject="Recuperación de contraseña",
        correlation_id=correlation_id,
        metadata={"html_body": html},
    )


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
@limiter.limit("3/hour")
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    session: AsyncSession = Depends(get_db),
) -> ForgotPasswordResponse:
    """Issue a temporary password + fan it out to the user's wired channels.

    Flow (per spec ``web-authentication`` forgot-password addendum):

    1. Lookup user by email (case-sensitive on the existing column;
       same shape as :func:`login`). The DB collation determines
       case-sensitivity — SQLite default is case-sensitive, PostgreSQL
       depends on the column type; both are acceptable for MVP.
    2. **Anti-enumeration**: if no user matches, return the same generic
       200 payload as the success path — no timing-attack hardening
       needed because Argon2 cost dwarfs any DB query latency.
    2.5. **Guardrail** (slice ``auth-forgot-password-guardrail``): refuse
       to rotate the hash if the resolved dispatcher cannot actually
       transmit the temp password (i.e., the tree is a transitive
       :class:`LogOnlyMessageDispatcher`). Same generic 200 payload —
       only the WARN log
       ``auth.password.forgot.no_recovery_channel_configured`` exposes
       the dropped request to operators.
    3. Generate a 16-char temp password
       (:func:`generate_temp_password`), hash with Argon2id, and write
       it to ``users`` along with ``must_change_password=TRUE`` and a
       fresh ``password_changed_at``. The user MUST rotate on first
       login (gated by :class:`MustChangePasswordMiddleware`).
    4. Resolve recipients via
       :func:`resolve_recipients_for_user` (email always-on; Telegram +
       WhatsApp opt-in via the new columns from slice
       ``auth-forgot-password-flow``).
    5. ``await dispatcher.dispatch(message=, recipients=)``. Per-channel
       failures are isolated by :class:`MultiChannelMessageDispatcher`
       and surface as ``status='failed'`` :class:`DispatchResult`
       entries — they do NOT fail the request.
    6. Return 200 with the generic message.

    Rate-limit: ``3/hour`` keyed on the IP via slowapi's default
    keyfunc behaviour for non-login routes (the login-specific
    ``(ip, email)`` compound key is not used here — keep to per-IP to
    avoid over-engineering; per-email keying is a separate slice).

    Logging: emits ``auth.password.forgot.requested`` on every request
    (with the email hashed for log safety) and
    ``auth.password.forgot.dispatched`` on the success branch with the
    per-channel result counts. NEVER logs the temp password itself.
    """
    email_hash = hash_email_for_log(body.email)
    log.info("auth.password.forgot.requested", email_hash=email_hash)

    # Step 1: bootstrap-path lookup — tenant_id_var is unset (the user
    # is not authenticated yet). Same helper as ``POST /login``.
    user = await bootstrap_load_user_by_email(session, body.email)

    if user is None:
        log.info(
            "auth.password.forgot.email_unknown",
            email_hash=email_hash,
        )
        # Step 2: anti-enumeration. Same payload + status as the
        # success branch. NO dispatcher call.
        return ForgotPasswordResponse(message=FORGOT_PASSWORD_GENERIC_MESSAGE)

    # Step 2.5: GUARDRAIL (slice ``auth-forgot-password-guardrail``).
    # Resolve the dispatcher EARLY (before rotating the hash) so we can
    # detect the log-only fallback path — see :func:`_dispatcher_can_deliver`
    # docstring for the footgun this prevents. If the resolved tree
    # cannot actually transmit the temp password we MUST NOT rotate
    # ``password_hash`` / ``must_change_password`` / ``password_changed_at``
    # — otherwise the user's credential is destroyed with no recovery
    # path. We still return the generic 200 to preserve anti-enumeration
    # (an unauthenticated caller MUST NOT be able to probe "is recovery
    # configured?" via status code or response body). Operators see the
    # dropped request via the WARN log below.
    dispatcher = _resolve_forgot_password_dispatcher()
    if not _dispatcher_can_deliver(dispatcher):
        log.warning(
            "auth.password.forgot.no_recovery_channel_configured",
            email_hash=email_hash,
            user_id=str(user.id),
            note=(
                "resolved dispatcher is log-only — refusing to rotate the "
                "password hash to avoid silent account lockout. Configure "
                "IGUANATRADER_CHANNEL_DISPATCHER + the relevant transport "
                "credentials and retry."
            ),
        )
        return ForgotPasswordResponse(message=FORGOT_PASSWORD_GENERIC_MESSAGE)

    # Step 3: generate + hash + persist. Raw SQL UPDATE — bypasses the
    # ORM identity map (same pattern as :func:`change_password`).
    temp_password = generate_temp_password()
    new_hash = hash_password(temp_password)
    await session.execute(
        text(
            "UPDATE users SET password_hash = :hash, "
            "must_change_password = 1, "
            "password_changed_at = CURRENT_TIMESTAMP, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE id = :uid"
        ),
        {"hash": new_hash, "uid": user.id.hex},
    )
    await session.commit()

    # Step 4: resolve recipients from the user record. The dispatcher
    # filters by channel internally, so over-listing recipients on
    # channels that are not wired in the current dispatcher is safe
    # (the multi-dispatcher just emits ``skipped`` for unknown
    # channels).
    recipients = resolve_recipients_for_user(user)
    if not recipients:
        log.warning(
            "auth.password.forgot.no_recipients",
            email_hash=email_hash,
            user_id=str(user.id),
            note="user record has no email/telegram/whatsapp populated",
        )
        # Still return the generic success message — anti-enumeration
        # also covers the "user exists but has no channels" edge case.
        return ForgotPasswordResponse(message=FORGOT_PASSWORD_GENERIC_MESSAGE)

    # Step 5: dispatch. The dispatcher is responsible for per-channel
    # isolation; we wrap the call in try/except as defense in depth so
    # a constructor-time crash in the dispatcher tree cannot leak a 500
    # to the caller (which would also be a side-channel — a 500 vs 200
    # is observable enumeration). ``dispatcher`` was already resolved
    # above by the guardrail (Step 2.5) — we reuse the same instance so
    # the dispatcher tree is constructed exactly once per request.
    message = _render_forgot_password_message(
        temp_password=temp_password,
        correlation_id=f"forgot-password:{user.id}",
    )
    try:
        results = await dispatcher.dispatch(message=message, recipients=recipients)
    except Exception as exc:
        log.warning(
            "auth.password.forgot.dispatch_failed",
            email_hash=email_hash,
            user_id=str(user.id),
            error=str(exc),
            error_type=type(exc).__name__,
        )
        # Still return generic success — the credential IS rotated;
        # the operator can read the password from the DB or re-issue.
        return ForgotPasswordResponse(message=FORGOT_PASSWORD_GENERIC_MESSAGE)

    delivered = sum(1 for r in results if r.status == "delivered")
    failed = sum(1 for r in results if r.status == "failed")
    skipped = sum(1 for r in results if r.status == "skipped")
    log.info(
        "auth.password.forgot.dispatched",
        email_hash=email_hash,
        user_id=str(user.id),
        delivered=delivered,
        failed=failed,
        skipped=skipped,
        channels=[r.channel for r in results],
    )

    return ForgotPasswordResponse(message=FORGOT_PASSWORD_GENERIC_MESSAGE)


__all__ = [
    "FORGOT_PASSWORD_GENERIC_MESSAGE",
    "router",
    "set_forgot_password_dispatcher_override",
]
