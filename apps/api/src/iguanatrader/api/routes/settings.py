"""Settings routes (slice R6 hindsight-integration).

GET/PUT ``/settings/feature-flags`` reads + writes
``tenants.feature_flags`` for the authenticated tenant. The v1 schema
whitelists a single key (``hindsight_recall_enabled``); unknown keys
in the PUT payload are rejected by Pydantic's ``extra='forbid'``.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.deps import get_current_user, get_db
from iguanatrader.api.dtos.settings import FeatureFlagsIn, FeatureFlagsOut
from iguanatrader.persistence import Tenant, User
from iguanatrader.shared.errors import NotFoundError

log = structlog.get_logger("iguanatrader.api.routes.settings")

router = APIRouter(prefix="/settings", tags=["settings"])


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
    return FeatureFlagsOut(
        hindsight_recall_enabled=bool(flags.get("hindsight_recall_enabled", False)),
    )


@router.put("/feature-flags", response_model=FeatureFlagsOut)
async def put_feature_flags(
    payload: FeatureFlagsIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeatureFlagsOut:
    """Update the current tenant's feature flags (whitelisted keys)."""
    log.info(
        "api.settings.feature_flags.put",
        tenant_id=str(user.tenant_id),
        flags=payload.model_dump(),
    )
    tenant = await db.get(Tenant, user.tenant_id)
    if tenant is None:
        raise NotFoundError(detail=f"Tenant {user.tenant_id} not found.")
    current = dict(tenant.feature_flags or {})
    current["hindsight_recall_enabled"] = bool(payload.hindsight_recall_enabled)
    tenant.feature_flags = current
    await db.commit()
    return FeatureFlagsOut(
        hindsight_recall_enabled=current["hindsight_recall_enabled"],
    )


__all__ = ["router"]
