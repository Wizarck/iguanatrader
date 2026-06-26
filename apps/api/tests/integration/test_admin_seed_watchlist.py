"""Integration test for ``iguanatrader admin seed-watchlist`` (WS-B1).

Asserts the seed command's contract:

1. Dry run (default) prints the plan and writes NOTHING.
2. ``--apply`` seeds the full ``strategies x symbols`` grid, enabled.
3. ``--ucits-swap`` rewrites the 11 US ETFs to their UCITS tickers.
4. ``--wipe`` (default) soft-disables every pre-existing config first —
   configs absent from the new grid end up ``enabled=False`` (kept, not
   deleted); the new grid is ``enabled=True``.
5. ``--strategies`` accepts a subset; an unknown kind exits non-zero.
6. Unknown tenant slug exits non-zero.

These are SYNC test functions on purpose: the admin CLI calls
``asyncio.run`` internally, so driving it from inside a pytest-asyncio
event loop would raise ``asyncio.run() cannot be called from a running
event loop``. Running sync (CLI invoke + sequential ``asyncio.run``
read-backs) verifies the real command end-to-end against sqlite.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from iguanatrader.cli.admin import app as admin_app
from iguanatrader.contexts.trading.models import StrategyConfig
from iguanatrader.persistence import (
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import with_tenant_context
from sqlalchemy import select
from typer.testing import CliRunner

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(autouse=True)
def _listeners() -> Iterator[None]:
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()


@pytest.fixture
def prepared_db(tmp_path: Path) -> str:
    """Create a fresh sqlite schema and return its URL."""
    url = f"sqlite+aiosqlite:///{(tmp_path / 'ig_seed_test.db').as_posix()}"

    async def _create() -> None:
        eng = engine_factory(url)
        try:
            async with eng.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await eng.dispose()

    asyncio.run(_create())
    return url


def _run_admin(db_url: str, *args: str, monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    monkeypatch.setenv("IGUANA_DATABASE_URL", db_url)
    runner = CliRunner()
    result = runner.invoke(admin_app, list(args))
    output = result.output or ""
    if result.exception is not None and not isinstance(result.exception, SystemExit):
        import traceback

        output += "\n\n--- exception ---\n" + "".join(
            traceback.format_exception(
                type(result.exception), result.exception, result.exception.__traceback__
            )
        )
    return result.exit_code, output


def _bootstrap(db_url: str, slug: str, monkeypatch: pytest.MonkeyPatch) -> None:
    code, output = _run_admin(
        db_url,
        "bootstrap-tenant",
        slug,
        "--email",
        f"{slug}@example.com",
        "--password",
        "p1",
        monkeypatch=monkeypatch,
    )
    assert code == 0, output


def _read_configs(db_url: str, slug: str) -> list[tuple[str, str, bool, dict[str, object]]]:
    """Read back configs as plain tuples (detached from the session)."""

    async def _go() -> list[tuple[str, str, bool, dict[str, object]]]:
        eng = engine_factory(db_url)
        try:
            factory = session_factory(eng)
            async with factory() as session:
                tenant = (
                    (await session.execute(select(Tenant).where(Tenant.name == slug)))
                    .scalars()
                    .first()
                )
                assert tenant is not None
                async with with_tenant_context(tenant.id):
                    rows = (await session.execute(select(StrategyConfig))).scalars().all()
                    return [
                        (r.strategy_kind, r.symbol, bool(r.enabled), dict(r.params)) for r in rows
                    ]
        finally:
            await eng.dispose()

    return asyncio.run(_go())


def _plant_config(db_url: str, slug: str, *, kind: str, symbol: str) -> None:
    async def _go() -> None:
        eng = engine_factory(db_url)
        try:
            factory = session_factory(eng)
            async with factory() as session:
                tenant = (
                    (await session.execute(select(Tenant).where(Tenant.name == slug)))
                    .scalars()
                    .first()
                )
                assert tenant is not None
                async with with_tenant_context(tenant.id):
                    session.add(
                        StrategyConfig(
                            id=uuid4(),
                            tenant_id=tenant.id,
                            strategy_kind=kind,
                            symbol=symbol,
                            params={"legacy": True},
                            enabled=True,
                            version=1,
                        )
                    )
                    await session.commit()
        finally:
            await eng.dispose()

    asyncio.run(_go())


_ALL_KINDS = {
    "bollinger_breakout",
    "donchian_atr",
    "macd_cross",
    "rsi_mean_reversion",
    "sma_cross",
    "volume_donchian",
}


def test_dry_run_writes_nothing(prepared_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _bootstrap(prepared_db, "arturo-trading", monkeypatch)

    code, output = _run_admin(
        prepared_db,
        "seed-watchlist",
        "--tenant",
        "arturo-trading",
        "--symbols",
        "AMD,NVDA",
        monkeypatch=monkeypatch,
    )
    assert code == 0, output
    assert "DRY RUN" in output
    assert "= 12 configs" in output  # 6 strategies x 2 symbols

    assert _read_configs(prepared_db, "arturo-trading") == []


def test_apply_seeds_full_grid_enabled(prepared_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _bootstrap(prepared_db, "arturo-trading", monkeypatch)

    code, output = _run_admin(
        prepared_db,
        "seed-watchlist",
        "--tenant",
        "arturo-trading",
        "--symbols",
        "AMD,NVDA,XOM",
        "--apply",
        monkeypatch=monkeypatch,
    )
    assert code == 0, output
    assert "OK — seeded 18 configs" in output

    rows = _read_configs(prepared_db, "arturo-trading")
    assert len(rows) == 18
    assert all(enabled for _, _, enabled, _ in rows)
    assert all(params == {} for *_, params in rows)
    assert {sym for _, sym, _, _ in rows} == {"AMD", "NVDA", "XOM"}
    assert {kind for kind, _, _, _ in rows} == _ALL_KINDS
    assert len({(kind, sym) for kind, sym, _, _ in rows}) == 18


def test_ucits_swap_rewrites_us_etfs(prepared_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _bootstrap(prepared_db, "arturo-trading", monkeypatch)

    code, output = _run_admin(
        prepared_db,
        "seed-watchlist",
        "--tenant",
        "arturo-trading",
        "--symbols",
        "SPY,GLD,AMD",  # 2 US ETFs + 1 stock
        "--ucits-swap",
        "--strategies",
        "donchian_atr",
        "--apply",
        monkeypatch=monkeypatch,
    )
    assert code == 0, output

    symbols = {sym for _, sym, _, _ in _read_configs(prepared_db, "arturo-trading")}
    # SPY→VUSA, GLD→IGLN; the stock passes through; ZERO US ETFs remain.
    assert symbols == {"VUSA", "IGLN", "AMD"}
    assert "SPY" not in symbols and "GLD" not in symbols


def test_wipe_disables_preexisting_then_reseeds(
    prepared_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap(prepared_db, "arturo-trading", monkeypatch)
    # Plant a stale config for a symbol NOT in the new grid (SLV, a US ETF
    # the live reseed drops) — it must end up disabled, not deleted.
    _plant_config(prepared_db, "arturo-trading", kind="donchian_atr", symbol="SLV")

    code, output = _run_admin(
        prepared_db,
        "seed-watchlist",
        "--tenant",
        "arturo-trading",
        "--symbols",
        "AMD",
        "--strategies",
        "donchian_atr",
        "--apply",
        monkeypatch=monkeypatch,
    )
    assert code == 0, output

    by_symbol = {
        sym: enabled for _, sym, enabled, _ in _read_configs(prepared_db, "arturo-trading")
    }
    assert by_symbol.get("SLV") is False  # preserved (audit) but disabled
    assert by_symbol.get("AMD") is True  # new config enabled


def test_unknown_strategy_exits_non_zero(prepared_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _bootstrap(prepared_db, "arturo-trading", monkeypatch)
    code, output = _run_admin(
        prepared_db,
        "seed-watchlist",
        "--tenant",
        "arturo-trading",
        "--symbols",
        "AMD",
        "--strategies",
        "not_a_strategy",
        monkeypatch=monkeypatch,
    )
    assert code == 2
    assert "unknown strategy" in output


def test_unknown_tenant_exits_non_zero(prepared_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    code, output = _run_admin(
        prepared_db,
        "seed-watchlist",
        "--tenant",
        "ghost",
        "--symbols",
        "AMD",
        "--apply",
        monkeypatch=monkeypatch,
    )
    assert code != 0
    assert "not found" in output
