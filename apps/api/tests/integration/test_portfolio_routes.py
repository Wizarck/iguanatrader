"""Integration tests for ``/api/v1/portfolio*`` (slice trading-routes-portfolio-strategies-bodies).

Eight cases per proposal §Tests:

1. Empty tenant → synthesised empty equity + empty trade/order lists.
2. Seeded data → echoes back.
3. ``GET /portfolio/positions`` no open trades → ``items=[]``.
4. ``GET /portfolio/positions`` with fills → computed ``avg_entry_price``.
5. ``GET /portfolio/positions`` open trade w/ no fills → null entries.
6. ``GET /portfolio/equity`` no snapshots → 404 ``NotFoundError``.
7. ``GET /portfolio/equity`` with snapshot → echoes latest.
8. Cross-tenant isolation (via slice-3 ``tenant_listener``).

Mirror of :mod:`apps.api.tests.integration.test_trade_routes` —
cookie-driven JWT auth + ASGI transport + tenant-scoped seeds.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from iguanatrader.api import deps as api_deps
from iguanatrader.api.app import create_app
from iguanatrader.api.auth import encode_jwt, hash_password
from iguanatrader.api.deps import COOKIE_NAME
from iguanatrader.contexts.trading.market_data.models import MarketDataBar
from iguanatrader.contexts.trading.models import (
    EquitySnapshot,
    Fill,
    Order,
    Trade,
    TradeProposal,
)
from iguanatrader.persistence import (
    Tenant,
    User,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import with_tenant_context
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_JWT_SECRET", "x" * 64)


@pytest.fixture(autouse=True)
def _listeners() -> Iterator[None]:
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    db_path = tmp_path / "ig_portfolio_routes.db"
    eng = engine_factory(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def sf(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return session_factory(engine)


async def _seed_tenant_user(
    sf: async_sessionmaker[AsyncSession],
    *,
    email: str,
    tenant_name: str,
) -> dict[str, UUID]:
    tid = uuid4()
    uid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name=tenant_name, feature_flags={}))
        await s.commit()
    async with with_tenant_context(tid), sf() as s:
        s.add(
            User(
                id=uid,
                tenant_id=tid,
                email=email,
                password_hash=hash_password("pw"),
                role="tenant_user",
            )
        )
        await s.commit()
    return {"tenant_id": tid, "user_id": uid}


@pytest.fixture
async def seed(sf: async_sessionmaker[AsyncSession]) -> dict[str, UUID]:
    return await _seed_tenant_user(sf, email="trader@example.com", tenant_name="t-portfolio")


@pytest.fixture
async def app_with_overrides(
    engine: AsyncEngine,
    sf: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Any]:
    app = create_app()

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with sf() as s:
            yield s

    app.dependency_overrides[api_deps.get_db] = _override_get_db
    try:
        yield app
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
async def client(app_with_overrides: Any) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app_with_overrides)
    async with AsyncClient(transport=transport, base_url="https://test") as c:
        yield c


def _login_cookie(user_id: UUID, tenant_id: UUID, role: str = "tenant_user") -> str:
    import time

    return encode_jwt(
        {
            "sub": str(user_id),
            "tenant_id": str(tenant_id),
            "role": role,
            "login_at": int(time.time()),
        },
        exp_seconds=3600,
    )


async def _seed_open_trade_with_fills(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    symbol: str,
    quantity: Decimal,
    fills: list[tuple[Decimal, Decimal]],
    opened_offset_seconds: int = 0,
) -> dict[str, UUID]:
    """Insert proposal + open trade + market order + N fills.

    ``fills`` is a list of ``(quantity_filled, fill_price)`` tuples.
    The total fill quantity does NOT have to equal ``quantity`` (a
    partially-filled trade is still in state ``open`` in this schema).
    """
    base = datetime.now(UTC) + timedelta(seconds=opened_offset_seconds)
    proposal_id = uuid4()
    trade_id = uuid4()
    order_id = uuid4()
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            TradeProposal(
                id=proposal_id,
                tenant_id=tenant_id,
                strategy_config_id=uuid4(),
                research_brief_id=None,
                correlation_id=uuid4(),
                symbol=symbol,
                side="buy",
                quantity=quantity,
                entry_price_indicative=Decimal("100"),
                stop_price=Decimal("90"),
                reasoning={"why": "test"},
                mode="paper",
            )
        )
        s.add(
            Trade(
                id=trade_id,
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                symbol=symbol,
                side="buy",
                quantity=quantity,
                mode="paper",
                state="open",
                opened_at=base,
            )
        )
        s.add(
            Order(
                id=order_id,
                tenant_id=tenant_id,
                trade_id=trade_id,
                broker="ibkr",
                broker_order_id=f"IB-{order_id}",
                order_type="market",
                side="buy",
                quantity=quantity,
                state="partially_filled" if fills else "submitted",
                submitted_at=base,
            )
        )
        for fill_qty, fill_price in fills:
            s.add(
                Fill(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    order_id=order_id,
                    quantity_filled=fill_qty,
                    fill_price=fill_price,
                    commission=Decimal("0"),
                    commission_currency="USD",
                    filled_at=base,
                )
            )
        await s.commit()
    return {"trade_id": trade_id, "order_id": order_id, "proposal_id": proposal_id}


async def _seed_equity_snapshot(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    account_equity: Decimal,
    created_offset_seconds: int = 0,
    created_at: datetime | None = None,
) -> UUID:
    snap_id = uuid4()
    ts = (
        created_at
        if created_at is not None
        else datetime.now(UTC) + timedelta(seconds=created_offset_seconds)
    )
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            EquitySnapshot(
                id=snap_id,
                tenant_id=tenant_id,
                mode="paper",
                account_equity=account_equity,
                cash_balance=Decimal("0"),
                realized_pnl_today=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                currency="USD",
                snapshot_kind="event",
                created_at=ts,
            )
        )
        await s.commit()
    return snap_id


async def _seed_market_data_bar(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    symbol: str,
    close: Decimal,
    timeframe: str = "1d",
    ts: datetime | None = None,
) -> UUID:
    bar_id = uuid4()
    ts_val = ts if ts is not None else datetime.now(UTC)
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(
            MarketDataBar(
                id=bar_id,
                tenant_id=tenant_id,
                symbol=symbol,
                timeframe=timeframe,
                ts=ts_val,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=100000,
                source="test",
            )
        )
        await s.commit()
    return bar_id


# ---------------------------------------------------------------------------
# GET /portfolio
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_portfolio_empty_tenant_returns_synthesised_empty_equity(
    client: AsyncClient,
    seed: dict[str, UUID],
) -> None:
    cookie = _login_cookie(seed["user_id"], seed["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/portfolio")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["equity"]["snapshot_kind"] == "empty"
    assert body["equity"]["account_equity"] == "0"
    assert body["equity"]["cash_balance"] == "0"
    assert body["open_trades"] == []
    assert body["open_orders"] == []


@pytest.mark.asyncio
async def test_get_portfolio_with_seeded_data_echoes_back(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, UUID],
) -> None:
    tid = seed["tenant_id"]
    uid = seed["user_id"]
    await _seed_open_trade_with_fills(
        sf,
        tenant_id=tid,
        symbol="SPY",
        quantity=Decimal("10"),
        fills=[(Decimal("10"), Decimal("450.25"))],
    )
    await _seed_equity_snapshot(
        sf,
        tenant_id=tid,
        account_equity=Decimal("100000"),
    )
    cookie = _login_cookie(uid, tid)
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/portfolio")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["equity"]["snapshot_kind"] == "event"
    assert body["equity"]["account_equity"] == "100000"
    assert len(body["open_trades"]) == 1
    assert body["open_trades"][0]["symbol"] == "SPY"
    # Order is "partially_filled" — counts as open.
    assert len(body["open_orders"]) == 1
    assert body["open_orders"][0]["state"] == "partially_filled"


# ---------------------------------------------------------------------------
# GET /portfolio/positions
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_positions_no_open_trades_returns_empty(
    client: AsyncClient,
    seed: dict[str, UUID],
) -> None:
    cookie = _login_cookie(seed["user_id"], seed["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/portfolio/positions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_get_positions_with_fills_computes_weighted_avg_entry_price(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, UUID],
) -> None:
    tid = seed["tenant_id"]
    uid = seed["user_id"]
    # Trade A: 2 fills @ 100 and @ 110 (both qty 5) → weighted avg 105.
    await _seed_open_trade_with_fills(
        sf,
        tenant_id=tid,
        symbol="AAPL",
        quantity=Decimal("10"),
        fills=[(Decimal("5"), Decimal("100")), (Decimal("5"), Decimal("110"))],
        opened_offset_seconds=0,
    )
    # Trade B: 1 fill @ 200 qty 3 → avg 200. Newer (opened_at).
    await _seed_open_trade_with_fills(
        sf,
        tenant_id=tid,
        symbol="MSFT",
        quantity=Decimal("3"),
        fills=[(Decimal("3"), Decimal("200"))],
        opened_offset_seconds=60,
    )
    cookie = _login_cookie(uid, tid)
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/portfolio/positions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    # Sorted opened_at DESC — MSFT first.
    assert body["items"][0]["symbol"] == "MSFT"
    assert Decimal(body["items"][0]["avg_entry_price"]) == Decimal("200")
    assert body["items"][1]["symbol"] == "AAPL"
    assert Decimal(body["items"][1]["avg_entry_price"]) == Decimal("105")
    # Market-data fields stay null in v1.
    for row in body["items"]:
        assert row["last_price"] is None
        assert row["unrealized_pnl"] is None


@pytest.mark.asyncio
async def test_get_positions_open_trade_with_no_fills_yields_null_avg_entry(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, UUID],
) -> None:
    tid = seed["tenant_id"]
    uid = seed["user_id"]
    await _seed_open_trade_with_fills(
        sf,
        tenant_id=tid,
        symbol="TSLA",
        quantity=Decimal("5"),
        fills=[],
    )
    cookie = _login_cookie(uid, tid)
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/portfolio/positions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["symbol"] == "TSLA"
    assert row["avg_entry_price"] is None
    assert row["last_price"] is None
    assert row["unrealized_pnl"] is None


@pytest.mark.asyncio
async def test_get_positions_with_market_data_computes_last_price_and_unrealized_pnl(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, UUID],
) -> None:
    tid = seed["tenant_id"]
    uid = seed["user_id"]
    # BUY 10 @ avg entry 100; latest bar close 110 → unrealized = (110-100)*10 = 100.
    await _seed_open_trade_with_fills(
        sf,
        tenant_id=tid,
        symbol="AAPL",
        quantity=Decimal("10"),
        fills=[(Decimal("10"), Decimal("100"))],
    )
    await _seed_market_data_bar(sf, tenant_id=tid, symbol="AAPL", close=Decimal("110"))
    cookie = _login_cookie(uid, tid)
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/portfolio/positions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["symbol"] == "AAPL"
    assert Decimal(row["avg_entry_price"]) == Decimal("100")
    assert Decimal(row["last_price"]) == Decimal("110")
    assert Decimal(row["unrealized_pnl"]) == Decimal("100")


@pytest.mark.asyncio
async def test_get_positions_without_market_data_leaves_last_price_null(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, UUID],
) -> None:
    tid = seed["tenant_id"]
    uid = seed["user_id"]
    await _seed_open_trade_with_fills(
        sf,
        tenant_id=tid,
        symbol="AAPL",
        quantity=Decimal("10"),
        fills=[(Decimal("10"), Decimal("100"))],
    )
    # No MarketDataBar seeded.
    cookie = _login_cookie(uid, tid)
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/portfolio/positions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["symbol"] == "AAPL"
    assert Decimal(row["avg_entry_price"]) == Decimal("100")
    assert row["last_price"] is None
    assert row["unrealized_pnl"] is None


@pytest.mark.asyncio
async def test_get_positions_mixed_market_data(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, UUID],
) -> None:
    tid = seed["tenant_id"]
    uid = seed["user_id"]
    # Trade A — AAPL with bar.
    await _seed_open_trade_with_fills(
        sf,
        tenant_id=tid,
        symbol="AAPL",
        quantity=Decimal("10"),
        fills=[(Decimal("10"), Decimal("100"))],
        opened_offset_seconds=0,
    )
    # Trade B — MSFT without bar. Newer (sorted first by opened_at DESC).
    await _seed_open_trade_with_fills(
        sf,
        tenant_id=tid,
        symbol="MSFT",
        quantity=Decimal("5"),
        fills=[(Decimal("5"), Decimal("200"))],
        opened_offset_seconds=60,
    )
    await _seed_market_data_bar(sf, tenant_id=tid, symbol="AAPL", close=Decimal("110"))
    cookie = _login_cookie(uid, tid)
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/portfolio/positions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    by_symbol = {row["symbol"]: row for row in body["items"]}
    assert by_symbol["MSFT"]["last_price"] is None
    assert by_symbol["MSFT"]["unrealized_pnl"] is None
    assert Decimal(by_symbol["AAPL"]["last_price"]) == Decimal("110")
    assert Decimal(by_symbol["AAPL"]["unrealized_pnl"]) == Decimal("100")


# ---------------------------------------------------------------------------
# GET /portfolio/equity
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_equity_returns_404_when_no_snapshots(
    client: AsyncClient,
    seed: dict[str, UUID],
) -> None:
    cookie = _login_cookie(seed["user_id"], seed["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/portfolio/equity")
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body["type"] == "urn:iguanatrader:error:not-found"


@pytest.mark.asyncio
async def test_get_equity_returns_latest_snapshot(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, UUID],
) -> None:
    tid = seed["tenant_id"]
    uid = seed["user_id"]
    await _seed_equity_snapshot(
        sf, tenant_id=tid, account_equity=Decimal("50000"), created_offset_seconds=0
    )
    newest = await _seed_equity_snapshot(
        sf,
        tenant_id=tid,
        account_equity=Decimal("75000"),
        created_offset_seconds=60,
    )
    cookie = _login_cookie(uid, tid)
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/portfolio/equity")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(newest)
    assert body["account_equity"] == "75000"


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_portfolio_isolated_across_tenants(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
) -> None:
    a = await _seed_tenant_user(sf, email="alice@x.test", tenant_name="t-A")
    b = await _seed_tenant_user(sf, email="bob@x.test", tenant_name="t-B")
    # Tenant A: 1 open trade + 1 snapshot.
    await _seed_open_trade_with_fills(
        sf,
        tenant_id=a["tenant_id"],
        symbol="SPY",
        quantity=Decimal("1"),
        fills=[(Decimal("1"), Decimal("400"))],
    )
    await _seed_equity_snapshot(sf, tenant_id=a["tenant_id"], account_equity=Decimal("9999"))
    # Tenant B: nothing.
    cookie_b = _login_cookie(b["user_id"], b["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie_b)
    # GET /portfolio for B should be empty (B sees no A data).
    resp = await client.get("/api/v1/portfolio")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["equity"]["snapshot_kind"] == "empty"
    assert body["open_trades"] == []
    # GET /portfolio/equity for B should 404 even though A has a snapshot.
    resp_eq = await client.get("/api/v1/portfolio/equity")
    assert resp_eq.status_code == 404, resp_eq.text
    # GET /portfolio/positions for B should be empty list.
    resp_pos = await client.get("/api/v1/portfolio/positions")
    assert resp_pos.status_code == 200, resp_pos.text
    assert resp_pos.json()["items"] == []


# ---------------------------------------------------------------------------
# GET /portfolio — day P&L (slice portfolio-pnl-and-equity-series)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_portfolio_day_pnl_null_when_no_today_snapshot(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, UUID],
) -> None:
    tid = seed["tenant_id"]
    uid = seed["user_id"]
    yesterday = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        hours=1
    )
    await _seed_equity_snapshot(
        sf,
        tenant_id=tid,
        account_equity=Decimal("100000"),
        created_at=yesterday,
    )
    cookie = _login_cookie(uid, tid)
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/portfolio")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["day_pnl_abs"] is None
    assert body["day_pnl_pct"] is None


@pytest.mark.asyncio
async def test_get_portfolio_day_pnl_computed_with_baseline(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, UUID],
) -> None:
    tid = seed["tenant_id"]
    uid = seed["user_id"]
    today_midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    await _seed_equity_snapshot(
        sf,
        tenant_id=tid,
        account_equity=Decimal("100000"),
        created_at=today_midnight + timedelta(hours=9),
    )
    await _seed_equity_snapshot(
        sf,
        tenant_id=tid,
        account_equity=Decimal("102500"),
        created_at=today_midnight + timedelta(hours=14),
    )
    cookie = _login_cookie(uid, tid)
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/portfolio")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["day_pnl_abs"]) == Decimal("2500")
    assert Decimal(body["day_pnl_pct"]) == Decimal("0.025")


@pytest.mark.asyncio
async def test_get_portfolio_day_pnl_negative(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, UUID],
) -> None:
    tid = seed["tenant_id"]
    uid = seed["user_id"]
    today_midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    await _seed_equity_snapshot(
        sf,
        tenant_id=tid,
        account_equity=Decimal("100000"),
        created_at=today_midnight + timedelta(hours=9),
    )
    await _seed_equity_snapshot(
        sf,
        tenant_id=tid,
        account_equity=Decimal("99000"),
        created_at=today_midnight + timedelta(hours=14),
    )
    cookie = _login_cookie(uid, tid)
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/portfolio")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["day_pnl_abs"]) == Decimal("-1000")
    assert Decimal(body["day_pnl_pct"]) == Decimal("-0.01")


# ---------------------------------------------------------------------------
# GET /portfolio/equity/series (slice portfolio-pnl-and-equity-series)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_equity_series_empty_returns_empty_items(
    client: AsyncClient,
    seed: dict[str, UUID],
) -> None:
    cookie = _login_cookie(seed["user_id"], seed["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/portfolio/equity/series")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["next_cursor"] is None


@pytest.mark.asyncio
async def test_get_equity_series_returns_only_in_window(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
    seed: dict[str, UUID],
) -> None:
    tid = seed["tenant_id"]
    uid = seed["user_id"]
    now = datetime.now(UTC)
    await _seed_equity_snapshot(
        sf, tenant_id=tid, account_equity=Decimal("100"), created_at=now - timedelta(days=5)
    )
    await _seed_equity_snapshot(
        sf, tenant_id=tid, account_equity=Decimal("200"), created_at=now - timedelta(days=15)
    )
    await _seed_equity_snapshot(
        sf, tenant_id=tid, account_equity=Decimal("300"), created_at=now - timedelta(days=45)
    )
    cookie = _login_cookie(uid, tid)
    client.cookies.set(COOKIE_NAME, cookie)
    resp = await client.get("/api/v1/portfolio/equity/series?days=30")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    # Chronological ASC: -15d (200) then -5d (100).
    assert Decimal(body["items"][0]["account_equity"]) == Decimal("200")
    assert Decimal(body["items"][1]["account_equity"]) == Decimal("100")


@pytest.mark.asyncio
async def test_get_equity_series_clamps_days_param(
    client: AsyncClient,
    seed: dict[str, UUID],
) -> None:
    cookie = _login_cookie(seed["user_id"], seed["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie)
    resp_low = await client.get("/api/v1/portfolio/equity/series?days=0")
    assert resp_low.status_code == 422, resp_low.text
    resp_high = await client.get("/api/v1/portfolio/equity/series?days=400")
    assert resp_high.status_code == 422, resp_high.text


@pytest.mark.asyncio
async def test_equity_series_isolated_across_tenants(
    client: AsyncClient,
    sf: async_sessionmaker[AsyncSession],
) -> None:
    a = await _seed_tenant_user(sf, email="alice2@x.test", tenant_name="t-A2")
    b = await _seed_tenant_user(sf, email="bob2@x.test", tenant_name="t-B2")
    now = datetime.now(UTC)
    await _seed_equity_snapshot(
        sf,
        tenant_id=a["tenant_id"],
        account_equity=Decimal("12345"),
        created_at=now - timedelta(days=2),
    )
    cookie_b = _login_cookie(b["user_id"], b["tenant_id"])
    client.cookies.set(COOKIE_NAME, cookie_b)
    resp = await client.get("/api/v1/portfolio/equity/series")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0
