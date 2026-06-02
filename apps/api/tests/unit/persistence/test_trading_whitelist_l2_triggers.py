"""#35: whitelist-aware L2 triggers on the column-whitelisted trading tables.

``trades`` / ``orders`` / ``trade_proposals`` undergo legitimate,
whitelist-restricted UPDATEs (state transitions). The L2 trigger must mirror
the L1 ``before_flush`` listener: block a raw (out-of-ORM) UPDATE that touches
a NON-whitelisted column, ALLOW one that touches only whitelisted columns, and
block every DELETE.

``Base.metadata.create_all`` does not model triggers, so the test re-emits the
SQLite trigger DDL exactly as migration 0035 does (mirrors the #26 test).

The final test is the lockstep guard: it asserts the migration's static column
snapshot still equals ``ORM columns - whitelist`` for each table, so a future
column addition that forgets a follow-up trigger migration fails CI.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from iguanatrader.contexts.trading.models import (
    Order,
    StrategyConfig,
    Trade,
    TradeProposal,
)
from iguanatrader.migrations._trading_whitelist_trigger_helpers import (
    MUTABLE_COLUMNS,
    NON_WHITELISTED_COLUMNS,
    SQLITE_TRADING_WHITELIST_TRIGGER_SQL,
    WHITELISTED_TRADING_TABLES,
)
from iguanatrader.persistence import (
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import session_var, with_tenant_context
from iguanatrader.shared.time import now as utc_now
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
    eng = engine_factory(f"sqlite+aiosqlite:///{(tmp_path / 'l2wl.db').as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for sql in SQLITE_TRADING_WHITELIST_TRIGGER_SQL:
            await conn.execute(sa.text(sql))
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def sf(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return session_factory(engine)


async def _seed_chain(
    sf: async_sessionmaker[AsyncSession], tid: UUID
) -> tuple[UUID, UUID, UUID, UUID]:
    """Seed tenant → strategy_config → proposal → trade → order."""
    sc_id, pid, trid, oid = uuid4(), uuid4(), uuid4(), uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name="t", feature_flags={}))
        await s.commit()
    async with with_tenant_context(tid), sf() as s:
        s.add(
            StrategyConfig(
                id=sc_id,
                tenant_id=tid,
                strategy_kind="donchian_atr",
                symbol="SPY",
                params={},
                enabled=True,
            )
        )
        await s.commit()
    async with with_tenant_context(tid), sf() as s:
        s.add(
            TradeProposal(
                id=pid,
                tenant_id=tid,
                strategy_config_id=sc_id,
                correlation_id=uuid4(),
                symbol="SPY",
                side="buy",
                quantity=Decimal("10"),
                entry_price_indicative=Decimal("100"),
                stop_price=Decimal("90"),
                reasoning={},
                mode="paper",
            )
        )
        await s.commit()
    async with with_tenant_context(tid), sf() as s:
        s.add(
            Trade(
                id=trid,
                tenant_id=tid,
                proposal_id=pid,
                symbol="SPY",
                side="buy",
                quantity=Decimal("10"),
                mode="paper",
                state="open",
                opened_at=utc_now(),
            )
        )
        await s.commit()
    async with with_tenant_context(tid), sf() as s:
        s.add(
            Order(
                id=oid,
                tenant_id=tid,
                trade_id=trid,
                broker="ibkr",
                broker_order_id="BR-1",
                order_type="market",
                side="buy",
                quantity=Decimal("10"),
                state="submitted",
                target_price=Decimal("120"),
                client_order_id=uuid4(),
            )
        )
        await s.commit()
    return sc_id, pid, trid, oid


# (table, a NON-whitelisted column to mutate, a NEW value, a whitelisted UPDATE)
_BLOCK_ALLOW = [
    (
        "trade_proposals",
        "UPDATE trade_proposals SET quantity = 1",
        "UPDATE trade_proposals SET state = 'approved'",
    ),
    ("trades", "UPDATE trades SET symbol = 'TSLA'", "UPDATE trades SET state = 'closing'"),
    ("orders", "UPDATE orders SET quantity = 1", "UPDATE orders SET state = 'filled'"),
]


@pytest.mark.parametrize("table,blocked_sql,allowed_sql", _BLOCK_ALLOW)
@pytest.mark.asyncio
async def test_raw_update_nonwhitelisted_blocked_whitelisted_allowed(
    sf: async_sessionmaker[AsyncSession],
    table: str,
    blocked_sql: str,
    allowed_sql: str,
) -> None:
    tid = uuid4()
    await _seed_chain(sf, tid)
    # A non-whitelisted column change is refused at the DB level.
    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        with pytest.raises(Exception, match="append-only"):
            await session.execute(sa.text(blocked_sql))
    # A whitelisted-only change goes through (mirrors L1 permitting it).
    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        await session.execute(sa.text(allowed_sql))
        await session.commit()


@pytest.mark.parametrize("table", WHITELISTED_TRADING_TABLES)
@pytest.mark.asyncio
async def test_raw_delete_blocked(
    sf: async_sessionmaker[AsyncSession],
    table: str,
) -> None:
    tid = uuid4()
    await _seed_chain(sf, tid)
    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        with pytest.raises(Exception, match="append-only"):
            await session.execute(sa.text(f"DELETE FROM {table}"))


@pytest.mark.parametrize("column", ["target_price", "client_order_id"])
@pytest.mark.asyncio
async def test_orders_new_immutable_columns_are_protected(
    sf: async_sessionmaker[AsyncSession],
    column: str,
) -> None:
    """#6/#7 added ``target_price`` + ``client_order_id`` to ``orders``; both are
    immutable and must be covered by the L2 trigger."""
    tid = uuid4()
    await _seed_chain(sf, tid)
    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        with pytest.raises(Exception, match="append-only"):
            await session.execute(sa.text(f"UPDATE orders SET {column} = NULL"))


def test_snapshot_in_lockstep_with_orm() -> None:
    """The migration's static column snapshot must equal ``ORM columns -
    whitelist`` for each table — otherwise a new column ships immutable-by-
    intent but unprotected by any trigger."""
    models = {
        "trades": Trade,
        "orders": Order,
        "trade_proposals": TradeProposal,
    }
    for table in WHITELISTED_TRADING_TABLES:
        model = models[table]
        all_cols = set(model.__table__.columns.keys())
        whitelist = set(model.__append_only_mutable_columns__)  # type: ignore[attr-defined]
        assert (
            set(MUTABLE_COLUMNS[table]) == whitelist
        ), f"{table}: MUTABLE_COLUMNS snapshot drifted from the ORM whitelist"
        assert set(NON_WHITELISTED_COLUMNS[table]) == (all_cols - whitelist), (
            f"{table}: NON_WHITELISTED_COLUMNS snapshot drifted from ORM "
            f"(columns - whitelist); add a follow-up trigger migration"
        )
