"""Integration tests — risk engine flow through the service layer.

Tests the happy + reject + override paths end-to-end with a real
SQLite + the real :class:`RiskService` + a fake-but-typed
:class:`RiskRepositoryPort` adapter that exposes the persisted rows
for assertion.

The suite re-uses the slice-4 ``app_with_overrides`` + ``client``
fixtures from ``apps/api/tests/integration/conftest.py`` for the
schema setup, then injects a tenant + user via ``seeded_tenant_user``.

Why not Alembic? — The shared conftest builds the schema via
``Base.metadata.create_all`` (per the docstring "NOT via Alembic — the
integration suite is schema-shape-tested by the persistence
package"). The risk ORM models are auto-imported when this test
module imports them, so SQLAlchemy registers their tables on the
shared ``metadata`` and ``create_all`` builds them too.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.risk.models import (
    Confirmation,
    ConfirmationChain,
    RiskState,
    TradeProposalInput,
)

# Importing the ORM module registers the risk tables on the shared
# Base.metadata so the conftest's Base.metadata.create_all builds them.
from iguanatrader.contexts.risk.orm import (  # noqa: F401
    KillSwitchEventORM,
    KillSwitchStateORM,
    RiskEvaluationORM,
    RiskOverrideORM,
)
from iguanatrader.contexts.risk.repository import RiskRepository
from iguanatrader.contexts.risk.service import RiskService
from iguanatrader.shared.contextvars import with_tenant_context
from iguanatrader.shared.errors import (
    KillSwitchActiveError,
    OverrideAuditMissingError,
)
from iguanatrader.shared.time import now as utc_now
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _PatchedRepo(RiskRepository):
    """Repository override that returns a populated state for tests.

    The base :class:`RiskRepository.load_risk_state` returns a neutral
    default until T1+O1 land. Tests that need a non-trivial state
    inject this patched repo with a known state.
    """

    def __init__(self, session: AsyncSession, state: RiskState) -> None:
        super().__init__(session)
        self._stub_state = state

    async def load_risk_state(self, tenant_id: UUID) -> RiskState:
        return self._stub_state


@pytest.fixture
async def session(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session with the K1 schema applied."""
    async with schema_session_factory() as s:
        yield s


@pytest.mark.integration
async def test_evaluate_proposal_happy_path_persists_evaluation(
    session: AsyncSession,
    seeded_tenant_user: dict[str, str],
) -> None:
    """Allow path: row is INSERTed with ``outcome='allow'``."""
    tenant_id = UUID(seeded_tenant_user["tenant_id"])
    state = RiskState(capital=Decimal("100000"))
    repo = _PatchedRepo(session, state)

    async with with_tenant_context(tenant_id):
        service = RiskService(repository=repo)
        proposal = TradeProposalInput(
            id=uuid4(),
            tenant_id=tenant_id,
            notional_value=Decimal("1000"),  # 1% — within 2% per_trade cap
            side="buy",
        )
        evaluation_id, decision = await service.evaluate_proposal(proposal)
        await session.commit()

        assert decision.outcome == "allow"
        row = (
            await session.execute(
                select(RiskEvaluationORM).where(RiskEvaluationORM.id == evaluation_id)
            )
        ).scalar_one()
        assert row.outcome == "allow"
        assert row.proposal_id == proposal.id


@pytest.mark.integration
async def test_evaluate_proposal_reject_path_persists_with_breach(
    session: AsyncSession,
    seeded_tenant_user: dict[str, str],
) -> None:
    """Reject path: ``outcome='reject'`` + ``cap_type_breached='per_trade'``."""
    tenant_id = UUID(seeded_tenant_user["tenant_id"])
    state = RiskState(capital=Decimal("100000"))
    repo = _PatchedRepo(session, state)

    async with with_tenant_context(tenant_id):
        service = RiskService(repository=repo)
        proposal = TradeProposalInput(
            id=uuid4(),
            tenant_id=tenant_id,
            notional_value=Decimal("5000"),  # 5% — exceeds 2% per_trade
            side="buy",
        )
        evaluation_id, decision = await service.evaluate_proposal(proposal)
        await session.commit()

        assert decision.outcome == "reject"
        assert decision.cap_type_breached == "per_trade"
        row = (
            await session.execute(
                select(RiskEvaluationORM).where(RiskEvaluationORM.id == evaluation_id)
            )
        ).scalar_one()
        assert row.outcome == "reject"
        assert row.cap_type_breached == "per_trade"


