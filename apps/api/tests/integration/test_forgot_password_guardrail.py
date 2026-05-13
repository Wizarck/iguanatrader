"""Integration tests for slice ``auth-forgot-password-guardrail``.

Parent slice :pr:`135` (``auth-forgot-password-flow``) shipped a footgun:
when ``IGUANATRADER_CHANNEL_DISPATCHER`` is unset (the default MVP
profile) ``build_user_channel_dispatcher_from_env`` returns
:class:`LogOnlyMessageDispatcher`. The original route rotated
``users.password_hash`` BEFORE checking whether the dispatcher could
deliver — so the temp password was never readable by anyone and the
user was silently locked out of their account.

This slice adds a guardrail that refuses to rotate the hash when the
resolved dispatcher tree is transitively log-only. Anti-enumeration is
preserved (the unauthenticated caller still sees the generic 200
response); operators observe the dropped request via the
``auth.password.forgot.no_recovery_channel_configured`` WARN log.

Four cases:

1. No channels configured (selector empty + SMTP/Telegram/Hermes env
   cleared) → 200 generic + hash UNCHANGED + ``must_change_password``
   still FALSE + WARN emitted.
2. ``telegram_hermes`` selector but every channel's creds missing →
   composed tree is log-only → guardrail trips → hash UNCHANGED.
3. Test-only override with a real recording dispatcher → hash IS
   rotated + dispatcher receives the message (proves the guardrail is
   opt-out via the override hook used by :pr:`135` happy-path tests).
4. Mixed ``MultiChannelMessageDispatcher`` with one real adapter + one
   :class:`LogOnlyMessageDispatcher` → ``_dispatcher_can_deliver``
   returns True → hash IS rotated. Locks down the "ANY real channel"
   semantics required by the helper's contract.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from uuid import UUID

import pytest
from httpx import AsyncClient
from iguanatrader.api.auth import verify_password
from iguanatrader.api.routes.auth import (
    FORGOT_PASSWORD_GENERIC_MESSAGE,
    set_forgot_password_dispatcher_override,
)
from iguanatrader.persistence import User
from iguanatrader.shared.channel_dispatch import (
    DispatchResult,
    LogOnlyMessageDispatcher,
    MultiChannelMessageDispatcher,
    OutboundMessage,
    Recipient,
)
from iguanatrader.shared.contextvars import with_tenant_context
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .conftest import SEEDED_PLAINTEXT_PASSWORD, SEEDED_USER_EMAIL


class _RecordingDispatcher:
    """Test double — mirrors the helper from ``test_forgot_password.py``.

    Records every ``dispatch`` call. The default result list reports
    every recipient as ``delivered``; tests that need a different
    outcome can pass ``results_factory``.
    """

    def __init__(
        self,
        *,
        results_factory: object | None = None,
    ) -> None:
        self.calls: list[tuple[OutboundMessage, list[Recipient]]] = []
        self._results_factory = results_factory

    async def dispatch(
        self,
        *,
        message: OutboundMessage,
        recipients: Sequence[Recipient],
    ) -> list[DispatchResult]:
        self.calls.append((message, list(recipients)))
        if self._results_factory is not None:
            assert callable(self._results_factory)
            results = self._results_factory(list(recipients))
            assert isinstance(results, list)
            return results
        return [
            DispatchResult(
                channel=r.channel,
                address=r.address,
                status="delivered",
                wire_message_id=f"wire-{i}",
                error=None,
            )
            for i, r in enumerate(recipients)
        ]


@pytest.fixture
def _clear_channel_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every env var that could spawn a real dispatcher leaf.

    Used by the cases that exercise the env-driven build path (i.e., they
    rely on :func:`build_user_channel_dispatcher_from_env` resolving to a
    log-only tree). The selector is explicitly deleted so the unset
    branch (which short-circuits to :class:`LogOnlyMessageDispatcher`) is
    hit deterministically — pytest workers can inherit a populated
    environment that would otherwise mask the bug.
    """
    for var in (
        "IGUANATRADER_CHANNEL_DISPATCHER",
        "IGUANATRADER_SMTP_HOST",
        "IGUANATRADER_SMTP_USERNAME",
        "IGUANATRADER_SMTP_PASSWORD",
        "IGUANATRADER_SMTP_PORT",
        "IGUANATRADER_SMTP_FROM_ADDRESS",
        "IGUANATRADER_SMTP_FROM_NAME",
        "IGUANATRADER_SMTP_USE_TLS",
        "TELEGRAM_BOT_TOKEN",
        "HERMES_BASE_URL",
        "HERMES_HMAC_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
async def _clear_override() -> AsyncIterator[None]:
    """Ensure no override leaks between guardrail tests.

    The env-driven cases MUST NOT have an override installed (otherwise
    they would test the override path, not the env-build path). Wrap in a
    try/finally so a failure in one test cannot poison the next.
    """
    set_forgot_password_dispatcher_override(None)
    try:
        yield
    finally:
        set_forgot_password_dispatcher_override(None)


async def _assert_user_unchanged(
    *,
    user_uuid: UUID,
    tenant_uuid: UUID,
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Assert the seeded user's recovery-related columns were NOT touched."""
    async with (
        with_tenant_context(tenant_uuid),
        schema_session_factory() as s,
    ):
        row = (await s.execute(select(User).where(User.id == user_uuid))).scalars().first()
        assert row is not None
        assert row.must_change_password is False
        assert row.password_changed_at is None
        # Old plaintext STILL verifies — hash was NOT rotated.
        assert verify_password(SEEDED_PLAINTEXT_PASSWORD, row.password_hash)


# --------------------------------------------------------------------------- #
# 1 — no channels configured → guardrail trips → hash unchanged
# --------------------------------------------------------------------------- #


async def test_forgot_password_guardrail_blocks_when_selector_unset(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
    schema_session_factory: async_sessionmaker[AsyncSession],
    _clear_channel_env: None,
    _clear_override: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Empty selector → ``LogOnlyMessageDispatcher`` → guardrail refuses rotation."""
    caplog.set_level(logging.WARNING, logger="iguanatrader.api.routes.auth")

    resp = await client.post(
        "/api/v1/auth/forgot-password",
        json={"email": SEEDED_USER_EMAIL},
    )

    # Anti-enumeration preserved — same payload as the happy path.
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"message": FORGOT_PASSWORD_GENERIC_MESSAGE}

    # Hash + flags MUST be untouched.
    await _assert_user_unchanged(
        user_uuid=UUID(seeded_tenant_user["user_id"]),
        tenant_uuid=UUID(seeded_tenant_user["tenant_id"]),
        schema_session_factory=schema_session_factory,
    )

    # Operator-facing WARN log surfaced.
    warn_events = [
        rec
        for rec in caplog.records
        if "auth.password.forgot.no_recovery_channel_configured" in rec.getMessage()
    ]
    assert warn_events, (
        "expected a structured WARN log "
        "auth.password.forgot.no_recovery_channel_configured to surface "
        "the dropped request to operators"
    )


# --------------------------------------------------------------------------- #
# 2 — selector ``telegram_hermes`` but every cred missing → still log-only
# --------------------------------------------------------------------------- #


async def test_forgot_password_guardrail_blocks_when_creds_missing(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
    schema_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    _clear_channel_env: None,
    _clear_override: None,
) -> None:
    """Selector wired but transports unwired → composed tree is log-only."""
    # Set the selector AFTER ``_clear_channel_env`` has wiped everything,
    # so only the selector is present — every channel leaf still falls
    # back to None / log-only.
    monkeypatch.setenv("IGUANATRADER_CHANNEL_DISPATCHER", "telegram_hermes")

    resp = await client.post(
        "/api/v1/auth/forgot-password",
        json={"email": SEEDED_USER_EMAIL},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"message": FORGOT_PASSWORD_GENERIC_MESSAGE}

    # Both telegram + whatsapp creds are missing → ``_compose_user_multi_dispatcher``
    # filters out the ``None`` slots and falls back to LogOnly →
    # ``_dispatcher_can_deliver`` returns False → guardrail trips.
    await _assert_user_unchanged(
        user_uuid=UUID(seeded_tenant_user["user_id"]),
        tenant_uuid=UUID(seeded_tenant_user["tenant_id"]),
        schema_session_factory=schema_session_factory,
    )


# --------------------------------------------------------------------------- #
# 3 — real (test-double) dispatcher injected → hash IS rotated
# --------------------------------------------------------------------------- #


async def test_forgot_password_guardrail_allows_real_dispatcher_override(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``_RecordingDispatcher`` is neither LogOnly nor MultiChannel → can deliver."""
    recorder = _RecordingDispatcher()
    set_forgot_password_dispatcher_override(recorder)
    try:
        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": SEEDED_USER_EMAIL},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"message": FORGOT_PASSWORD_GENERIC_MESSAGE}

        user_uuid = UUID(seeded_tenant_user["user_id"])
        tenant_uuid = UUID(seeded_tenant_user["tenant_id"])
        async with (
            with_tenant_context(tenant_uuid),
            schema_session_factory() as s,
        ):
            row = (await s.execute(select(User).where(User.id == user_uuid))).scalars().first()
            assert row is not None
            # Hash was rotated → old plaintext no longer verifies.
            assert not verify_password(SEEDED_PLAINTEXT_PASSWORD, row.password_hash)
            assert row.must_change_password is True
            assert row.password_changed_at is not None

        # Dispatcher was actually invoked.
        assert len(recorder.calls) == 1
        _msg, recipients = recorder.calls[0]
        assert [r.channel for r in recipients] == ["email"]
    finally:
        set_forgot_password_dispatcher_override(None)


# --------------------------------------------------------------------------- #
# 4 — MultiChannel with one real + one LogOnly → ANY real → can deliver
# --------------------------------------------------------------------------- #


async def test_forgot_password_guardrail_mixed_multi_allows_rotation(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """MultiChannel = {real, LogOnly} → ``_dispatcher_can_deliver`` returns True."""
    real_leaf = _RecordingDispatcher()
    multi = MultiChannelMessageDispatcher(
        dispatchers={
            "email": real_leaf,
            "telegram": LogOnlyMessageDispatcher(),
        }
    )
    set_forgot_password_dispatcher_override(multi)
    try:
        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": SEEDED_USER_EMAIL},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"message": FORGOT_PASSWORD_GENERIC_MESSAGE}

        user_uuid = UUID(seeded_tenant_user["user_id"])
        tenant_uuid = UUID(seeded_tenant_user["tenant_id"])
        async with (
            with_tenant_context(tenant_uuid),
            schema_session_factory() as s,
        ):
            row = (await s.execute(select(User).where(User.id == user_uuid))).scalars().first()
            assert row is not None
            # Hash WAS rotated — at least one real leaf can carry the credential.
            assert not verify_password(SEEDED_PLAINTEXT_PASSWORD, row.password_hash)
            assert row.must_change_password is True

        # The MultiChannel dispatcher routes the email recipient to the
        # real leaf; the LogOnly leaf gets no recipient because the
        # seeded user has no telegram_chat_id. The real leaf MUST have
        # been invoked exactly once.
        assert len(real_leaf.calls) == 1
        _msg, recipients = real_leaf.calls[0]
        assert [r.channel for r in recipients] == ["email"]
    finally:
        set_forgot_password_dispatcher_override(None)
