"""Risk routes — ``GET /risk/state``, ``POST /risk/override``.

The router is mounted at ``/api/v1/risk`` automatically by the slice-5
dynamic-discovery loop in :mod:`iguanatrader.api.routes`. Adding a new
risk endpoint is a matter of declaring it on this router; no edit to
``app.py`` or ``routes/__init__.py``.

structlog event-name convention (per K1 prompt): ``risk.<entity>.<action>``.
The route handlers are thin — most logic lives in
:class:`iguanatrader.contexts.risk.service.RiskService`.

Errors:

* :class:`iguanatrader.shared.errors.OverrideAuditMissingError` raised
  by the service-layer renders as 400 RFC 7807 via the slice-5 global
  handler (no per-route try/except needed).
* :class:`iguanatrader.shared.errors.KillSwitchActiveError` would be
  raised inside ``evaluate_proposal`` (not directly callable from
  these routes — the trade-evaluation entry point is in slice T1's
  trading service which calls into ``RiskService.evaluate_proposal``).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.deps import get_current_user, get_db
from iguanatrader.api.dtos.risk import (
    CapsDTO,
    OverrideRequest,
    OverrideResponse,
    RiskStateResponse,
    StateDTO,
)
from iguanatrader.contexts.risk.repository import RiskRepository
from iguanatrader.contexts.risk.service import RiskService
from iguanatrader.persistence import User
from iguanatrader.shared.time import now as utc_now

log = structlog.get_logger("iguanatrader.api.routes.risk")

router = APIRouter(prefix="/risk", tags=["risk"])


def _build_service(session: AsyncSession) -> RiskService:
    """Compose a request-scoped :class:`RiskService` from the session.

    Slice 5's API foundation does not yet ship a DI container; route
    handlers compose their service objects from the request-scoped
    session. Slice O1 may swap this for a ``Depends(...)`` factory.
    The :class:`MessageBus` argument is omitted for K1 routes — the
    SSE module owns the bus singleton; routes don't need to publish.
    """
    repo = RiskRepository(session)
    return RiskService(repository=repo, bus=None)


@router.get(
    "/state",
    response_model=RiskStateResponse,
    status_code=status.HTTP_200_OK,
)
async def get_state(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> RiskStateResponse:
    """Return the current caps + state + kill-switch flag for the tenant.

    Auth: any authenticated user (the tenant scoping is enforced by
    the slice-3 ORM listener via ``tenant_id_var``, which
    :func:`get_current_user` sets before this handler runs).
    """
    service = _build_service(session)
    caps = service.load_caps()
    state = await service.repository.load_risk_state(user.tenant_id)
    is_active = await service.repository.load_kill_switch_state(user.tenant_id)
    # ``per_trade`` utilisation is per-proposal (not stateful), so it's
    # absent from this snapshot — the dashboard renders it on a
    # per-proposal basis from the per-evaluation events.
    utilisation = {
        "daily_loss": state.day_to_date_loss_pct,
        "weekly_loss": state.week_to_date_loss_pct,
        "max_drawdown": state.peak_to_trough_drawdown_pct,
    }

    log.info(
        "risk.state.fetched",
        tenant_id=str(user.tenant_id),
        kill_switch_active=is_active,
    )

    return RiskStateResponse(
        caps=CapsDTO(
            per_trade_pct=caps.per_trade_pct,
            daily_loss_pct=caps.daily_loss_pct,
            weekly_loss_pct=caps.weekly_loss_pct,
            max_open_positions=caps.max_open_positions,
            max_drawdown_pct=caps.max_drawdown_pct,
        ),
        state=StateDTO(
            capital=state.capital,
            day_to_date_loss_pct=state.day_to_date_loss_pct,
            week_to_date_loss_pct=state.week_to_date_loss_pct,
            open_positions_count=state.open_positions_count,
            peak_to_trough_drawdown_pct=state.peak_to_trough_drawdown_pct,
        ),
        utilisation=utilisation,
        kill_switch_active=is_active,
        fetched_at=utc_now(),
    )


@router.post(
    "/override",
    response_model=OverrideResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_override(
    body: OverrideRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> OverrideResponse:
    """Persist an override audit row.

    The DTO's ``Field(min_length=20)`` already rejects short reasons
    at the FastAPI / Pydantic boundary with a native 422; the
    :class:`OverrideAuditMissingError` raised by the service layer
    renders as 400 RFC 7807 for any other audit-field shortfall.

    No role gating in K1: any authenticated user of the tenant can
    record an override (single-seat-per-tenant model). When the
    multi-seat RBAC lands (post-MVP), this route will require the
    ``tenant_user`` role explicitly via ``Depends(requires_role(Role.tenant_user))``.
    """
    service = _build_service(session)
    override_id = await service.record_override(
        tenant_id=user.tenant_id,
        proposal_id=body.proposal_id,
        risk_evaluation_id=body.risk_evaluation_id,
        authorised_by_user_id=body.authorised_by_user_id,
        reason_text=body.reason_text,
        confirmation_chain=body.confirmation_chain,
        state_snapshot_at_override=body.state_snapshot_at_override,
    )
    await session.commit()

    return OverrideResponse(
        override_id=override_id,
        proposal_id=body.proposal_id,
        risk_evaluation_id=body.risk_evaluation_id,
        authorised_by_user_id=body.authorised_by_user_id,
        reason_text=body.reason_text,
        confirmation_chain=body.confirmation_chain,
        created_at=utc_now(),
    )


__all__ = ["router"]
