"""Integration tests for sidecar routes — facade mocked, no network."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from openbb_sidecar.adapters.openbb_facade import OpenBBFacadeError
from openbb_sidecar.main import create_app


@pytest.mark.asyncio
async def test_equity_fundamentals_route_happy_path() -> None:
    canned = {
        "symbol": "AAPL",
        "pe_ratio": 22.5,
        "market_cap": 3_500_000_000_000.0,
        "dividend_yield": 0.005,
        "as_of_date": "2026-04-30",
    }
    with patch("openbb_sidecar.routes.equity._facade.equity_fundamentals", return_value=canned):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            response = await c.get("/v1/equity/fundamentals/AAPL")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "AAPL"
    assert body["pe_ratio"] == 22.5


@pytest.mark.asyncio
async def test_equity_fundamentals_route_404_on_no_data() -> None:
    with patch(
        "openbb_sidecar.routes.equity._facade.equity_fundamentals",
        side_effect=OpenBBFacadeError("no fundamentals for UNKNOWN"),
    ):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            response = await c.get("/v1/equity/fundamentals/UNKNOWN")

    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["symbol"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_equity_fundamentals_route_502_on_upstream_failure() -> None:
    with patch(
        "openbb_sidecar.routes.equity._facade.equity_fundamentals",
        side_effect=OpenBBFacadeError("equity_fundamentals(AAPL) failed: ConnectionError"),
    ):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            response = await c.get("/v1/equity/fundamentals/AAPL")

    assert response.status_code == 502


@pytest.mark.asyncio
async def test_equity_ratings_route_happy_path() -> None:
    canned = {
        "symbol": "AAPL",
        "consensus": "Buy",
        "target_price": 250.0,
        "analyst_count": 42,
        "as_of_date": "2026-04-29",
    }
    with patch("openbb_sidecar.routes.equity._facade.equity_ratings", return_value=canned):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            response = await c.get("/v1/equity/ratings/AAPL")

    assert response.status_code == 200
    body = response.json()
    assert body["consensus"] == "Buy"
    assert body["target_price"] == 250.0


@pytest.mark.asyncio
async def test_equity_esg_route_happy_path() -> None:
    canned = {
        "symbol": "AAPL",
        "esg_score": 65.0,
        "environmental_score": 60.0,
        "social_score": 70.0,
        "governance_score": 65.0,
        "as_of_date": "2026-03-31",
    }
    with patch("openbb_sidecar.routes.equity._facade.equity_esg", return_value=canned):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            response = await c.get("/v1/equity/esg/AAPL")

    assert response.status_code == 200
    body = response.json()
    assert body["esg_score"] == 65.0


@pytest.mark.asyncio
async def test_economy_macro_route_happy_path() -> None:
    canned = {
        "indicator": "CPIAUCSL",
        "series": [
            {"date": "2026-01-01", "value": 100.0},
            {"date": "2026-02-01", "value": 101.5},
        ],
        "unit": "Index 1982-1984=100",
        "frequency": "Monthly",
    }
    with patch("openbb_sidecar.routes.economy._facade.economy_macro", return_value=canned):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            response = await c.get("/v1/economy/macro/CPIAUCSL")

    assert response.status_code == 200
    body = response.json()
    assert len(body["series"]) == 2
    assert body["unit"] == "Index 1982-1984=100"


@pytest.mark.asyncio
async def test_economy_macro_route_404_on_unknown_indicator() -> None:
    with patch(
        "openbb_sidecar.routes.economy._facade.economy_macro",
        side_effect=OpenBBFacadeError("no macro data for indicator=BOGUS"),
    ):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            response = await c.get("/v1/economy/macro/BOGUS")

    assert response.status_code == 404
