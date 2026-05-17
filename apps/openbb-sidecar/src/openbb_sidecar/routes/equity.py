"""Equity routes — `/v1/equity/*` thin wrappers around the OpenBB facade.

Per task 3.1 + design D2: minimal endpoint surface (3 endpoints), every
request goes through ``OpenBBFacade``; route handlers do error mapping
(facade raises → HTTPException 404/502).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from openbb_sidecar.adapters.openbb_facade import OpenBBFacade, OpenBBFacadeError

router = APIRouter(prefix="/v1/equity", tags=["equity"])

logger = logging.getLogger(__name__)
_facade = OpenBBFacade()


class EquityFundamentalsResponse(BaseModel):
    symbol: str
    pe_ratio: float | None = None
    forward_pe: float | None = None
    price_to_book: float | None = None
    market_cap: float | None = None
    dividend_yield: float | None = None
    as_of_date: Any | None = Field(default=None, description="Date string or ISO 8601 timestamp")


class EquityRatingsResponse(BaseModel):
    symbol: str
    consensus: str | None = None
    target_price: float | None = None
    analyst_count: int | None = None
    as_of_date: Any | None = None


class EquityESGResponse(BaseModel):
    symbol: str
    esg_score: float | None = None
    environmental_score: float | None = None
    social_score: float | None = None
    governance_score: float | None = None
    as_of_date: Any | None = None


class EquityHistoricalPricesResponse(BaseModel):
    """Daily OHLCV bar series; ``bars`` ordered ascending by ``date``."""

    symbol: str
    start_date: str | None = None
    end_date: str | None = None
    bars: list[dict[str, Any]] = Field(default_factory=list)


def _map_facade_error_to_http(exc: OpenBBFacadeError, symbol: str) -> HTTPException:
    """Translate facade errors to HTTP 404 (no-data) vs 502 (upstream failure)."""
    msg = str(exc).lower()
    if (
        "no fundamentals" in msg
        or "no analyst" in msg
        or "no esg" in msg
        or "no macro" in msg
        or "no historical prices" in msg
    ):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"symbol": symbol, "error": str(exc)},
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={"symbol": symbol, "error": str(exc)},
    )


@router.get("/fundamentals/{symbol}", response_model=EquityFundamentalsResponse)
def fundamentals(symbol: str) -> EquityFundamentalsResponse:
    try:
        data = _facade.equity_fundamentals(symbol)
    except OpenBBFacadeError as exc:
        logger.warning(
            "openbb_sidecar.equity_fundamentals.failed",
            extra={"symbol": symbol, "error": str(exc)},
        )
        raise _map_facade_error_to_http(exc, symbol) from exc
    return EquityFundamentalsResponse(**data)


@router.get("/ratings/{symbol}", response_model=EquityRatingsResponse)
def ratings(symbol: str) -> EquityRatingsResponse:
    try:
        data = _facade.equity_ratings(symbol)
    except OpenBBFacadeError as exc:
        logger.warning(
            "openbb_sidecar.equity_ratings.failed",
            extra={"symbol": symbol, "error": str(exc)},
        )
        raise _map_facade_error_to_http(exc, symbol) from exc
    return EquityRatingsResponse(**data)


@router.get("/esg/{symbol}", response_model=EquityESGResponse)
def esg(symbol: str) -> EquityESGResponse:
    try:
        data = _facade.equity_esg(symbol)
    except OpenBBFacadeError as exc:
        logger.warning(
            "openbb_sidecar.equity_esg.failed",
            extra={"symbol": symbol, "error": str(exc)},
        )
        raise _map_facade_error_to_http(exc, symbol) from exc
    return EquityESGResponse(**data)


@router.get("/historical_prices/{symbol}", response_model=EquityHistoricalPricesResponse)
def historical_prices(
    symbol: str,
    start_date: str | None = Query(
        default=None,
        description="ISO 8601 YYYY-MM-DD inclusive lower bound on the bar series.",
    ),
    end_date: str | None = Query(
        default=None,
        description="ISO 8601 YYYY-MM-DD inclusive upper bound on the bar series.",
    ),
) -> EquityHistoricalPricesResponse:
    try:
        data = _facade.equity_historical_prices(symbol, start_date, end_date)
    except OpenBBFacadeError as exc:
        logger.warning(
            "openbb_sidecar.equity_historical_prices.failed",
            extra={"symbol": symbol, "error": str(exc)},
        )
        raise _map_facade_error_to_http(exc, symbol) from exc
    return EquityHistoricalPricesResponse(**data)
