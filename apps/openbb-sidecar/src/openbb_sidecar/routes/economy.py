"""Economy routes — `/v1/economy/*` thin wrapper around the OpenBB facade."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from openbb_sidecar.adapters.openbb_facade import OpenBBFacade, OpenBBFacadeError

router = APIRouter(prefix="/v1/economy", tags=["economy"])

logger = logging.getLogger(__name__)
_facade = OpenBBFacade()


class MacroSeriesPoint(BaseModel):
    date: Any | None = None
    value: float | None = None


class MacroResponse(BaseModel):
    indicator: str
    series: list[MacroSeriesPoint]
    unit: str | None = None
    frequency: str | None = None


@router.get("/macro/{indicator}", response_model=MacroResponse)
def macro(indicator: str) -> MacroResponse:
    try:
        data = _facade.economy_macro(indicator)
    except OpenBBFacadeError as exc:
        logger.warning(
            "openbb_sidecar.economy_macro.failed",
            extra={"indicator": indicator, "error": str(exc)},
        )
        msg = str(exc).lower()
        if "no macro" in msg or "no data" in msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"indicator": indicator, "error": str(exc)},
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"indicator": indicator, "error": str(exc)},
        ) from exc
    return MacroResponse(**data)
