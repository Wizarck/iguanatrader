"""Broker-translator catalogue route — slice ``ib-translators-full``.

Auto-discovered. Exposes the IBKR translator vocabulary (sec_type +
order_type + algo_kind) with human-readable Spanish prose so the
frontend can render the order-builder selectors without hard-coding
the strings or maintaining a TS copy of the explanations.

Read-only — every authenticated user gets the same response (the
catalogue is global, not tenant-scoped). The frontend caches the
response per page-load.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from iguanatrader.api.deps import get_current_user
from iguanatrader.contexts.trading.brokers.translator_docs import (
    ALGO_KINDS,
    ORDER_TYPES,
    SEC_TYPES,
    TranslatorOption,
)
from iguanatrader.persistence import User

log = structlog.get_logger("iguanatrader.api.routes.broker_types")

router = APIRouter(prefix="/broker", tags=["broker"])


class TranslatorOptionDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    label: str
    description: str
    required_fields: list[str]


class BrokerTypesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sec_types: list[TranslatorOptionDTO]
    order_types: list[TranslatorOptionDTO]
    algo_kinds: list[TranslatorOptionDTO]


@router.get("/types", response_model=BrokerTypesResponse)
async def get_broker_types(
    user: User = Depends(get_current_user),
) -> BrokerTypesResponse:
    """Return the full IBKR translator catalogue (sec_type / order_type / algo_kind).

    Each entry carries:

    * ``code`` — the literal string the daemon expects (e.g. ``"STK"`` /
      ``"TRAIL LIMIT"``).
    * ``label`` — short UI string (Spanish).
    * ``description`` — 1-3 paragraph prose explaining the option,
      required parameters, and the canonical use case. The UI renders
      this as the selector tooltip / help-panel content.
    * ``required_fields`` — list of additional :class:`Contract` /
      :class:`IBOrder` attributes the caller MUST populate beyond the
      always-required ones.
    """
    log.info("api.broker.types.get")
    return BrokerTypesResponse(
        sec_types=[_to_dto(o) for o in SEC_TYPES],
        order_types=[_to_dto(o) for o in ORDER_TYPES],
        algo_kinds=[_to_dto(o) for o in ALGO_KINDS],
    )


def _to_dto(opt: TranslatorOption) -> TranslatorOptionDTO:
    return TranslatorOptionDTO(
        code=opt.code,
        label=opt.label,
        description=opt.description,
        required_fields=list(opt.required_fields),
    )


__all__ = ["router"]
