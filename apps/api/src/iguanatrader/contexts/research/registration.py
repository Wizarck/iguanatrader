"""Symbol registration helper — shared by CLI admin + ad-hoc research refresh.

Slice ``research-ad-hoc-mode`` (2026-05-18) extracts the
``symbol_universe`` + ``watchlist_configs`` insertion logic out of
:mod:`iguanatrader.cli.admin` so the brief-refresh route can register
a symbol on-the-fly the first time the operator researches it.

Mental model: the universe is a TRACKING commitment registry, not a
permission gate. The default created by :func:`ensure_symbol_registered`
uses ``brief_refresh_schedule='manual'`` — nothing is auto-refreshed
until the operator opts in by creating a strategy_config.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.contexts.research.models import SymbolUniverse, WatchlistConfig

#: Default tier for ad-hoc / research-only registrations. ``primary``
#: keeps the symbol visible in the strategies "All symbols" pickers
#: without changing schedule semantics — the actual scheduling gate is
#: ``brief_refresh_schedule`` + the presence of a strategy_config.
DEFAULT_TIER = "primary"
DEFAULT_METHODOLOGY = "three_pillar"
DEFAULT_EXCHANGE = "NASDAQ"
#: ``manual`` schedule keeps the symbol OUT of any future auto-refresh
#: cron — the operator must hit the "Refresh brief" button explicitly.
#: Promotion to ``daily`` / ``weekly`` happens when a strategy is added
#: (slice ``research-ad-hoc-mode-strategy-promotion``, follow-up PR).
DEFAULT_SCHEDULE = "manual"


@dataclass(frozen=True, slots=True)
class RegistrationOutcome:
    """Result of :func:`ensure_symbol_registered`.

    ``created`` distinguishes the first-time path (rows inserted, caller
    may want to kick off live source ingestion) from the idempotent
    path (symbol already known, just return its ids).
    """

    symbol_universe_id: UUID
    watchlist_config_id: UUID
    created: bool


async def ensure_symbol_registered(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    symbol: str,
    exchange: str = DEFAULT_EXCHANGE,
    tier: str = DEFAULT_TIER,
    methodology: str = DEFAULT_METHODOLOGY,
    schedule: str = DEFAULT_SCHEDULE,
) -> RegistrationOutcome:
    """Return ids for ``(tenant, symbol)`` — creating the rows if missing.

    Idempotent: a second call for the same ``(tenant, symbol)`` returns
    the existing row ids with ``created=False`` and does not write.
    A race between two concurrent first-time calls is handled by
    catching the unique-constraint :class:`IntegrityError` and falling
    back to a re-select.

    The caller is responsible for setting the tenant context (via
    :func:`iguanatrader.shared.contextvars.with_tenant_context`) so the
    SELECT clauses pick up the tenant predicate and the INSERTs satisfy
    the append-only listener's tenant-stamp.
    """
    existing = await _select_ids(session, tenant_id=tenant_id, symbol=symbol)
    if existing is not None:
        return RegistrationOutcome(
            symbol_universe_id=existing[0],
            watchlist_config_id=existing[1],
            created=False,
        )

    symbol_universe_id = uuid4()
    watchlist_config_id = uuid4()
    try:
        # #23: wrap the INSERTs in a SAVEPOINT so a lost race rolls back
        # ONLY these two rows. The previous ``session.rollback()`` rolled
        # back the WHOLE shared transaction — discarding any other pending
        # work in the daemon's long-lived session (the #29 hazard). This
        # mirrors ``OnDemandIngestionService._persist``.
        async with session.begin_nested():
            session.add(
                SymbolUniverse(
                    id=symbol_universe_id,
                    tenant_id=tenant_id,
                    symbol=symbol,
                    exchange=exchange,
                )
            )
            session.add(
                WatchlistConfig(
                    id=watchlist_config_id,
                    tenant_id=tenant_id,
                    symbol_universe_id=symbol_universe_id,
                    tier=tier,
                    methodology=methodology,
                    brief_refresh_schedule=schedule,
                )
            )
            await session.flush()
    except IntegrityError:
        # Concurrent first-time call won the race — the SAVEPOINT already
        # rolled our INSERTs back; read the winner's ids.
        existing = await _select_ids(session, tenant_id=tenant_id, symbol=symbol)
        if existing is None:
            raise
        return RegistrationOutcome(
            symbol_universe_id=existing[0],
            watchlist_config_id=existing[1],
            created=False,
        )

    return RegistrationOutcome(
        symbol_universe_id=symbol_universe_id,
        watchlist_config_id=watchlist_config_id,
        created=True,
    )


async def _select_ids(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    symbol: str,
) -> tuple[UUID, UUID] | None:
    stmt = (
        sa.select(SymbolUniverse.id, WatchlistConfig.id)
        .join(
            WatchlistConfig,
            WatchlistConfig.symbol_universe_id == SymbolUniverse.id,
        )
        .where(
            SymbolUniverse.tenant_id == tenant_id,
            SymbolUniverse.symbol == symbol,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.first()
    if row is None:
        return None
    return row[0], row[1]


__all__ = [
    "DEFAULT_EXCHANGE",
    "DEFAULT_METHODOLOGY",
    "DEFAULT_SCHEDULE",
    "DEFAULT_TIER",
    "RegistrationOutcome",
    "ensure_symbol_registered",
]
