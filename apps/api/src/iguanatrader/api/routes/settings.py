"""Settings routes (slice R6 + slice A0 budget-cap exposure).

GET/PUT ``/settings/feature-flags`` reads + writes
``tenants.feature_flags`` for the authenticated tenant. Whitelisted
keys:

* ``hindsight_recall_enabled`` — FR81 narrative recall toggle (R6).
* ``llm_budget_usd`` — per-tenant monthly LLM budget cap (A0). String-
  encoded Decimal to avoid float drift on JSON round-trip. Empty
  string clears the cap (falls back to the canonical $50 default).

Partial updates supported: any field left ``None`` in the PUT payload
keeps the persisted value untouched. Unknown keys → 400.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.deps import get_current_user, get_db
from iguanatrader.api.dtos.settings import FeatureFlagsIn, FeatureFlagsOut
from iguanatrader.persistence import Tenant, User
from iguanatrader.shared.errors import IguanaError, NotFoundError

log = structlog.get_logger("iguanatrader.api.routes.settings")

router = APIRouter(prefix="/settings", tags=["settings"])


class InvalidBudgetCapError(IguanaError):
    """Raised when ``llm_budget_usd`` PUT payload fails parse/validate."""

    type_uri = "urn:iguanatrader:error:invalid-budget-cap"
    default_title = "Invalid Budget Cap"
    default_status = 400


class InvalidRiskThresholdError(IguanaError):
    """Raised when ``risk_review_confidence_threshold`` PUT payload fails parse/validate."""

    type_uri = "urn:iguanatrader:error:invalid-risk-threshold"
    default_title = "Invalid Risk Threshold"
    default_status = 400


@router.get("/feature-flags", response_model=FeatureFlagsOut)
async def get_feature_flags(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeatureFlagsOut:
    """Return the current tenant's feature flags."""
    log.info("api.settings.feature_flags.get", tenant_id=str(user.tenant_id))
    tenant = await db.get(Tenant, user.tenant_id)
    if tenant is None:
        raise NotFoundError(detail=f"Tenant {user.tenant_id} not found.")
    flags = dict(tenant.feature_flags or {})
    raw_budget = flags.get("llm_budget_usd")
    raw_threshold = flags.get("risk_review_confidence_threshold")
    return FeatureFlagsOut(
        hindsight_recall_enabled=bool(flags.get("hindsight_recall_enabled", False)),
        llm_budget_usd=str(raw_budget) if raw_budget is not None else None,
        risk_review_confidence_threshold=(
            str(raw_threshold) if raw_threshold is not None else None
        ),
    )


@router.put("/feature-flags", response_model=FeatureFlagsOut)
async def put_feature_flags(
    payload: FeatureFlagsIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeatureFlagsOut:
    """Update the current tenant's feature flags (whitelisted keys).

    Partial updates supported — fields left ``None`` in the payload
    are not touched on the persisted JSON.
    """
    log.info(
        "api.settings.feature_flags.put",
        tenant_id=str(user.tenant_id),
        flags=payload.model_dump(),
    )
    tenant = await db.get(Tenant, user.tenant_id)
    if tenant is None:
        raise NotFoundError(detail=f"Tenant {user.tenant_id} not found.")
    current = dict(tenant.feature_flags or {})

    if payload.hindsight_recall_enabled is not None:
        current["hindsight_recall_enabled"] = bool(payload.hindsight_recall_enabled)

    if payload.llm_budget_usd is not None:
        raw = payload.llm_budget_usd.strip()
        if raw == "":
            # Empty string → clear the cap, fall back to the canonical default.
            current.pop("llm_budget_usd", None)
        else:
            try:
                value = Decimal(raw)
            except (InvalidOperation, ValueError) as exc:
                raise InvalidBudgetCapError(
                    detail=f"llm_budget_usd must parse as a decimal; got {raw!r}."
                ) from exc
            if value < Decimal("0"):
                raise InvalidBudgetCapError(detail="llm_budget_usd cannot be negative.")
            current["llm_budget_usd"] = str(value)

    if payload.risk_review_confidence_threshold is not None:
        raw_t = payload.risk_review_confidence_threshold.strip()
        if raw_t == "":
            current.pop("risk_review_confidence_threshold", None)
        else:
            try:
                threshold = Decimal(raw_t)
            except (InvalidOperation, ValueError) as exc:
                raise InvalidRiskThresholdError(
                    detail=(
                        "risk_review_confidence_threshold must parse as a "
                        f"decimal; got {raw_t!r}."
                    )
                ) from exc
            if threshold < Decimal("0") or threshold > Decimal("1"):
                raise InvalidRiskThresholdError(
                    detail=(
                        "risk_review_confidence_threshold must be in [0, 1]; " f"got {raw_t!r}."
                    )
                )
            current["risk_review_confidence_threshold"] = str(threshold)

    tenant.feature_flags = current
    await db.commit()

    return FeatureFlagsOut(
        hindsight_recall_enabled=bool(current.get("hindsight_recall_enabled", False)),
        llm_budget_usd=(str(current["llm_budget_usd"]) if "llm_budget_usd" in current else None),
        risk_review_confidence_threshold=(
            str(current["risk_review_confidence_threshold"])
            if "risk_review_confidence_threshold" in current
            else None
        ),
    )


__all__ = ["router"]
