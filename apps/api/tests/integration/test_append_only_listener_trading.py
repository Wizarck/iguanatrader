"""Append-only listener semantics on the trading-context tables.

Per design D4:

* ``trade_proposals`` / ``fills`` / ``equity_snapshots`` — pure
  append-only; UPDATE on any column raises.
* ``trades`` — column-level whitelist ``{state, closed_at}``; UPDATE
  on those columns succeeds, on ``symbol`` raises.
* ``orders`` — column-level whitelist ``{state, broker_order_id,
  submitted_at, acknowledged_at, closed_at}``.

These tests exercise the slice-T1 extension to the slice-3 listener
(``__append_only_mutable_columns__`` whitelist) — see
``apps/api/src/iguanatrader/persistence/append_only_listener.py``.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.trading.models import (
    Order,
    StrategyConfig,
    Trade,
    TradeProposal,
)
from iguanatrader.persistence import (
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.persistence.errors import AppendOnlyViolationError
from iguanatrader.shared.contextvars import with_tenant_context
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    db_path = tmp_path / "ig_trading_listener.db"
    return f"sqlite+aiosqlite:///{db_path.as_posix()}"


@pytest.fixture
async def engine(db_url: str) -> AsyncIterator[AsyncEngine]:
    eng = engine_factory(db_url)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def session_fx(
    engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield session_factory(engine)
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(autouse=True)
def _register_listeners() -> Iterator[None]:
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()


async def _seed_tenant_and_strategy(
    session_fx: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
) -> UUID:
    """Insert a tenant + a strategy_config; return the strategy_config_id."""
    strategy_id = uuid4()
    async with session_fx() as s:
        s.add(Tenant(id=tenant_id, name="t-listener", feature_flags={}))
        await s.commit()
    async with with_tenant_context(tenant_id), session_fx() as s:
        s.add(
            StrategyConfig(
                id=strategy_id,
                tenant_id=tenant_id,
                strategy_kind="donchian_atr",
                symbol="SPY",
                params={"lookback": 20},
                enabled=True,
                version=1,
            )
        )
        await s.commit()
    return strategy_id


async def test_update_on_trade_proposals_raises(
    session_fx: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = uuid4()
    strategy_id = await _seed_tenant_and_strategy(session_fx, tenant_id)
    proposal_id = uuid4()

    async with with_tenant_context(tenant_id), session_fx() as s:
        s.add(
            TradeProposal(
                id=proposal_id,
                tenant_id=tenant_id,
                strategy_config_id=strategy_id,
                symbol="SPY",
                side="buy",
                quantity=Decimal("10"),
                entry_price_indicative=Decimal("450.25"),
                stop_price=Decimal("440.0"),
                confidence_score=Decimal("0.75"),
                reasoning={"k": "v"},
                research_brief_id=None,
                mode="paper",
                correlation_id=uuid4(),
            )
        )
        await s.commit()

    async with with_tenant_context(tenant_id), session_fx() as s:
        proposal = (
            await s.execute(select(TradeProposal).where(TradeProposal.id == proposal_id))
        ).scalar_one()
        proposal.reasoning = {"mutated": "should-raise"}
        with pytest.raises(AppendOnlyViolationError):
            await s.commit()


async def test_update_on_trade_state_succeeds(
    session_fx: async_sessionmaker[AsyncSession],
) -> None:
    """``trades.state`` is in the whitelist — UPDATE allowed."""
    tenant_id = uuid4()
    strategy_id = await _seed_tenant_and_strategy(session_fx, tenant_id)
    proposal_id = uuid4()
    trade_id = uuid4()

    async with with_tenant_context(tenant_id), session_fx() as s:
        s.add(
            TradeProposal(
                id=proposal_id,
                tenant_id=tenant_id,
                strategy_config_id=strategy_id,
                symbol="SPY",
                side="buy",
                quantity=Decimal("10"),
                entry_price_indicative=Decimal("450.25"),
                stop_price=Decimal("440.0"),
                confidence_score=None,
                reasoning={},
                research_brief_id=None,
                mode="paper",
                correlation_id=uuid4(),
            )
        )
        s.add(
            Trade(
                id=trade_id,
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                symbol="SPY",
                side="buy",
                quantity=Decimal("10"),
                mode="paper",
                state="open",
                opened_at=datetime.now(UTC),
            )
        )
        await s.commit()

    async with with_tenant_context(tenant_id), session_fx() as s:
        trade = (await s.execute(select(Trade).where(Trade.id == trade_id))).scalar_one()
        trade.state = "closed"
        trade.closed_at = datetime.now(UTC)
        await s.commit()  # Should NOT raise — both columns whitelisted.

    async with with_tenant_context(tenant_id), session_fx() as s:
        trade = (await s.execute(select(Trade).where(Trade.id == trade_id))).scalar_one()
        assert trade.state == "closed"
        assert trade.closed_at is not None


async def test_update_on_trade_symbol_raises(
    session_fx: async_sessionmaker[AsyncSession],
) -> None:
    """``trades.symbol`` is NOT in the whitelist — UPDATE rejected."""
    tenant_id = uuid4()
    strategy_id = await _seed_tenant_and_strategy(session_fx, tenant_id)
    proposal_id = uuid4()
    trade_id = uuid4()

    async with with_tenant_context(tenant_id), session_fx() as s:
        s.add(
            TradeProposal(
                id=proposal_id,
                tenant_id=tenant_id,
                strategy_config_id=strategy_id,
                symbol="SPY",
                side="buy",
                quantity=Decimal("10"),
                entry_price_indicative=Decimal("450.25"),
                stop_price=Decimal("440.0"),
                confidence_score=None,
                reasoning={},
                research_brief_id=None,
                mode="paper",
                correlation_id=uuid4(),
            )
        )
        s.add(
            Trade(
                id=trade_id,
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                symbol="SPY",
                side="buy",
                quantity=Decimal("10"),
                mode="paper",
                state="open",
                opened_at=datetime.now(UTC),
            )
        )
        await s.commit()

    async with with_tenant_context(tenant_id), session_fx() as s:
        trade = (await s.execute(select(Trade).where(Trade.id == trade_id))).scalar_one()
        trade.symbol = "QQQ"
        with pytest.raises(AppendOnlyViolationError):
            await s.commit()


async def test_update_on_order_broker_order_id_succeeds(
    session_fx: async_sessionmaker[AsyncSession],
) -> None:
    """``orders.broker_order_id`` is whitelisted (settable on broker confirm)."""
    tenant_id = uuid4()
    strategy_id = await _seed_tenant_and_strategy(session_fx, tenant_id)
    proposal_id = uuid4()
    trade_id = uuid4()
    order_id = uuid4()

    async with with_tenant_context(tenant_id), session_fx() as s:
        s.add(
            TradeProposal(
                id=proposal_id,
                tenant_id=tenant_id,
                strategy_config_id=strategy_id,
                symbol="SPY",
                side="buy",
                quantity=Decimal("10"),
                entry_price_indicative=Decimal("450"),
                stop_price=Decimal("440"),
                confidence_score=None,
                reasoning={},
                research_brief_id=None,
                mode="paper",
                correlation_id=uuid4(),
            )
        )
        s.add(
            Trade(
                id=trade_id,
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                symbol="SPY",
                side="buy",
                quantity=Decimal("10"),
                mode="paper",
                state="open",
                opened_at=datetime.now(UTC),
            )
        )
        s.add(
            Order(
                id=order_id,
                tenant_id=tenant_id,
                trade_id=trade_id,
                broker="ibkr",
                broker_order_id=None,
                order_type="market",
                side="buy",
                quantity=Decimal("10"),
                state="new",
            )
        )
        await s.commit()

    async with with_tenant_context(tenant_id), session_fx() as s:
        order = (await s.execute(select(Order).where(Order.id == order_id))).scalar_one()
        order.broker_order_id = "IB-12345"
        order.state = "submitted"
        order.submitted_at = datetime.now(UTC)
        await s.commit()


async def test_update_on_trade_exit_reason_and_realised_pnl_succeeds(
    session_fx: async_sessionmaker[AsyncSession],
) -> None:
    """``trades.exit_reason`` + ``trades.realised_pnl`` are whitelisted.

    Slice ``trades-add-exit-and-realised-pnl-columns``: the (future)
    close-flow service populates both columns alongside ``state`` +
    ``closed_at`` in a single UPDATE. The whitelist must permit that
    UPDATE; without the whitelist edit the append-only listener would
    raise. This test also exercises the ORM read-back so the columns
    are accessible as ``Mapped`` attributes.
    """
    tenant_id = uuid4()
    strategy_id = await _seed_tenant_and_strategy(session_fx, tenant_id)
    proposal_id = uuid4()
    trade_id = uuid4()

    async with with_tenant_context(tenant_id), session_fx() as s:
        s.add(
            TradeProposal(
                id=proposal_id,
                tenant_id=tenant_id,
                strategy_config_id=strategy_id,
                symbol="SPY",
                side="buy",
                quantity=Decimal("10"),
                entry_price_indicative=Decimal("450"),
                stop_price=Decimal("440"),
                confidence_score=None,
                reasoning={},
                research_brief_id=None,
                mode="paper",
                correlation_id=uuid4(),
            )
        )
        s.add(
            Trade(
                id=trade_id,
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                symbol="SPY",
                side="buy",
                quantity=Decimal("10"),
                mode="paper",
                state="open",
                opened_at=datetime.now(UTC),
            )
        )
        await s.commit()

    # Fresh INSERT — both columns default to NULL ("unknown").
    async with with_tenant_context(tenant_id), session_fx() as s:
        trade = (await s.execute(select(Trade).where(Trade.id == trade_id))).scalar_one()
        assert trade.exit_reason is None
        assert trade.realised_pnl is None

    # Whitelisted UPDATE — close-flow shape: state + closed_at +
    # exit_reason + realised_pnl in one commit.
    async with with_tenant_context(tenant_id), session_fx() as s:
        trade = (await s.execute(select(Trade).where(Trade.id == trade_id))).scalar_one()
        trade.state = "closed"
        trade.closed_at = datetime.now(UTC)
        trade.exit_reason = "stop"
        trade.realised_pnl = Decimal("-42.50000000")
        await s.commit()

    async with with_tenant_context(tenant_id), session_fx() as s:
        trade = (await s.execute(select(Trade).where(Trade.id == trade_id))).scalar_one()
        assert trade.exit_reason == "stop"
        assert trade.realised_pnl == Decimal("-42.50000000")


async def test_strategy_config_update_bumps_version(
    session_fx: async_sessionmaker[AsyncSession],
) -> None:
    """Mutable :class:`StrategyConfig` UPDATE bumps :attr:`version` via hook.

    The slice-T1 ``before_update`` listener increments ``version`` and
    emits ``trading.config.changed``; slice O1 will land the
    ``config_changes`` row insert.
    """
    tenant_id = uuid4()
    strategy_id = await _seed_tenant_and_strategy(session_fx, tenant_id)

    async with with_tenant_context(tenant_id), session_fx() as s:
        cfg = (
            await s.execute(select(StrategyConfig).where(StrategyConfig.id == strategy_id))
        ).scalar_one()
        original = cfg.version
        cfg.params = {"lookback": 30}
        await s.commit()

    async with with_tenant_context(tenant_id), session_fx() as s:
        cfg = (
            await s.execute(select(StrategyConfig).where(StrategyConfig.id == strategy_id))
        ).scalar_one()
        assert cfg.version == original + 1
