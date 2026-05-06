"""NFR-R5 assertion — kill-switch propagation under 2 seconds.

Per slice K1 spec scenario "CLI halt propagates to next evaluate()
call within 2s": activate the kill-switch, then call
``service.evaluate_proposal`` and assert the wall-clock latency
between the two operations is below the NFR-R5 budget.

The actual wall-clock is dominated by SQLite write + cache update;
on a modern laptop this is sub-millisecond. The 2s budget is the
worst-case allowance for slow CI runners + filesystem fsync.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.risk.models import RiskState, TradeProposalInput
from iguanatrader.contexts.risk.orm import (  # noqa: F401  — register risk tables
    KillSwitchEventORM,
    KillSwitchStateORM,
    RiskEvaluationORM,
    RiskOverrideORM,
)
from iguanatrader.contexts.risk.repository import RiskRepository
from iguanatrader.contexts.risk.service import RiskService
from iguanatrader.shared.contextvars import with_tenant_context
from iguanatrader.shared.errors import KillSwitchActiveError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

#: NFR-R5 budget. Wall-clock latency between activation and first
#: refused trade must be at-or-below this.
_NFR_R5_BUDGET_SECONDS: float = 2.0


class _StubRepo(RiskRepository):
    """Stub repository returning a known state — same shape as the test_flow stub."""

    def __init__(self, session: AsyncSession, state: RiskState) -> None:
        super().__init__(session)
        self._stub_state = state

    async def load_risk_state(self, tenant_id: UUID) -> RiskState:
        return self._stub_state


@pytest.fixture
async def session(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with schema_session_factory() as s:
        yield s


@pytest.mark.integration
async def test_kill_switch_propagates_under_nfr_r5_budget(
    session: AsyncSession,
    seeded_tenant_user: dict[str, str],
) -> None:
    """Activate-to-refusal wall-clock latency MUST be < 2s (NFR-R5)."""
    tenant_id = UUID(seeded_tenant_user["tenant_id"])
    repo = _StubRepo(session, RiskState(capital=Decimal("100000")))

    async with with_tenant_context(tenant_id):
        service = RiskService(repository=repo)

        t_activate = time.monotonic()
        await service.activate_kill_switch(
            tenant_id=tenant_id,
            source="cli",
            actor_user_id=None,
            reason="latency test for NFR-R5 verification path",
        )
        await session.commit()

        proposal = TradeProposalInput(
            id=uuid4(),
            tenant_id=tenant_id,
            notional_value=Decimal("100"),
            side="buy",
        )
        with pytest.raises(KillSwitchActiveError):
            await service.evaluate_proposal(proposal)
        elapsed = time.monotonic() - t_activate

        assert elapsed < _NFR_R5_BUDGET_SECONDS, (
            f"NFR-R5 violated: activate→refusal wall-clock = {elapsed:.3f}s, "
            f"budget {_NFR_R5_BUDGET_SECONDS}s"
        )
