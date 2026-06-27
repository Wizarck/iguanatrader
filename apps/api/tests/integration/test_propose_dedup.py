"""Propose-tick flood guard (slice ``propose-dedup``).

A persistent strategy signal must NOT re-emit a fresh proposal (+ a new
approval card) on every propose tick while an entry for the same
config/symbol is still in flight. Observed flood on eligia-prod:
``TXN buy x50``, ``MSFT sell x45`` — the same signal re-proposed across
ticks because :meth:`TradingService.propose` had no dedup guard.

Covers the two repository guards (:meth:`TradeRepository.has_open_position`
+ :meth:`TradeProposalRepository.has_recent_pending`) and the service
short-circuit, against a real aiosqlite session so the COUNT queries
actually run (the unit/property propose tests use a no-op fake session).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.trading.models import (
    StrategyConfig,
    Trade,
    TradeProposal,
)
from iguanatrader.contexts.trading.ports import (
    BarHistory,
    Proposal,
    StrategyConfigSnapshot,
)
from iguanatrader.contexts.trading.repository import (
    TradeProposalRepository,
    TradeRepository,
)
from iguanatrader.contexts.trading.service import TradingService
from iguanatrader.persistence import (
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import with_session_context
from iguanatrader.shared.messagebus import MessageBus
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

_DEDUP_WINDOW = 1800


@pytest.fixture(autouse=True)
def _listeners() -> Iterator[None]:
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    db_path = tmp_path / "ig_dedup.db"
    eng = engine_factory(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def sf(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return session_factory(engine)


# ----------------------------------------------------------------------
# Seed helpers. Tenant + config land in their own committed sessions
# (the FK-safe pattern from ``test_trading_pipeline_e2e``); per-test
# proposal/trade rows are flushed into the caller's working session.
# ----------------------------------------------------------------------
async def _seed_base(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    config_id: UUID,
    symbol: str,
) -> None:
    async with sf() as s:
        s.add(Tenant(id=tenant_id, name="t-dedup", feature_flags={}))
        await s.commit()
    async with sf() as s, with_session_context(s, tenant_id):
        s.add(
            StrategyConfig(
                id=config_id,
                tenant_id=tenant_id,
                strategy_kind="donchian_atr",
                symbol=symbol,
                params={"lookback": 20},
                enabled=True,
                version=1,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await s.commit()


async def _seed_proposal(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    config_id: UUID,
    symbol: str,
    state: str,
    created_at: datetime,
) -> UUID:
    proposal_id = uuid4()
    session.add(
        TradeProposal(
            id=proposal_id,
            tenant_id=tenant_id,
            strategy_config_id=config_id,
            symbol=symbol,
            side="buy",
            quantity=Decimal("10"),
            entry_price_indicative=Decimal("100"),
            stop_price=Decimal("95"),
            target_price=Decimal("115"),
            confidence_score=Decimal("0.5"),
            reasoning={"hypothesis": "seed"},
            mode="paper",
            correlation_id=uuid4(),
            state=state,
            created_at=created_at,
        )
    )
    await session.flush()
    return proposal_id


async def _seed_open_trade(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    proposal_id: UUID,
    symbol: str,
    state: str = "open",
) -> None:
    session.add(
        Trade(
            id=uuid4(),
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            symbol=symbol,
            side="buy",
            quantity=Decimal("10"),
            mode="paper",
            state=state,
            opened_at=datetime.now(UTC),
        )
    )
    await session.flush()


# ----------------------------------------------------------------------
# Service-level fakes — propose() never calls the broker, only the
# strategy resolver; a bare stub broker suffices for construction.
# ----------------------------------------------------------------------
class _StubBroker:
    """Constructor-only placeholder — propose() does not touch the broker."""


class _AlwaysProposeStrategy:
    def __init__(self, *, tenant_id: UUID, config_id: UUID, symbol: str) -> None:
        self._proposal = Proposal(
            tenant_id=tenant_id,
            strategy_config_id=config_id,
            symbol=symbol,
            side="buy",
            quantity=Decimal("10"),
            entry_price_indicative=Decimal("100"),
            stop_price=Decimal("95"),
            confidence_score=Decimal("0.5"),
            reasoning={"hypothesis": "fire"},
            mode="paper",
            correlation_id=uuid4(),
            target_price=Decimal("115"),
        )

    def name(self) -> str:
        return "donchian_atr"

    def version(self) -> str:
        return "0.2.0"

    def evaluate(self, symbol: str, bars: BarHistory, config: StrategyConfigSnapshot) -> Proposal:
        return self._proposal


def _build_service(strategy: _AlwaysProposeStrategy) -> TradingService:
    async def _resolve(_sid: UUID) -> _AlwaysProposeStrategy:
        return strategy

    return TradingService(
        bus=MessageBus(),
        broker=_StubBroker(),  # type: ignore[arg-type]
        strategy_resolver=_resolve,
        propose_dedup_window_secs=_DEDUP_WINDOW,
    )


def _snapshot(*, tenant_id: UUID, config_id: UUID, symbol: str) -> StrategyConfigSnapshot:
    return StrategyConfigSnapshot(
        id=config_id,
        tenant_id=tenant_id,
        strategy_kind="donchian_atr",
        symbol=symbol,
        params={},
        enabled=True,
        version=1,
    )


# ----------------------------------------------------------------------
# Repository guards
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_has_open_position_detects_live_trade(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, config_id = uuid4(), uuid4()
    await _seed_base(sf, tenant_id=tenant_id, config_id=config_id, symbol="AAPL")
    async with sf() as session, with_session_context(session, tenant_id):
        pid = await _seed_proposal(
            session,
            tenant_id=tenant_id,
            config_id=config_id,
            symbol="AAPL",
            state="approved",
            created_at=datetime.now(UTC),
        )
        await _seed_open_trade(session, tenant_id=tenant_id, proposal_id=pid, symbol="AAPL")
        repo = TradeRepository()
        assert await repo.has_open_position(symbol="AAPL") is True
        assert await repo.has_open_position(symbol="MSFT") is False


@pytest.mark.asyncio
async def test_has_open_position_ignores_closed_trade(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, config_id = uuid4(), uuid4()
    await _seed_base(sf, tenant_id=tenant_id, config_id=config_id, symbol="AAPL")
    async with sf() as session, with_session_context(session, tenant_id):
        pid = await _seed_proposal(
            session,
            tenant_id=tenant_id,
            config_id=config_id,
            symbol="AAPL",
            state="approved",
            created_at=datetime.now(UTC),
        )
        await _seed_open_trade(
            session, tenant_id=tenant_id, proposal_id=pid, symbol="AAPL", state="closed"
        )
        assert await TradeRepository().has_open_position(symbol="AAPL") is False


@pytest.mark.asyncio
async def test_has_recent_pending_detects_fresh_proposal(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, config_id = uuid4(), uuid4()
    await _seed_base(sf, tenant_id=tenant_id, config_id=config_id, symbol="AAPL")
    async with sf() as session, with_session_context(session, tenant_id):
        await _seed_proposal(
            session,
            tenant_id=tenant_id,
            config_id=config_id,
            symbol="AAPL",
            state="pending_approval",
            created_at=datetime.now(UTC),
        )
        repo = TradeProposalRepository()
        assert (
            await repo.has_recent_pending(
                strategy_config_id=config_id, within_seconds=_DEDUP_WINDOW
            )
            is True
        )
        assert (
            await repo.has_recent_pending(strategy_config_id=uuid4(), within_seconds=_DEDUP_WINDOW)
            is False
        )


@pytest.mark.asyncio
async def test_has_recent_pending_ignores_stale_proposal(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    """A pending_approval row older than the window no longer blocks — robust
    to the (separate) bug where approval-timeout never advances state."""
    tenant_id, config_id = uuid4(), uuid4()
    await _seed_base(sf, tenant_id=tenant_id, config_id=config_id, symbol="AAPL")
    async with sf() as session, with_session_context(session, tenant_id):
        await _seed_proposal(
            session,
            tenant_id=tenant_id,
            config_id=config_id,
            symbol="AAPL",
            state="pending_approval",
            created_at=datetime.now(UTC) - timedelta(seconds=_DEDUP_WINDOW + 60),
        )
        assert (
            await TradeProposalRepository().has_recent_pending(
                strategy_config_id=config_id, within_seconds=_DEDUP_WINDOW
            )
            is False
        )


@pytest.mark.asyncio
async def test_has_recent_pending_ignores_decided_proposal(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    """Only ``pending_approval`` blocks — a rejected/expired row does not."""
    tenant_id, config_id = uuid4(), uuid4()
    await _seed_base(sf, tenant_id=tenant_id, config_id=config_id, symbol="AAPL")
    async with sf() as session, with_session_context(session, tenant_id):
        await _seed_proposal(
            session,
            tenant_id=tenant_id,
            config_id=config_id,
            symbol="AAPL",
            state="rejected",
            created_at=datetime.now(UTC),
        )
        assert (
            await TradeProposalRepository().has_recent_pending(
                strategy_config_id=config_id, within_seconds=_DEDUP_WINDOW
            )
            is False
        )


# ----------------------------------------------------------------------
# Service short-circuit
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_propose_skips_when_open_position(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, config_id, symbol = uuid4(), uuid4(), "AAPL"
    service = _build_service(
        _AlwaysProposeStrategy(tenant_id=tenant_id, config_id=config_id, symbol=symbol)
    )
    await _seed_base(sf, tenant_id=tenant_id, config_id=config_id, symbol=symbol)
    async with sf() as session, with_session_context(session, tenant_id):
        pid = await _seed_proposal(
            session,
            tenant_id=tenant_id,
            config_id=config_id,
            symbol=symbol,
            state="approved",
            created_at=datetime.now(UTC),
        )
        await _seed_open_trade(session, tenant_id=tenant_id, proposal_id=pid, symbol=symbol)
        result = await service.propose(
            symbol=symbol,
            strategy_config_id=config_id,
            bars=BarHistory(symbol=symbol, bars=()),
            config=_snapshot(tenant_id=tenant_id, config_id=config_id, symbol=symbol),
        )
        assert result is None


@pytest.mark.asyncio
async def test_propose_skips_when_pending_proposal(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, config_id, symbol = uuid4(), uuid4(), "AAPL"
    service = _build_service(
        _AlwaysProposeStrategy(tenant_id=tenant_id, config_id=config_id, symbol=symbol)
    )
    await _seed_base(sf, tenant_id=tenant_id, config_id=config_id, symbol=symbol)
    async with sf() as session, with_session_context(session, tenant_id):
        await _seed_proposal(
            session,
            tenant_id=tenant_id,
            config_id=config_id,
            symbol=symbol,
            state="pending_approval",
            created_at=datetime.now(UTC),
        )
        result = await service.propose(
            symbol=symbol,
            strategy_config_id=config_id,
            bars=BarHistory(symbol=symbol, bars=()),
            config=_snapshot(tenant_id=tenant_id, config_id=config_id, symbol=symbol),
        )
        assert result is None


@pytest.mark.asyncio
async def test_propose_proceeds_when_nothing_in_flight(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, config_id, symbol = uuid4(), uuid4(), "AAPL"
    service = _build_service(
        _AlwaysProposeStrategy(tenant_id=tenant_id, config_id=config_id, symbol=symbol)
    )
    await _seed_base(sf, tenant_id=tenant_id, config_id=config_id, symbol=symbol)
    async with sf() as session, with_session_context(session, tenant_id):
        result = await service.propose(
            symbol=symbol,
            strategy_config_id=config_id,
            bars=BarHistory(symbol=symbol, bars=()),
            config=_snapshot(tenant_id=tenant_id, config_id=config_id, symbol=symbol),
        )
        assert result is not None
        assert result.symbol == symbol


@pytest.mark.asyncio
async def test_propose_proceeds_despite_stale_or_decided_rows(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    """Neither a stale pending row nor a decided row blocks a fresh propose."""
    tenant_id, config_id, symbol = uuid4(), uuid4(), "AAPL"
    service = _build_service(
        _AlwaysProposeStrategy(tenant_id=tenant_id, config_id=config_id, symbol=symbol)
    )
    await _seed_base(sf, tenant_id=tenant_id, config_id=config_id, symbol=symbol)
    async with sf() as session, with_session_context(session, tenant_id):
        await _seed_proposal(
            session,
            tenant_id=tenant_id,
            config_id=config_id,
            symbol=symbol,
            state="pending_approval",
            created_at=datetime.now(UTC) - timedelta(seconds=_DEDUP_WINDOW + 60),
        )
        await _seed_proposal(
            session,
            tenant_id=tenant_id,
            config_id=config_id,
            symbol=symbol,
            state="rejected",
            created_at=datetime.now(UTC),
        )
        result = await service.propose(
            symbol=symbol,
            strategy_config_id=config_id,
            bars=BarHistory(symbol=symbol, bars=()),
            config=_snapshot(tenant_id=tenant_id, config_id=config_id, symbol=symbol),
        )
        assert result is not None
