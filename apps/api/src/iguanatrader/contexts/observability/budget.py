"""Per-tenant monthly budget gate — WARN_80 + BLOCK_100 (FR41).

Per design D4: a single chokepoint inside
:func:`iguanatrader.contexts.observability.llm_routing.route_llm`
queries spend-to-date for the current month and compares against the
per-tenant cap (``tenants.feature_flags["llm_budget_usd"]``, default
$50/month).

States:

- ``OK`` (0-79%) — proceed normally.
- ``WARN_80`` (80-99%) — emit ``observability.budget.warning_threshold``
  exactly once per tenant per month; ``route_llm()`` auto-downgrades
  sonnet → haiku at the next routing decision.
- ``BLOCK_100`` (100%+) — ``route_llm()`` raises
  :class:`BudgetExceededError` (RFC 7807 status 402).

The "exactly once" semantics for WARN_80 is enforced in-process via the
:data:`_warn_seen` cache keyed by ``(tenant_id, year, month)``. Multi-
process deployments would re-emit per worker; this MVP is single-process
(see Risks section in design.md).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import cast
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.contexts.observability.repository import ApiCostEventRepository
from iguanatrader.persistence.models import Tenant
from iguanatrader.shared.contextvars import session_var
from iguanatrader.shared.time import UTC, now

log = structlog.get_logger("iguanatrader.contexts.observability.budget")


class BudgetStatus(StrEnum):
    """Three-tier budget gate state (per design D4)."""

    OK = "OK"
    WARN_80 = "WARN_80"
    BLOCK_100 = "BLOCK_100"


class BudgetState(BaseModel):
    """Snapshot of a tenant's budget posture at a point in time.

    Decimals are serialised as strings by Pydantic v2 by default; we
    keep the in-process representation as :class:`Decimal` to avoid
    floating-point drift in the gate arithmetic.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    tenant_id: UUID
    status: BudgetStatus
    percent_used: int = Field(ge=0)
    spent_usd: Decimal
    cap_usd: Decimal
    remaining_usd: Decimal


#: Default monthly cap when ``tenants.feature_flags["llm_budget_usd"]``
#: is missing (per Open Question Q3 in design.md).
DEFAULT_MONTHLY_CAP_USD: Decimal = Decimal("50.00")

#: Process-local set of ``(tenant_id, year, month)`` tuples that have
#: already emitted the WARN_80 event. Cleared by tests via
#: :func:`reset_warn_cache_for_tests`.
_warn_seen: set[tuple[UUID, int, int]] = set()


def _start_of_month_utc(at: datetime) -> datetime:
    """Return the UTC midnight of the first day of ``at``'s month."""
    return datetime(at.year, at.month, 1, tzinfo=UTC)


def _end_of_month_utc(at: datetime) -> datetime:
    """Return the UTC midnight of the first day of ``at``'s next month."""
    if at.month == 12:
        return datetime(at.year + 1, 1, 1, tzinfo=UTC)
    return datetime(at.year, at.month + 1, 1, tzinfo=UTC)


def reset_warn_cache_for_tests() -> None:
    """Clear the in-process WARN_80 dedup cache. Test-only helper."""
    _warn_seen.clear()


async def _read_cap_for_tenant(tenant_id: UUID) -> Decimal:
    """Resolve the monthly USD cap for ``tenant_id``.

    Reads ``tenants.feature_flags["llm_budget_usd"]``; falls back to
    :data:`DEFAULT_MONTHLY_CAP_USD` when the flag is missing or
    non-numeric. The :class:`Tenant` mapping is non-tenant-scoped so
    the slice-3 listener does not require a ``tenant_id_var``.
    """
    sess = session_var.get()
    if sess is None:
        return DEFAULT_MONTHLY_CAP_USD
    session = cast(AsyncSession, sess)
    stmt = select(Tenant).where(Tenant.id == tenant_id)
    result = await session.execute(stmt)
    tenant = result.scalar_one_or_none()
    if tenant is None:
        return DEFAULT_MONTHLY_CAP_USD
    raw = tenant.feature_flags.get("llm_budget_usd") if tenant.feature_flags else None
    if raw is None:
        return DEFAULT_MONTHLY_CAP_USD
    try:
        return Decimal(str(raw))
    except (ValueError, ArithmeticError):
        return DEFAULT_MONTHLY_CAP_USD


async def check_budget(
    tenant_id: UUID,
    *,
    at: datetime | None = None,
) -> BudgetState:
    """Compute the current :class:`BudgetState` for ``tenant_id``.

    Aggregates ``SUM(cost_usd)`` over ``api_cost_events`` for the
    current calendar month (UTC) and classifies into one of the three
    :class:`BudgetStatus` tiers.

    Side effect: when the resulting status is ``WARN_80`` and the
    ``(tenant_id, year, month)`` tuple has not yet been seen this month,
    emits structlog ``observability.budget.warning_threshold`` and
    records the tuple in :data:`_warn_seen` so subsequent calls in the
    same month do not re-emit.
    """
    when = at or now()
    period_start = _start_of_month_utc(when)
    period_end = _end_of_month_utc(when)

    repo = ApiCostEventRepository()
    spent = await repo.sum_cost_for_tenant_in_period(
        tenant_id=tenant_id,
        start=period_start,
        end=period_end,
    )
    cap = await _read_cap_for_tenant(tenant_id)
    if cap <= 0:
        # Defensive: a zero / negative cap is treated as immediately
        # blocked, not silent OK. Operators raise the cap to unblock.
        cap = DEFAULT_MONTHLY_CAP_USD

    percent = int((spent / cap) * 100) if cap > 0 else 100

    if percent >= 100:
        status = BudgetStatus.BLOCK_100
    elif percent >= 80:
        status = BudgetStatus.WARN_80
    else:
        status = BudgetStatus.OK

    if status is BudgetStatus.WARN_80:
        key = (tenant_id, when.year, when.month)
        if key not in _warn_seen:
            _warn_seen.add(key)
            log.info(
                "observability.budget.warning_threshold",
                tenant_id=str(tenant_id),
                percent_used=percent,
                spent_usd=str(spent),
                cap_usd=str(cap),
            )

    remaining = cap - spent
    if remaining < 0:
        remaining = Decimal("0")

    return BudgetState(
        tenant_id=tenant_id,
        status=status,
        percent_used=percent,
        spent_usd=spent,
        cap_usd=cap,
        remaining_usd=remaining,
    )


def month_window(at: datetime | None = None) -> tuple[datetime, datetime]:
    """Return the ``[start, end)`` UTC window for the calendar month of ``at``."""
    when = at or now()
    return _start_of_month_utc(when), _end_of_month_utc(when)


def previous_month_window(at: datetime | None = None) -> tuple[datetime, datetime]:
    """Return ``[start, end)`` UTC for the calendar month BEFORE ``at``."""
    when = at or now()
    start_this = _start_of_month_utc(when)
    end = start_this
    # Step into previous month by subtracting one day from start_this and
    # snapping back to month start.
    in_prev = start_this - timedelta(days=1)
    start = _start_of_month_utc(in_prev)
    return start, end


__all__ = [
    "DEFAULT_MONTHLY_CAP_USD",
    "BudgetState",
    "BudgetStatus",
    "check_budget",
    "month_window",
    "previous_month_window",
    "reset_warn_cache_for_tests",
]
