"""MCP HITL adapter — owner approve happy path + idempotency.

Slice ``mcp-hitl-approvals`` §3. Companion to ``test_mcp_hitl.py``: seeds a
real ``trade_proposals`` parent (the ``approval_requests.proposal_id`` FK is
enforced under SQLite ``foreign_keys=ON``) plus its ``strategy_configs``
parent, then drives ``approve_proposal`` through the real dispatch chain and
asserts a granted decision is recorded exactly once.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from iguanatrader.api.routes.mcp_hitl import _run_action, list_pending_approvals
from iguanatrader.contexts.approval.bootstrap import get_message_bus
from iguanatrader.contexts.approval.channels.command_handler import (
    reset_idempotency_cache,
)
from iguanatrader.contexts.approval.models import ApprovalDecision
from iguanatrader.contexts.approval.repository import ApprovalRepository
from iguanatrader.contexts.approval.service import ApprovalService
from iguanatrader.contexts.trading.models import StrategyConfig, TradeProposal
from iguanatrader.persistence import (
    AuthorizedSender,
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import session_var, with_tenant_context
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

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


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    reset_idempotency_cache()


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    eng = engine_factory(f"sqlite+aiosqlite:///{(tmp_path / 'ig_mcp_hitl_approve.db').as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def sf(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return session_factory(engine)


async def _seed_owner_with_proposal(sf: async_sessionmaker[AsyncSession]) -> tuple[UUID, UUID]:
    tid = uuid4()
    pid = uuid4()
    sc_id = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name=f"t{tid.hex[:8]}", feature_flags={}))
        await s.commit()
    async with with_tenant_context(tid), sf() as s:
        s.add(
            AuthorizedSender(
                id=uuid4(),
                tenant_id=tid,
                channel="telegram",
                external_id="owner-1",
                display_name=None,
                enabled=True,
                role="owner",
            )
        )
        s.add(
            StrategyConfig(
                id=sc_id,
                tenant_id=tid,
                strategy_kind="donchian_atr",
                symbol="AAPL",
                params={"channel": 20},
                enabled=True,
                version=1,
            )
        )
        s.add(
            TradeProposal(
                id=pid,
                tenant_id=tid,
                strategy_config_id=sc_id,
                symbol="AAPL",
                side="buy",
                quantity=Decimal("10"),
                entry_price_indicative=Decimal("100"),
                stop_price=Decimal("95"),
                confidence_score=Decimal("0.90"),
                reasoning={"signal": "breakout"},
                mode="paper",
                correlation_id=uuid4(),
                state="pending_approval",
            )
        )
        await s.commit()
    return tid, pid


async def _create_request(sf: async_sessionmaker[AsyncSession], tid: UUID, pid: UUID) -> UUID:
    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        service = ApprovalService(repository=ApprovalRepository(), message_bus=get_message_bus())
        request = await service.create_request(
            proposal_id=pid,
            channels=["telegram"],
            timeout_seconds=60,
        )
        await session.commit()
        return request.id


@pytest.mark.asyncio
async def test_owner_approve_records_granted_decision(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid, pid = await _seed_owner_with_proposal(sf)
    request_id = await _create_request(sf, tid, pid)

    async with with_tenant_context(tid), sf() as db:
        resp = await _run_action(
            db,
            command_name="/approve",
            channel="telegram",
            external_id="owner-1",
            request_id=request_id,
        )
    assert resp.status == "ok"

    async with with_tenant_context(tid), sf() as check:
        session_var.set(check)
        decision = await ApprovalRepository().get_decision(request_id)
    assert decision is not None
    assert decision.outcome == "granted"


@pytest.mark.asyncio
async def test_enriched_notification_includes_proposal_fields(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    from datetime import UTC, datetime, timedelta

    from iguanatrader.contexts.approval.channels.types import ApprovalRequestRow
    from iguanatrader.contexts.approval.dispatcher import (
        build_outbound_message_from_request,
    )

    tid, pid = await _seed_owner_with_proposal(sf)
    async with with_tenant_context(tid), sf() as s:
        proposal = await s.get(TradeProposal, pid)
        request = ApprovalRequestRow(
            id=uuid4(),
            tenant_id=tid,
            proposal_id=pid,
            delivered_to_channels=["telegram"],
            timeout_seconds=300,
            expires_at=datetime.now(UTC) + timedelta(seconds=300),
            created_at=datetime.now(UTC),
        )
        message = build_outbound_message_from_request(request, proposal)

    # Enriched body carries the decision-relevant fields + the proposal id.
    assert "AAPL" in message.body
    assert "buy" in message.body
    assert "stop" in message.body
    assert str(pid) in message.body
    # Sparse fallback (no proposal) keeps the proposal id for correlation.
    sparse = build_outbound_message_from_request(request)
    assert str(pid) in sparse.body
    assert "AAPL" not in sparse.body


@pytest.mark.asyncio
async def test_notification_appends_auto_explain_narrative(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    """A1: the LLM rationale attached as ``request.narrative`` reaches the body
    (the bug was that the message builder ignored it)."""
    from datetime import UTC, datetime, timedelta

    from iguanatrader.contexts.approval.channels.types import ApprovalRequestRow
    from iguanatrader.contexts.approval.dispatcher import (
        build_outbound_message_from_request,
    )

    tid, pid = await _seed_owner_with_proposal(sf)
    rationale = "Donchian 20d breakout, ATR-sized stop; momentum + volume confirm."
    async with with_tenant_context(tid), sf() as s:
        proposal = await s.get(TradeProposal, pid)

        def _row() -> ApprovalRequestRow:
            return ApprovalRequestRow(
                id=uuid4(),
                tenant_id=tid,
                proposal_id=pid,
                delivered_to_channels=["telegram"],
                timeout_seconds=300,
                expires_at=datetime.now(UTC) + timedelta(seconds=300),
                created_at=datetime.now(UTC),
            )

        with_narr = _row()
        object.__setattr__(with_narr, "narrative", rationale)
        enriched = build_outbound_message_from_request(with_narr, proposal)

        without = build_outbound_message_from_request(_row(), proposal)

    assert rationale in enriched.body  # the reasoning reached the phone
    assert "AAPL" in enriched.body  # base enrichment preserved
    assert rationale not in without.body  # no narrative attr → unchanged body


@pytest.mark.asyncio
async def test_list_pending_approvals_returns_proposal_summary(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid, pid = await _seed_owner_with_proposal(sf)
    request_id = await _create_request(sf, tid, pid)

    async with with_tenant_context(tid), sf() as db:
        resp = await list_pending_approvals(db)

    assert len(resp.pending) == 1
    item = resp.pending[0]
    assert item.request_id == request_id
    assert item.proposal_id == pid
    assert item.symbol == "AAPL"
    assert item.side == "buy"
    assert item.quantity is not None and Decimal(item.quantity) == Decimal("10")
    assert item.entry_price_indicative is not None and Decimal(
        item.entry_price_indicative
    ) == Decimal("100")
    assert item.stop_price is not None and Decimal(item.stop_price) == Decimal("95")


@pytest.mark.asyncio
async def test_duplicate_approve_records_single_decision(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid, pid = await _seed_owner_with_proposal(sf)
    request_id = await _create_request(sf, tid, pid)

    for _ in range(2):
        async with with_tenant_context(tid), sf() as db:
            resp = await _run_action(
                db,
                command_name="/approve",
                channel="telegram",
                external_id="owner-1",
                request_id=request_id,
                idempotency_key="hermes-callback-abc",
            )
        assert resp.status == "ok"

    async with with_tenant_context(tid), sf() as check:
        session_var.set(check)
        count = (
            await check.execute(
                select(func.count())
                .select_from(ApprovalDecision)
                .where(ApprovalDecision.request_id == request_id)
            )
        ).scalar_one()
    assert count == 1
