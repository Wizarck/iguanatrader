"""Unit tests for :class:`StrategyManager` (slice T3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from iguanatrader.contexts.trading.ports import (
    Bar,
    BarHistory,
    StrategyConfigSnapshot,
)
from iguanatrader.contexts.trading.strategies import StrategyManager
from iguanatrader.contexts.trading.strategies.manager import STRATEGY_REGISTRY


def _flat_history(n: int = 250) -> BarHistory:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    bars = tuple(
        Bar(
            timestamp=base + timedelta(days=i),
            open=Decimal("100"),
            high=Decimal("100.5"),
            low=Decimal("99.5"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        )
        for i in range(n)
    )
    return BarHistory(symbol="AAPL", bars=bars)


def test_registry_contains_canonical_kinds() -> None:
    assert "donchian_atr" in STRATEGY_REGISTRY
    assert "sma_cross" in STRATEGY_REGISTRY


def test_evaluate_all_skips_disabled_configs() -> None:
    manager = StrategyManager()
    config = StrategyConfigSnapshot(
        id=uuid4(),
        tenant_id=uuid4(),
        strategy_kind="donchian_atr",
        symbol="AAPL",
        params={},
        enabled=False,
        version=1,
    )
    results = manager.evaluate_all("AAPL", _flat_history(), [config])
    assert results == []


def test_evaluate_all_returns_empty_on_unknown_kind() -> None:
    manager = StrategyManager()
    config = StrategyConfigSnapshot(
        id=uuid4(),
        tenant_id=uuid4(),
        strategy_kind="not_a_real_strategy",
        symbol="AAPL",
        params={},
        enabled=True,
        version=1,
    )
    results = manager.evaluate_all("AAPL", _flat_history(), [config])
    assert results == []


def test_evaluate_all_caches_strategy_instance() -> None:
    manager = StrategyManager()
    config = StrategyConfigSnapshot(
        id=uuid4(),
        tenant_id=uuid4(),
        strategy_kind="donchian_atr",
        symbol="AAPL",
        params={},
        enabled=True,
        version=1,
    )
    manager.evaluate_all("AAPL", _flat_history(), [config])
    manager.evaluate_all("AAPL", _flat_history(), [config])
    # Same kind + version hits cache; only one entry per kind.
    assert len(manager._cache) == 1


def test_evaluate_all_invalidates_cache_on_version_bump() -> None:
    manager = StrategyManager()
    base_config = StrategyConfigSnapshot(
        id=uuid4(),
        tenant_id=uuid4(),
        strategy_kind="donchian_atr",
        symbol="AAPL",
        params={},
        enabled=True,
        version=1,
    )
    manager.evaluate_all("AAPL", _flat_history(), [base_config])
    bumped = StrategyConfigSnapshot(
        id=base_config.id,
        tenant_id=base_config.tenant_id,
        strategy_kind="donchian_atr",
        symbol="AAPL",
        params={},
        enabled=True,
        version=2,
    )
    manager.evaluate_all("AAPL", _flat_history(), [bumped])
    # Old version evicted; only the new one cached.
    assert len(manager._cache) == 1
    assert ("donchian_atr", 2) in manager._cache
