"""``StrategyConfigRepository`` is the only repository with concrete
methods in slice T1 (FR2/FR3). The cross-tenant isolation invariant is
already covered by the slice-3 ``test_tenant_isolation.py``; this file
adds a smoke that the trading repositories instantiate cleanly +
``StrategyConfigRepository.upsert`` raises ``LookupError`` when no
tenant is bound.
"""

from __future__ import annotations

import pytest

from iguanatrader.contexts.trading.repository import (
    EquitySnapshotRepository,
    FillRepository,
    OrderRepository,
    StrategyConfigRepository,
    TradeProposalRepository,
    TradeRepository,
)
from iguanatrader.shared.contextvars import tenant_id_var


def test_repositories_instantiate_cleanly() -> None:
    # No session bound — instantiating the repository class is fine; only
    # accessing ``.session`` would raise.
    for cls in (
        StrategyConfigRepository,
        TradeProposalRepository,
        TradeRepository,
        OrderRepository,
        FillRepository,
        EquitySnapshotRepository,
    ):
        instance = cls()
        assert instance is not None


@pytest.mark.asyncio
async def test_strategy_config_upsert_raises_when_no_tenant_bound() -> None:
    """``upsert`` reads ``tenant_id_var`` and raises if it's unset."""
    repo = StrategyConfigRepository()
    # tenant_id_var default is None in a fresh context.
    with pytest.raises(LookupError):
        await repo.upsert(
            symbol="SPY",
            strategy_kind="donchian_atr",
            params={"lookback": 20},
            enabled=True,
        )


@pytest.mark.asyncio
async def test_strategy_config_upsert_reads_tenant_id_var() -> None:
    """When ``tenant_id_var`` is set the repository tries to use the
    session — which raises ``LookupError`` here because no session is
    bound. The test verifies ``upsert`` reaches the session-pull step
    (i.e. the tenant guard passed).
    """
    from uuid import uuid4

    repo = StrategyConfigRepository()
    token = tenant_id_var.set(uuid4())
    try:
        with pytest.raises(LookupError, match="session_var"):
            await repo.upsert(
                symbol="SPY",
                strategy_kind="donchian_atr",
                params={"lookback": 20},
                enabled=True,
            )
    finally:
        tenant_id_var.reset(token)
