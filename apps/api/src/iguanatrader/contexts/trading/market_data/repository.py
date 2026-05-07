"""Repository for ``market_data_sync_audit`` (slice T4-followup-market-data §2.8).

The audit table is the single source of truth for rate-limiting:
:class:`MarketDataIngestionService` queries
:meth:`count_invocations_since` before each call; if the count exceeds
``IGUANATRADER_MARKET_DATA_MAX_INVOCATIONS_PER_HOUR`` the service
refuses (still writing a ``status='rate_limited'`` row so ops dashboards
see the spam).

Append-only enforcement: :class:`MarketDataSyncAudit` declares
``__tablename_is_append_only__ = True`` so any UPDATE/DELETE attempt
raises :class:`AppendOnlyViolation` at flush time (slice 3 listener).
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select

from iguanatrader.contexts.trading.market_data.models import MarketDataSyncAudit
from iguanatrader.shared.contextvars import tenant_id_var
from iguanatrader.shared.kernel import BaseRepository
from iguanatrader.shared.time import now as utc_now


class MarketDataSyncAuditRepository(BaseRepository):
    """INSERT + COUNT-only access to ``market_data_sync_audit``."""

    async def count_invocations_since(self, *, since: datetime) -> int:
        """Count audit rows ``invoked_at >= since`` for the current tenant.

        Used by the rate-limit guard. Tenant scoping is automatic via
        the slice-3 ``tenant_listener``.
        """
        stmt = (
            select(func.count())
            .select_from(MarketDataSyncAudit)
            .where(MarketDataSyncAudit.invoked_at >= since)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def write_audit_row(
        self,
        *,
        invoked_by: str,
        symbols: list[str],
        timeframe: str,
        lookback_bars: int,
        status: str,
        bars_written: int = 0,
        duration_ms: int = 0,
        error: str | None = None,
    ) -> MarketDataSyncAudit:
        """INSERT a new audit row (append-only)."""
        tenant_id = tenant_id_var.get()
        if tenant_id is None:
            raise LookupError(
                "tenant_id_var must be set before write_audit_row; "
                "call from a request scope or with_tenant_context()."
            )
        row = MarketDataSyncAudit(
            id=uuid4(),
            tenant_id=tenant_id,
            invoked_at=utc_now(),
            invoked_by=invoked_by,
            symbols=list(symbols),
            timeframe=timeframe,
            lookback_bars=lookback_bars,
            status=status,
            bars_written=bars_written,
            duration_ms=duration_ms,
            error=error,
        )
        self.session.add(row)
        await self.session.flush()
        return row


__all__ = ["MarketDataSyncAuditRepository"]
