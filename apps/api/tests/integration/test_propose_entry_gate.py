"""WS-2 entry veto gate wired into ``TradingService.propose``.

The gate is a HARD pre-filter: a ``blocked`` decision drops the entry BEFORE any
``trade_proposals`` row is written and before ``ProposalCreated`` is published —
so no approval card is ever raised. An unblocked decision proceeds to the normal
flow. The gate runs AFTER the cheap dedup guards, so a deduped re-signal never
reaches it (no wasted LLM call). Driven against a real aiosqlite session so the
"no row was written" assertion actually queries the table.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.trading.models import StrategyConfig, Trade, TradeProposal
from iguanatrader.contexts.trading.ports import BarHistory, Proposal, StrategyConfigSnapshot
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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


@pytest.fixture(autouse=True)
def _listeners() -> Iterator[None]:
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    db_path = tmp_path / "ig_entry_gate.db"
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


class _StubBroker:
    """propose() never touches the broker."""


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


class _RecordingGate:
    def __init__(self, *, blocked: bool) -> None:
        self._blocked = blocked
        self.calls: list[dict[str, Any]] = []

    async def evaluate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(blocked=self._blocked, rationale="veto" if self._blocked else "ok")


def _build_service(strategy: _AlwaysProposeStrategy, *, gate: Any) -> TradingService:
    async def _resolve(_sid: UUID) -> _AlwaysProposeStrategy:
        return strategy

    return TradingService(
        bus=MessageBus(),
        broker=_StubBroker(),  # type: ignore[arg-type]
        strategy_resolver=_resolve,
        entry_gate=gate,
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


async def _seed_base(
    sf: async_sessionmaker[AsyncSession], *, tenant_id: UUID, config_id: UUID, symbol: str
) -> None:
    async with sf() as s:
        s.add(Tenant(id=tenant_id, name="t-entry-gate", feature_flags={}))
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


async def _count_proposals(session: AsyncSession, config_id: UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(TradeProposal)
        .where(TradeProposal.strategy_config_id == config_id)
    )
    return int((await session.execute(stmt)).scalar() or 0)


@pytest.mark.asyncio
async def test_blocked_entry_writes_no_proposal_row(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, config_id, symbol = uuid4(), uuid4(), "AMD"
    gate = _RecordingGate(blocked=True)
    service = _build_service(
        _AlwaysProposeStrategy(tenant_id=tenant_id, config_id=config_id, symbol=symbol), gate=gate
    )
    await _seed_base(sf, tenant_id=tenant_id, config_id=config_id, symbol=symbol)
    async with sf() as session, with_session_context(session, tenant_id):
        result = await service.propose(
            symbol=symbol,
            strategy_config_id=config_id,
            bars=BarHistory(symbol=symbol, bars=()),
            config=_snapshot(tenant_id=tenant_id, config_id=config_id, symbol=symbol),
        )
        assert result is None
        # Hard pre-filter: NOTHING persisted.
        assert await _count_proposals(session, config_id) == 0
        # The gate was consulted with the proposal fields.
        assert len(gate.calls) == 1
        assert gate.calls[0]["symbol"] == symbol
        assert gate.calls[0]["side"] == "buy"


@pytest.mark.asyncio
async def test_unblocked_entry_proceeds_and_persists(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, config_id, symbol = uuid4(), uuid4(), "AMD"
    gate = _RecordingGate(blocked=False)
    service = _build_service(
        _AlwaysProposeStrategy(tenant_id=tenant_id, config_id=config_id, symbol=symbol), gate=gate
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
        assert await _count_proposals(session, config_id) == 1
        assert len(gate.calls) == 1


@pytest.mark.asyncio
async def test_gate_not_consulted_when_deduped_by_open_position(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    """Dedup runs BEFORE the gate — a deduped re-signal must not spend an LLM
    call. With an open position, propose short-circuits and the gate is never
    consulted."""
    tenant_id, config_id, symbol = uuid4(), uuid4(), "AMD"
    gate = _RecordingGate(blocked=False)
    service = _build_service(
        _AlwaysProposeStrategy(tenant_id=tenant_id, config_id=config_id, symbol=symbol), gate=gate
    )
    await _seed_base(sf, tenant_id=tenant_id, config_id=config_id, symbol=symbol)
    async with sf() as session, with_session_context(session, tenant_id):
        pid = uuid4()
        session.add(
            TradeProposal(
                id=pid,
                tenant_id=tenant_id,
                strategy_config_id=config_id,
                symbol=symbol,
                side="buy",
                quantity=Decimal("10"),
                entry_price_indicative=Decimal("100"),
                stop_price=Decimal("95"),
                target_price=Decimal("115"),
                confidence_score=Decimal("0.5"),
                reasoning={"why": "seed"},
                mode="paper",
                correlation_id=uuid4(),
                state="approved",
                created_at=datetime.now(UTC),
            )
        )
        await session.flush()
        session.add(
            Trade(
                id=uuid4(),
                tenant_id=tenant_id,
                proposal_id=pid,
                symbol=symbol,
                side="buy",
                quantity=Decimal("10"),
                mode="paper",
                state="open",
                opened_at=datetime.now(UTC),
            )
        )
        await session.flush()

        result = await service.propose(
            symbol=symbol,
            strategy_config_id=config_id,
            bars=BarHistory(symbol=symbol, bars=()),
            config=_snapshot(tenant_id=tenant_id, config_id=config_id, symbol=symbol),
        )
        assert result is None
        assert gate.calls == []  # dedup short-circuited before the gate