@pytest.mark.integration
async def test_evaluate_proposal_kill_switch_active_raises(
    session: AsyncSession,
    seeded_tenant_user: dict[str, str],
) -> None:
    """Active kill-switch raises before engine is even called."""
    tenant_id = UUID(seeded_tenant_user["tenant_id"])
    repo = _PatchedRepo(session, RiskState(capital=Decimal("100000")))

    async with with_tenant_context(tenant_id):
        service = RiskService(repository=repo)
        await service.activate_kill_switch(
            tenant_id=tenant_id,
            source="cli",
            actor_user_id=None,
            reason="test halt for kill-switch gate verification",
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


@pytest.mark.integration
async def test_record_override_persists_full_audit_metadata(
    session: AsyncSession,
    seeded_tenant_user: dict[str, str],
) -> None:
    """Valid override produces a row with all audit fields populated."""
    tenant_id = UUID(seeded_tenant_user["tenant_id"])
    user_id = UUID(seeded_tenant_user["user_id"])
    repo = _PatchedRepo(session, RiskState(capital=Decimal("100000")))

    async with with_tenant_context(tenant_id):
        service = RiskService(repository=repo)
        # Need a parent risk_evaluation row — generate via a reject.
        proposal = TradeProposalInput(
            id=uuid4(),
            tenant_id=tenant_id,
            notional_value=Decimal("5000"),
            side="buy",
        )
        eval_id, _ = await service.evaluate_proposal(proposal)

        chain = ConfirmationChain(
            first_confirmation=Confirmation(
                channel="cli",
                at=utc_now(),
                actor_user_id=user_id,
            ),
            second_confirmation=Confirmation(
                channel="cli",
                at=utc_now(),
                actor_user_id=user_id,
            ),
        )
        override_id = await service.record_override(
            tenant_id=tenant_id,
            proposal_id=proposal.id,
            risk_evaluation_id=eval_id,
            authorised_by_user_id=user_id,
            reason_text="Earnings beat justifies a one-off bypass for AAPL.",
            confirmation_chain=chain,
            state_snapshot_at_override={"capital": "100000"},
        )
        await session.commit()

        row = (
            await session.execute(select(RiskOverrideORM).where(RiskOverrideORM.id == override_id))
        ).scalar_one()
        assert row.authorised_by_user_id == user_id
        assert len(row.reason_text) >= 20
        assert row.risk_evaluation_id == eval_id


@pytest.mark.integration
async def test_record_override_short_reason_raises(
    session: AsyncSession,
    seeded_tenant_user: dict[str, str],
) -> None:
    """``OverrideAuditMissingError`` raised before any DB write."""
    tenant_id = UUID(seeded_tenant_user["tenant_id"])
    user_id = UUID(seeded_tenant_user["user_id"])
    repo = _PatchedRepo(session, RiskState(capital=Decimal("100000")))

    async with with_tenant_context(tenant_id):
        service = RiskService(repository=repo)
        chain = ConfirmationChain(
            first_confirmation=Confirmation(
                channel="cli",
                at=utc_now(),
                actor_user_id=user_id,
            ),
            second_confirmation=Confirmation(
                channel="cli",
                at=utc_now(),
                actor_user_id=user_id,
            ),
        )
        with pytest.raises(OverrideAuditMissingError):
            await service.record_override(
                tenant_id=tenant_id,
                proposal_id=uuid4(),
                risk_evaluation_id=uuid4(),
                authorised_by_user_id=user_id,
                reason_text="too short",  # 9 chars — below floor
                confirmation_chain=chain,
                state_snapshot_at_override={},
            )
