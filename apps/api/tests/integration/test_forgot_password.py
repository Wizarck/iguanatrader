"""Integration tests for the slice ``auth-forgot-password-flow`` HTTP surface.

Six cases (proposal §Tests):

1. Known email → 200 + generic message + ``must_change_password=TRUE`` +
   ``password_hash`` rotated + dispatcher called once.
2. Unknown email → 200 + same generic message + dispatcher NOT called.
3. Rate limit: 4th request within 1h → 429.
4. Email-only fallback when Telegram + WhatsApp creds missing →
   dispatcher fans to 1 channel (email only).
5. Multi-channel fanout when all three channels wired (telegram +
   whatsapp + email) → 3 :class:`Recipient` instances; transport error
   in one → other two still succeed.
6. After successful recovery, ``POST /auth/login`` with the temp
   password works, but ``GET /portfolio`` returns 403 password-change-
   required until ``change-password`` is called.

The dispatcher used by the route is swapped via
:func:`set_forgot_password_dispatcher_override` so tests do NOT hit
real SMTP / Telegram / WhatsApp transports.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any
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
    OutboundMessage,
    Recipient,
)
from iguanatrader.shared.contextvars import with_tenant_context
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .conftest import SEEDED_PLAINTEXT_PASSWORD, SEEDED_USER_EMAIL


class _RecordingDispatcher:
    """Test double :class:`MessageDispatcher` — records the calls.

    Returns a configurable list of :class:`DispatchResult` rows; the
    default mirrors a happy-path delivery for every recipient so cases
    that care only about "was the dispatcher called?" do not need to
    program a result table.
    """

    def __init__(
        self,
        *,
        results_factory: Any | None = None,
        raise_on_dispatch: BaseException | None = None,
    ) -> None:
        self.calls: list[tuple[OutboundMessage, list[Recipient]]] = []
        self._results_factory = results_factory
        self._raise = raise_on_dispatch

    async def dispatch(
        self,
        *,
        message: OutboundMessage,
        recipients: Sequence[Recipient],
    ) -> list[DispatchResult]:
        self.calls.append((message, list(recipients)))
        if self._raise is not None:
            raise self._raise
        if self._results_factory is not None:
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
async def dispatcher_override() -> AsyncIterator[_RecordingDispatcher]:
    """Swap in a :class:`_RecordingDispatcher` for the duration of the test."""
    recorder = _RecordingDispatcher()
    set_forgot_password_dispatcher_override(recorder)
    try:
        yield recorder
    finally:
        set_forgot_password_dispatcher_override(None)


# --------------------------------------------------------------------------- #
# 1 — known email → 200 + flag + hash rotated + dispatcher called once
# --------------------------------------------------------------------------- #


async def test_forgot_password_known_email_rotates_hash_and_dispatches(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
    schema_session_factory: async_sessionmaker[AsyncSession],
    dispatcher_override: _RecordingDispatcher,
) -> None:
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
        assert row.must_change_password is True
        assert row.password_changed_at is not None
        # Old plaintext no longer verifies — hash was rotated.
        assert not verify_password(SEEDED_PLAINTEXT_PASSWORD, row.password_hash)

    # Dispatcher was called exactly once with one (email) recipient.
    assert len(dispatcher_override.calls) == 1
    _msg, recipients = dispatcher_override.calls[0]
    assert [r.channel for r in recipients] == ["email"]
    assert recipients[0].address == SEEDED_USER_EMAIL


# --------------------------------------------------------------------------- #
# 2 — unknown email → same generic 200 + dispatcher NOT called
# --------------------------------------------------------------------------- #


async def test_forgot_password_unknown_email_anti_enumeration(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
    dispatcher_override: _RecordingDispatcher,
) -> None:
    resp = await client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "ghost@example.com"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"message": FORGOT_PASSWORD_GENERIC_MESSAGE}
    # Dispatcher MUST NOT be called for an unknown email.
    assert dispatcher_override.calls == []


# --------------------------------------------------------------------------- #
# 3 — rate-limit: 4th request within 1h → 429
# --------------------------------------------------------------------------- #


async def test_forgot_password_rate_limited_after_3_attempts(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
    dispatcher_override: _RecordingDispatcher,
) -> None:
    payload = {"email": SEEDED_USER_EMAIL}
    # 3 attempts succeed.
    for _ in range(3):
        r = await client.post("/api/v1/auth/forgot-password", json=payload)
        assert r.status_code == 200, r.text

    # 4th attempt hits the limit.
    fourth = await client.post("/api/v1/auth/forgot-password", json=payload)
    assert fourth.status_code == 429
    assert fourth.headers["content-type"].startswith("application/problem+json")
    body = fourth.json()
    assert body["status"] == 429
    assert body["type"] == "urn:iguanatrader:error:rate-limit"


# --------------------------------------------------------------------------- #
# 4 — email-only fallback (Telegram + WhatsApp creds missing)
# --------------------------------------------------------------------------- #


async def test_forgot_password_email_only_fallback_when_other_channels_unset(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
    dispatcher_override: _RecordingDispatcher,
) -> None:
    # Seeded user has email only — telegram_chat_id + whatsapp_phone are
    # NULL on insert. The dispatcher MUST receive exactly one
    # ``email``-channel recipient.
    resp = await client.post(
        "/api/v1/auth/forgot-password",
        json={"email": SEEDED_USER_EMAIL},
    )
    assert resp.status_code == 200

    assert len(dispatcher_override.calls) == 1
    _msg, recipients = dispatcher_override.calls[0]
    channels = [r.channel for r in recipients]
    assert channels == ["email"]


# --------------------------------------------------------------------------- #
# 5 — multi-channel fanout (telegram + whatsapp + email); one failure
#     does not block the others
# --------------------------------------------------------------------------- #


async def test_forgot_password_multi_channel_fanout_with_partial_failure(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Wire telegram_chat_id + whatsapp_phone on the seeded user so
    # :func:`resolve_recipients_for_user` returns all three channels.
    user_uuid = UUID(seeded_tenant_user["user_id"])
    async with schema_session_factory() as s:
        await s.execute(
            text(
                "UPDATE users SET telegram_chat_id = :tg, whatsapp_phone = :wa " "WHERE id = :uid"
            ),
            {
                "tg": "123456789",
                "wa": "+15551234567",
                "uid": user_uuid.hex,
            },
        )
        await s.commit()

    # One transport failure (telegram); other two deliver.
    def _results_factory(recs: list[Recipient]) -> list[DispatchResult]:
        out: list[DispatchResult] = []
        for r in recs:
            if r.channel == "telegram":
                out.append(
                    DispatchResult(
                        channel=r.channel,
                        address=r.address,
                        status="failed",
                        wire_message_id=None,
                        error="RuntimeError: bot offline",
                    )
                )
            else:
                out.append(
                    DispatchResult(
                        channel=r.channel,
                        address=r.address,
                        status="delivered",
                        wire_message_id="wire-id",
                        error=None,
                    )
                )
        return out

    recorder = _RecordingDispatcher(results_factory=_results_factory)
    set_forgot_password_dispatcher_override(recorder)
    try:
        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": SEEDED_USER_EMAIL},
        )
        # Per-channel failure MUST NOT fail the request.
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"message": FORGOT_PASSWORD_GENERIC_MESSAGE}

        assert len(recorder.calls) == 1
        _msg, recipients = recorder.calls[0]
        channels = sorted(r.channel for r in recipients)
        assert channels == ["email", "telegram", "whatsapp"]
    finally:
        set_forgot_password_dispatcher_override(None)


# --------------------------------------------------------------------------- #
# 6 — after recovery, login with temp password works but gated until rotate
# --------------------------------------------------------------------------- #


async def test_forgot_password_temp_password_login_then_change_required(
    client: AsyncClient,
    seeded_tenant_user: dict[str, str],
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Capture the temp password by intercepting the dispatcher call.
    captured: dict[str, str] = {}

    def _capture(recs: list[Recipient]) -> list[DispatchResult]:
        return [
            DispatchResult(
                channel=r.channel,
                address=r.address,
                status="delivered",
                wire_message_id=None,
                error=None,
            )
            for r in recs
        ]

    class _CaptureDispatcher(_RecordingDispatcher):
        async def dispatch(
            self,
            *,
            message: OutboundMessage,
            recipients: Sequence[Recipient],
        ) -> list[DispatchResult]:
            # The plain-text body carries the temp password as the only
            # ``XXXX-XXXX-XXXX-XXXX``-shaped token. We pull it out
            # rather than redesign the route to expose the password.
            import re

            match = re.search(
                r"\b[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}\b",
                message.body,
            )
            assert match is not None, f"no temp-password token in body: {message.body!r}"
            captured["temp_password"] = match.group(0)
            return _capture(list(recipients))

    recorder = _CaptureDispatcher()
    set_forgot_password_dispatcher_override(recorder)
    try:
        # 1. Trigger recovery.
        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": SEEDED_USER_EMAIL},
        )
        assert resp.status_code == 200
        temp_password = captured["temp_password"]
        assert len(temp_password) == 19  # 16 chars + 3 dashes

        # 2. Login with the temp password works (200).
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": SEEDED_USER_EMAIL, "password": temp_password},
        )
        assert login_resp.status_code == 200, login_resp.text

        # 3. Hitting a gated route → 403 password-change-required.
        gated = await client.get("/api/v1/portfolio/summary")
        assert gated.status_code == 403
        assert gated.headers["content-type"].startswith("application/problem+json")
        body = gated.json()
        assert body["type"] == "urn:iguanatrader:error:password-change-required"

        # 4. /auth/me is allow-listed → 200 + flag set.
        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["must_change_password"] is True

        # 5. Change to a fresh password.
        rotate = await client.post(
            "/api/v1/auth/change-password",
            json={
                "old_password": temp_password,
                "new_password": "post-recovery-pw-9!",
            },
        )
        assert rotate.status_code == 204, rotate.text

        # 6. Gate steps aside — portfolio no longer 403.
        post_rotate = await client.get("/api/v1/portfolio/summary")
        assert post_rotate.status_code != 403
    finally:
        set_forgot_password_dispatcher_override(None)
