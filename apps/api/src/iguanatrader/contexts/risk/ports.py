"""Hexagonal :class:`Protocol` ports for the risk bounded context.

Per slice K1 design + tasks 2.3: ``RiskService`` depends on a
:class:`RiskRepositoryPort` Protocol — concrete adapter is
:mod:`iguanatrader.contexts.risk.repository`. Tests can inject
fake/in-memory adapters by satisfying the structural typing.

All methods are ``async`` — repository implementations use SQLAlchemy
:class:`AsyncSession` under the hood. The Protocol declares the wire
shape; concrete adapters add session plumbing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from iguanatrader.contexts.risk.models import (
    CapType,
    ConfirmationChain,
    Decision,
    KillSwitchSource,
    RiskState,
)
from iguanatrader.shared.ports import Port


@runtime_checkable
class RiskRepositoryPort(Port, Protocol):
    """Persistence + state-load surface consumed by :class:`RiskService`.

    Method-by-method contract (NOT a place for business rules — those
    live in ``service.py``):

    * :meth:`load_risk_state` — read the current :class:`RiskState` for
      a tenant. Service-layer derives the values from equity snapshots,
      open positions count, day P&L (which live in trading + obs
      tables; for K1 the implementation is allowed to return defaults
      until trading T1 + observability O1 land).
    * :meth:`save_evaluation` — INSERT a row into ``risk_evaluations``;
      returns the new row's id for event publication.
    * :meth:`save_override` — INSERT a row into ``risk_overrides``.
      Service-layer validates the audit fields BEFORE calling this; the
      DB-level CHECK is the second-line safety net.
    * :meth:`load_kill_switch_state` — read the cached
      ``kill_switch_state.is_active`` for the current tenant. NFR-R5
      hot-path read (sub-2s). Returns ``False`` when no row exists for
      the tenant (kill-switch never activated).
    * :meth:`append_kill_switch_event` + :meth:`update_kill_switch_cache`
      — write the event row + same-transaction cache update (per design
      D4). Service-layer wraps both in one ``session.commit()``.
    * :meth:`has_today_automatic_breach_event` — query helper for the
      "first breach of the day" guard in
      :meth:`RiskService._maybe_auto_activate_on_breach`. Returns True
      iff a ``kill_switch_events`` row exists for the current tenant
      with ``transition='activated'`` AND ``source='automatic_cap_breach'``
      AND ``DATE(created_at) == DATE(now)``.
    """

    async def load_risk_state(self, tenant_id: UUID) -> RiskState: ...

    async def save_evaluation(
        self,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
        decision: Decision,
        created_at: datetime,
    ) -> UUID: ...

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
    ) -> UUID: ...

    async def load_kill_switch_state(self, tenant_id: UUID) -> bool: ...

    async def append_kill_switch_event(
        self,
        *,
        tenant_id: UUID,
        transition: str,
        source: KillSwitchSource,
        actor_user_id: UUID | None,
        reason: str | None,
        created_at: datetime,
    ) -> UUID: ...

    async def update_kill_switch_cache(
        self,
        *,
        tenant_id: UUID,
        is_active: bool,
        last_event_id: UUID,
        updated_at: datetime,
    ) -> None: ...

    async def has_today_automatic_breach_event(
        self,
        tenant_id: UUID,
        today_utc: datetime,
        cap_type: CapType,
    ) -> bool: ...


__all__ = ["RiskRepositoryPort"]
