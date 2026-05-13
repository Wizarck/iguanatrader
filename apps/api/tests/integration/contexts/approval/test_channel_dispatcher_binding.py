"""Integration test for the channel-dispatch binding layer.

Asserts that the generic :class:`MessageDispatcher` core, when wrapped by
``_MessageDispatcherChannelAdapter``, correctly:

1. Builds an :class:`OutboundMessage` from an ``ApprovalRequestRow``.
2. Resolves recipients via :meth:`ApprovalRepository.list_enabled_senders`
   against real (tenant-scoped) ``authorized_senders`` rows.
3. Hands the message + recipients to the inner dispatcher in one call.

Uses a real on-disk SQLite engine + the canonical tenant-scoping listeners
so the row-level filtering behaves identically to production.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiosmtplib

# Side-effect imports — ``Base.metadata.create_all`` needs every mapped
# table registered. The approval-context test only seeds Tenant +
# AuthorizedSender rows, but ``approval_requests`` carries an FK to
# ``trade_proposals`` so the schema generator refuses to emit the FK
# without the trading model in the registry. Importing the model modules
# here is enough to register them.
import iguanatrader.contexts.approval.models as _approval_models
import iguanatrader.contexts.risk.orm as _risk_orm
import iguanatrader.contexts.trading.models as _trading_models
import pytest
from iguanatrader.contexts.approval.channels.types import ApprovalRequestRow
from iguanatrader.contexts.approval.dispatcher import (
    LogOnlyChannelDispatcher,
    _MessageDispatcherChannelAdapter,
    build_channel_dispatcher_from_env,
)
from iguanatrader.contexts.approval.repository import ApprovalRepository
from iguanatrader.persistence import (
    AuthorizedSender,
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.channel_dispatch import (
    DispatchResult,
    OutboundMessage,
    Recipient,
)
from iguanatrader.shared.contextvars import session_var, with_tenant_context
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

# Side-effect aliases (mypy/ruff happy) — referenced via ``_REGISTERED``
# below to keep the imports alive without F401 noise.
_REGISTERED = (_approval_models, _risk_orm, _trading_models)

# Same Windows event-loop quirk as other integration suites.
if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(autouse=True)
def _listeners() -> Iterator[None]:
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    eng = engine_factory(f"sqlite+aiosqlite:///{(tmp_path / 'ig_channel_binding.db').as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def sf(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return session_factory(engine)


class _RecordingDispatcher:
    """Captures dispatch calls verbatim for assertion."""

    def __init__(self) -> None:
        self.calls: list[tuple[OutboundMessage, list[Recipient]]] = []

    async def dispatch(
        self,
        *,
        message: OutboundMessage,
        recipients: Sequence[Recipient],
    ) -> list[DispatchResult]:
        self.calls.append((message, list(recipients)))
        return [
            DispatchResult(
                channel=r.channel,
                address=r.address,
                status="delivered",
                wire_message_id=f"wire-{r.address}",
                error=None,
            )
            for r in recipients
        ]


@pytest.mark.asyncio
async def test_binding_resolves_authorized_senders_and_dispatches(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = uuid4()
    other_tenant_id = uuid4()

    # Seed two tenants — both with the same channel names — so the
    # tenant-scoping query MUST filter to only the right one.
    async with sf() as s:
        s.add(Tenant(id=tenant_id, name="dispatch-tenant", feature_flags={}))
        s.add(Tenant(id=other_tenant_id, name="other-tenant", feature_flags={}))
        await s.commit()

    async with with_tenant_context(tenant_id), sf() as s:
        # Telegram + WhatsApp recipients for the target tenant.
        s.add(
            AuthorizedSender(
                id=uuid4(),
                tenant_id=tenant_id,
                channel="telegram",
                external_id="chat-111",
                display_name="Alice TG",
                enabled=True,
            )
        )
        s.add(
            AuthorizedSender(
                id=uuid4(),
                tenant_id=tenant_id,
                channel="whatsapp",
                external_id="+34999",
                display_name="Alice WA",
                enabled=True,
            )
        )
        # Disabled row — must NOT appear in recipients.
        s.add(
            AuthorizedSender(
                id=uuid4(),
                tenant_id=tenant_id,
                channel="telegram",
                external_id="chat-disabled",
                display_name=None,
                enabled=False,
            )
        )
        await s.commit()

    async with with_tenant_context(other_tenant_id), sf() as s:
        # Cross-tenant row — must NOT appear in target tenant's results.
        s.add(
            AuthorizedSender(
                id=uuid4(),
                tenant_id=other_tenant_id,
                channel="telegram",
                external_id="chat-cross",
                display_name=None,
                enabled=True,
            )
        )
        await s.commit()

    inner = _RecordingDispatcher()

    request = ApprovalRequestRow(
        id=uuid4(),
        tenant_id=tenant_id,
        proposal_id=uuid4(),
        delivered_to_channels=["telegram", "whatsapp"],
        timeout_seconds=300,
        expires_at=datetime.now(UTC) + timedelta(seconds=300),
        created_at=datetime.now(UTC),
    )

    async with with_tenant_context(tenant_id), sf() as session:
        session_var.set(session)
        repository = ApprovalRepository()
        adapter = _MessageDispatcherChannelAdapter(inner=inner, repository=repository)
        await adapter.fanout(request=request, channels=["telegram", "whatsapp"])

    # Exactly one inner.dispatch call.
    assert len(inner.calls) == 1
    message, recipients = inner.calls[0]
    # Outbound message body shape matches the canonical render.
    assert str(request.proposal_id) in message.body
    assert message.correlation_id == str(request.id)
    assert message.metadata["tenant_id"] == str(tenant_id)
    # Exactly the two enabled rows from the target tenant (disabled + cross
    # tenant rows excluded by the query).
    addresses = sorted(r.address for r in recipients)
    assert addresses == ["+34999", "chat-111"]
    channels = sorted(r.channel for r in recipients)
    assert channels == ["telegram", "whatsapp"]
    # Display names propagated through.
    by_address = {r.address: r for r in recipients}
    assert by_address["chat-111"].display_name == "Alice TG"
    assert by_address["+34999"].display_name == "Alice WA"


@pytest.mark.asyncio
async def test_binding_no_recipients_skips_dispatch(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tenant_id, name="empty-tenant", feature_flags={}))
        await s.commit()

    inner = _RecordingDispatcher()
    request = ApprovalRequestRow(
        id=uuid4(),
        tenant_id=tenant_id,
        proposal_id=uuid4(),
        delivered_to_channels=["telegram"],
        timeout_seconds=60,
        expires_at=datetime.now(UTC) + timedelta(seconds=60),
        created_at=datetime.now(UTC),
    )

    async with with_tenant_context(tenant_id), sf() as session:
        session_var.set(session)
        repository = ApprovalRepository()
        adapter = _MessageDispatcherChannelAdapter(inner=inner, repository=repository)
        # MUST NOT raise; inner dispatcher must not be invoked.
        await adapter.fanout(request=request, channels=["telegram"])

    assert inner.calls == []


@pytest.mark.asyncio
async def test_telegram_hermes_email_selector_dispatches_email(
    monkeypatch: pytest.MonkeyPatch,
    sf: async_sessionmaker[AsyncSession],
) -> None:
    """Selector ``telegram_hermes_email`` composes a multi dispatcher that
    routes an ``email`` recipient through the SMTP adapter (transport patched
    so no socket is opened)."""
    # Patch aiosmtplib.send to capture envelopes without touching the network.
    sent: list[dict[str, str | None]] = []

    async def _fake_send(msg: Any, **kwargs: Any) -> tuple[dict[str, Any], str]:
        sent.append(
            {
                "from": str(msg["From"]),
                "to": str(msg["To"]),
                "subject": str(msg["Subject"]),
                "hostname": kwargs.get("hostname"),
                "username": kwargs.get("username"),
            }
        )
        return ({}, "250 OK")

    monkeypatch.setattr(aiosmtplib, "send", _fake_send)

    # Wire env vars: telegram + hermes intentionally missing → those channels
    # fall back to log-only individually, but the email channel stays live.
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("HERMES_BASE_URL", raising=False)
    monkeypatch.delenv("HERMES_HMAC_SECRET", raising=False)
    monkeypatch.setenv("IGUANATRADER_CHANNEL_DISPATCHER", "telegram_hermes_email")
    monkeypatch.setenv("IGUANATRADER_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("IGUANATRADER_SMTP_PORT", "587")
    monkeypatch.setenv("IGUANATRADER_SMTP_USERNAME", "user@example.com")
    monkeypatch.setenv("IGUANATRADER_SMTP_PASSWORD", "supersecret")
    monkeypatch.setenv("IGUANATRADER_SMTP_FROM_ADDRESS", "iguanatrader@palafitofood.com")
    monkeypatch.setenv("IGUANATRADER_SMTP_FROM_NAME", "iguanatrader")
    monkeypatch.setenv("IGUANATRADER_SMTP_USE_TLS", "true")

    tenant_id = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tenant_id, name="email-tenant", feature_flags={}))
        await s.commit()

    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            AuthorizedSender(
                id=uuid4(),
                tenant_id=tenant_id,
                channel="email",
                external_id="alice@example.com",
                display_name="Alice",
                enabled=True,
            )
        )
        await s.commit()

    request = ApprovalRequestRow(
        id=uuid4(),
        tenant_id=tenant_id,
        proposal_id=uuid4(),
        delivered_to_channels=["email"],
        timeout_seconds=300,
        expires_at=datetime.now(UTC) + timedelta(seconds=300),
        created_at=datetime.now(UTC),
    )

    async with with_tenant_context(tenant_id), sf() as session:
        session_var.set(session)
        repository = ApprovalRepository()
        dispatcher = build_channel_dispatcher_from_env(repository=repository)
        # Must NOT be the LogOnly fallback — at least the email leg is live.
        assert not isinstance(dispatcher, LogOnlyChannelDispatcher)
        await dispatcher.fanout(request=request, channels=["email"])

    assert len(sent) == 1
    envelope = sent[0]
    assert envelope["to"] == "alice@example.com"
    assert envelope["from"] == "iguanatrader <iguanatrader@palafitofood.com>"
    assert envelope["hostname"] == "smtp.example.com"
    assert envelope["username"] == "user@example.com"
    # Subject carries the canonical brand prefix.
    assert envelope["subject"] is not None and envelope["subject"].startswith("[iguanatrader]")


def test_unset_selector_returns_log_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default behaviour (no selector env var set) yields :class:`LogOnly`."""
    monkeypatch.delenv("IGUANATRADER_CHANNEL_DISPATCHER", raising=False)
    assert isinstance(build_channel_dispatcher_from_env(), LogOnlyChannelDispatcher)


def test_email_selector_without_credentials_falls_back_to_log_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``email`` selector + missing SMTP creds → LogOnly + error log."""
    monkeypatch.setenv("IGUANATRADER_CHANNEL_DISPATCHER", "email")
    for var in (
        "IGUANATRADER_SMTP_HOST",
        "IGUANATRADER_SMTP_USERNAME",
        "IGUANATRADER_SMTP_PASSWORD",
    ):
        monkeypatch.delenv(var, raising=False)
    # Repository is provided but every channel falls back → LogOnly.
    repository = ApprovalRepository()
    dispatcher = build_channel_dispatcher_from_env(repository=repository)
    assert isinstance(dispatcher, LogOnlyChannelDispatcher)
