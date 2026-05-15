"""SQLAlchemy adapter implementing :class:`RiskRepositoryPort`.

Per slice K1 design + tasks 4.1: thin wrapper around an
:class:`AsyncSession` (the FastAPI request-scoped session — slice 5
will move it under ``session_var`` once that lands as a SQLAlchemy
type). Tenant scoping is handled by the slice-3 ``tenant_listener`` —
this repository does NOT manually filter by tenant_id; it relies on
the global listener that reads
:data:`iguanatrader.shared.contextvars.tenant_id_var`.

All write operations are append-only EXCEPT
:meth:`update_kill_switch_cache` which UPDATEs the single
``kill_switch_state`` row (kill-switch cache is the explicit exception
to the global append-only invariant — see slice K1 design D4).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.contexts.risk.models import (
    CapType,
    ConfirmationChain,
    Decision,
    KillSwitchSource,
    RiskState,
)
from iguanatrader.contexts.risk.orm import (
    KillSwitchEventORM,
    KillSwitchStateORM,
    RiskEvaluationORM,
    RiskOverrideORM,
)
from iguanatrader.contexts.risk.ports import RiskRepositoryPort
from iguanatrader.contexts.trading.models import EquitySnapshot, Trade
from iguanatrader.shared.time import now as utc_now

#: Fallback capital when ``equity_snapshots`` is empty (early tenant,
#: equity-snapshot daemon not yet writing rows). Matches the
#: ``DEFAULT_EQUITY`` constant used by strategy modules so percentage
#: caps render the same units across the system. The risk engine
#: degrades cleanly under this fallback: drawdown stays 0 (peak ==
#: latest both None), daily/weekly loss percentages divide by the
#: fallback so they remain meaningful even without snapshots.
_FALLBACK_CAPITAL: Decimal = Decimal("10000")

#: Trailing-window denominator the stoploss-guard reports through
#: :attr:`RiskState.recent_trades_lookback`. Mirrors
#: :attr:`RiskCaps.stoploss_guard_lookback` field default (5). Read
#: here rather than imported from RiskCaps to keep the repository
#: independent from the cap-loading path (env var overrides happen at
#: the service layer; this query needs a stable lookback for the SQL
#: ``LIMIT`` clause).
_STOPLOSS_GUARD_LOOKBACK: int = 5


class RiskRepository(RiskRepositoryPort):
    """Concrete SQLAlchemy adapter for the risk persistence surface."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_risk_state(self, tenant_id: UUID) -> RiskState:
        """Compose a :class:`RiskState` from real trades + equity snapshots.

        Per slice ``wire-risk-state-real-data`` proposal: fans out 6
        scoped reads (open count, latest+peak equity, day P&L, week
        P&L, stoploss-guard tally + lookback, per-symbol seconds-since-
        last-close), assembles into a frozen :class:`RiskState`, and
        returns. Each helper is a single SELECT; all are tenant-scoped
        by the slice-3 ``tenant_listener`` via
        :data:`tenant_id_var` (the explicit ``tenant_id`` arg is
        accepted for Protocol conformance and reserved for future
        defence-in-depth filtering).

        Degradation modes:

        * No ``equity_snapshots`` rows → ``capital`` falls back to
          :data:`_FALLBACK_CAPITAL`; drawdown stays ``Decimal("0")``.
          The equity-snapshot daemon ships separately; until then the
          state still populates correctly from trades alone.
        * No closed trades → all P&L sums coalesce to ``0``; the
          stoploss-guard count and the per-symbol seconds dict are
          both empty. Engine sees a neutral baseline.
        * ``realised_pnl IS NULL`` on a closed row → the row is
          excluded from the P&L sum (legacy trades closed before
          slice ``trades-add-exit-and-realised-pnl-columns`` shipped
          have NULL here). Same NULL-tolerance for ``exit_reason``
          in the stoploss-guard tally.
        """
        now = utc_now()
        today_utc = now.date()
        week_start_date = today_utc - timedelta(days=today_utc.weekday())
        day_start = datetime.combine(today_utc, time.min, tzinfo=UTC)
        week_start = datetime.combine(week_start_date, time.min, tzinfo=UTC)

        open_count = await self._count_open_trades()
        latest_equity = await self._load_latest_equity()
        peak_equity = await self._load_peak_equity()

        capital = latest_equity if latest_equity is not None else _FALLBACK_CAPITAL
        if (
            peak_equity is not None
            and peak_equity > 0
            and latest_equity is not None
            and peak_equity > latest_equity
        ):
            drawdown_pct = (peak_equity - latest_equity) / peak_equity
        else:
            drawdown_pct = Decimal("0")

        day_pnl = await self._sum_realised_pnl_since(day_start)
        week_pnl = await self._sum_realised_pnl_since(week_start)
        day_loss_pct = max(Decimal("0"), -day_pnl / capital) if capital > 0 else Decimal("0")
        week_loss_pct = max(Decimal("0"), -week_pnl / capital) if capital > 0 else Decimal("0")

        recent_stop_count, recent_count = await self._count_recent_stoplosses(
            _STOPLOSS_GUARD_LOOKBACK,
        )
        seconds_since = await self._seconds_since_last_close_by_symbol(now)

        return RiskState(
            capital=capital,
            day_to_date_loss_pct=day_loss_pct,
            week_to_date_loss_pct=week_loss_pct,
            open_positions_count=open_count,
            peak_to_trough_drawdown_pct=drawdown_pct,
            recent_stoploss_count_trailing=recent_stop_count,
            recent_trades_lookback=recent_count,
            seconds_since_last_close_by_symbol=seconds_since,
        )

    async def _count_open_trades(self) -> int:
        """Count rows in ``trades`` whose ``state`` indicates a live position.

        Per slice ``trade-state-machine-redesign`` the canonical "live"
        states are ``'open'`` (entry submitted / filled, no exit yet)
        and ``'closing'`` (exit order submitted, position still open
        at the broker). Both consume a position slot for the ``max_open``
        cap; ``'closed'`` does not.

        Tenant-scoped by the global ``tenant_listener``. Returns 0 when
        the table is empty.
        """
        stmt = select(func.count()).select_from(Trade).where(Trade.state.in_(("open", "closing")))
        result = await self._session.execute(stmt)
        value = result.scalar_one_or_none()
        return int(value) if value is not None else 0

    async def _load_latest_equity(self) -> Decimal | None:
        """Latest ``account_equity`` ordered by ``created_at DESC``.

        Returns ``None`` when ``equity_snapshots`` is empty for the
        current tenant — caller falls back to :data:`_FALLBACK_CAPITAL`.
        """
        stmt = (
            select(EquitySnapshot.account_equity)
            .order_by(EquitySnapshot.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        value = result.scalar_one_or_none()
        return Decimal(str(value)) if value is not None else None

    async def _load_peak_equity(self) -> Decimal | None:
        """``MAX(account_equity)`` across the tenant's history.

        Returns ``None`` when the table is empty. Drawdown computation
        caller treats ``None`` as "no peak yet" → ``drawdown_pct = 0``.
        """
        stmt = select(func.max(EquitySnapshot.account_equity))
        result = await self._session.execute(stmt)
        value = result.scalar_one_or_none()
        return Decimal(str(value)) if value is not None else None

    async def _sum_realised_pnl_since(self, since: datetime) -> Decimal:
        """``SUM(realised_pnl)`` over trades closed at-or-after ``since``.

        Filters:

        * ``state == 'closed'`` — terminal state per slice
          ``trade-state-machine-redesign``. ``open`` and ``closing``
          trades have not yet realised their P&L. (Pre-slice the
          condition was ``state != 'open'`` which incorrectly included
          partial / closing states.)
        * ``closed_at >= since``.
        * ``realised_pnl IS NOT NULL`` — legacy rows from before the
          column shipped (slice 0015) are excluded.

        Returns ``Decimal("0")`` when no rows match (``COALESCE`` at
        the SQL level keeps the type as Decimal).
        """
        stmt = select(func.coalesce(func.sum(Trade.realised_pnl), 0)).where(
            Trade.state == "closed",
            Trade.closed_at.is_not(None),
            Trade.closed_at >= since,
            Trade.realised_pnl.is_not(None),
        )
        result = await self._session.execute(stmt)
        value = result.scalar_one()
        return Decimal(str(value)) if value is not None else Decimal("0")

    async def _count_recent_stoplosses(self, lookback: int) -> tuple[int, int]:
        """Tally ``exit_reason == 'stop'`` over the trailing ``lookback`` closed trades.

        Returns ``(stop_count, rows_returned)`` so the caller can
        populate both :attr:`RiskState.recent_stoploss_count_trailing`
        and :attr:`RiskState.recent_trades_lookback` (the actual
        denominator used — may be less than ``lookback`` when fewer
        closed trades exist).
        """
        stmt = (
            select(Trade.exit_reason)
            .where(
                Trade.state == "closed",
                Trade.closed_at.is_not(None),
            )
            .order_by(Trade.closed_at.desc())
            .limit(lookback)
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        stop_count = sum(1 for reason in rows if reason == "stop")
        return stop_count, len(rows)

    async def _seconds_since_last_close_by_symbol(
        self,
        now: datetime,
    ) -> dict[str, int]:
        """Per-symbol integer seconds since the most-recent close.

        Symbols with no closed trade are absent from the dict (the
        cooldown protection treats absence as "no cooldown applies").
        """
        stmt = (
            select(Trade.symbol, func.max(Trade.closed_at))
            .where(
                Trade.state == "closed",
                Trade.closed_at.is_not(None),
            )
            .group_by(Trade.symbol)
        )
        result = await self._session.execute(stmt)
        out: dict[str, int] = {}
        for symbol, last_close in result.all():
            if last_close is None:
                continue
            # Defensive: SQLite returns naive datetimes; coerce to UTC
            # so the subtraction is sane. Trades insert via the ORM
            # with timezone-aware values, but raw-SQL test seeds may
            # not, so guard explicitly.
            if last_close.tzinfo is None:
                last_close = last_close.replace(tzinfo=UTC)
            delta = now - last_close
            seconds = int(delta.total_seconds())
            if seconds < 0:
                seconds = 0
            out[str(symbol)] = seconds
        return out

    async def save_evaluation(
        self,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        decision: Decision,
        created_at: datetime,
    ) -> UUID:
        """INSERT a row into ``risk_evaluations``; return the new id."""
        eval_id = uuid.uuid4()
        row = RiskEvaluationORM(
            id=eval_id,
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            outcome=decision.outcome,
            cap_type_breached=decision.cap_type_breached,
            current_pct=decision.current_pct,
            state_snapshot=dict(decision.state_snapshot),
            clip_quantity=decision.clip_quantity,
            created_at=created_at,
        )
        self._session.add(row)
        await self._session.flush()
        return eval_id

    async def save_override(
        self,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        risk_evaluation_id: UUID,
        authorised_by_user_id: UUID,
        reason_text: str,
        confirmation_chain: ConfirmationChain,
        state_snapshot_at_override: dict[str, Any],
        created_at: datetime,
    ) -> UUID:
        """INSERT a row into ``risk_overrides``; return the new id."""
        override_id = uuid.uuid4()
        row = RiskOverrideORM(
            id=override_id,
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            risk_evaluation_id=risk_evaluation_id,
            authorised_by_user_id=authorised_by_user_id,
            reason_text=reason_text,
            confirmation_chain=confirmation_chain.model_dump(mode="json"),
            state_snapshot_at_override=state_snapshot_at_override,
            created_at=created_at,
        )
        self._session.add(row)
        await self._session.flush()
        return override_id

    async def load_kill_switch_state(self, tenant_id: UUID) -> bool:
        """Return ``True`` iff the cached ``is_active`` row says so.

        Single-row indexed lookup — sub-millisecond on SQLite, ditto
        on PostgreSQL. This is the NFR-R5 hot-path read.
        """
        stmt = select(KillSwitchStateORM.is_active).where(
            KillSwitchStateORM.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        value = result.scalar_one_or_none()
        return bool(value) if value is not None else False

    async def append_kill_switch_event(
        self,
        *,
        tenant_id: UUID,
        transition: str,
        source: KillSwitchSource,
        actor_user_id: UUID | None,
        reason: str | None,
        created_at: datetime,
    ) -> UUID:
        """INSERT a row into ``kill_switch_events``; return the new id."""
        event_id = uuid.uuid4()
        row = KillSwitchEventORM(
            id=event_id,
            tenant_id=tenant_id,
            transition=transition,
            source=source,
            actor_user_id=actor_user_id,
            reason=reason,
            created_at=created_at,
        )
        self._session.add(row)
        await self._session.flush()
        return event_id

    async def update_kill_switch_cache(
        self,
        *,
        tenant_id: UUID,
        is_active: bool,
        last_event_id: UUID,
        updated_at: datetime,
    ) -> None:
        """Upsert the single cache row for ``tenant_id``.

        Uses SQLite's ``INSERT … ON CONFLICT DO UPDATE`` (Postgres has
        the same syntax). The ``kill_switch_state`` table is NOT
        flagged ``__tablename_is_append_only__``; UPDATE is permitted.

        On Postgres deployments (post-MVP) the same statement is
        valid — :func:`sqlalchemy.dialects.sqlite.insert` is the most
        portable form for the on_conflict_do_update pattern; the
        equivalent ``sqlalchemy.dialects.postgresql.insert`` lands as
        a follow-up when the engine is detected at boot.
        """
        stmt = sqlite_insert(KillSwitchStateORM).values(
            tenant_id=tenant_id,
            is_active=is_active,
            last_event_id=last_event_id,
            updated_at=updated_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id"],
            set_={
                "is_active": is_active,
                "last_event_id": last_event_id,
                "updated_at": updated_at,
            },
        )
        await self._session.execute(stmt)

    async def has_today_automatic_breach_event(
        self,
        tenant_id: UUID,
        today_utc: datetime,
        cap_type: CapType,
    ) -> bool:
        """True iff an ``automatic_cap_breach`` activation row exists for today.

        Used by the service-layer's first-breach-of-the-day guard so
        the kill-switch is auto-activated AT MOST once per day per
        tenant. ``cap_type`` is currently unused at the SQL level
        (we activate once per day across any cap type) but kept in
        the signature for forward-compat: a future refinement could
        scope to "first daily breach", "first weekly breach", etc.

        The ``DATE()`` SQL function works on both SQLite (DATE() built-
        in) and PostgreSQL.
        """
        # Cap type is reserved for future per-cap-type day buckets;
        # silence ruff about the unused arg without changing the API.
        _ = cap_type
        stmt = (
            select(func.count())
            .select_from(KillSwitchEventORM)
            .where(
                KillSwitchEventORM.tenant_id == tenant_id,
                KillSwitchEventORM.transition == "activated",
                KillSwitchEventORM.source == "automatic_cap_breach",
                func.date(KillSwitchEventORM.created_at) == func.date(today_utc),
            )
        )
        result = await self._session.execute(stmt)
        count = result.scalar_one()
        return bool(count and int(count) > 0)


# ---------------------------------------------------------------------------
# Helpers for service-layer commit sequencing.
# ---------------------------------------------------------------------------


async def commit_session(session: AsyncSession) -> None:
    """Wrapper for ``await session.commit()``.

    Kept here so the service layer's "two-write transaction" guarantee
    (per design D4) is grep-able from a single module. Repositories
    don't normally call commit themselves — the FastAPI ``get_db``
    dependency yields a session whose lifecycle is managed by the
    request scope; the service flushes + commits explicitly when it
    needs cross-table atomicity.
    """
    await session.commit()


async def execute_raw_sql(session: AsyncSession, sql: str) -> Any:
    """Escape hatch for tests that want to inspect rows via raw SQL.

    Not used by the service layer in production code paths.
    """
    return await session.execute(text(sql))


__all__ = ["RiskRepository", "commit_session", "execute_raw_sql"]
