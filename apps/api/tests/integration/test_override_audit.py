"""Override audit — service-layer validation + DB-CHECK fallthrough.

Per slice K1 spec scenarios "Override with 19-char reason rejected at
service layer" + design D5 "service-layer raises OverrideAuditMissingError
if any field is empty/short before persistence".

Also verifies the DB-level CHECK is the second-line guarantee — a raw
SQL INSERT bypassing the service-layer validator should still fail at
the DB.
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
)
from iguanatrader.contexts.risk.orm import (  # noqa: F401
    KillSwitchEventORM,
    KillSwitchStateORM,
    RiskEvaluationORM,
    RiskOverrideORM,
)
from iguanatrader.contexts.risk.repository import RiskRepository
from iguanatrader.contexts.risk.service import RiskService
from iguanatrader.shared.contextvars import with_tenant_context
from iguanatrader.shared.errors import OverrideAuditMissingError
from iguanatrader.shared.time import now as utc_now
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _StubRepo(RiskRepository):
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


def _make_chain(actor: UUID) -> ConfirmationChain:
    now = utc_now()
    return ConfirmationChain(
        first_confirmation=Confirmation(channel="cli", at=now, actor_user_id=actor),
        second_confirmation=Confirmation(channel="cli", at=now, actor_user_id=actor),
    )


@pytest.mark.integration
async def test_record_override_19_char_reason_raises(
    session: AsyncSession,
    seeded_tenant_user: dict[str, str],
) -> None:
    """19-char reason → ``OverrideAuditMissingError`` at service layer."""
    tenant_id = UUID(seeded_tenant_user["tenant_id"])
    user_id = UUID(seeded_tenant_user["user_id"])
    repo = _StubRepo(session, RiskState(capital=Decimal("100000")))

    async with with_tenant_context(tenant_id):
        service = RiskService(repository=repo)
        with pytest.raises(OverrideAuditMissingError):
            await service.record_override(
                tenant_id=tenant_id,
                proposal_id=uuid4(),
                risk_evaluation_id=uuid4(),
                authorised_by_user_id=user_id,
                reason_text="x" * 19,
                confirmation_chain=_make_chain(user_id),
                state_snapshot_at_override={},
            )


@pytest.mark.integration
async def test_record_override_nil_user_raises(
    session: AsyncSession,
    seeded_tenant_user: dict[str, str],
) -> None:
    """Nil-UUID user → service-layer rejects."""
    tenant_id = UUID(seeded_tenant_user["tenant_id"])
    user_id = UUID(seeded_tenant_user["user_id"])
    repo = _StubRepo(session, RiskState(capital=Decimal("100000")))

    async with with_tenant_context(tenant_id):
        service = RiskService(repository=repo)
        with pytest.raises(OverrideAuditMissingError):
            await service.record_override(
                tenant_id=tenant_id,
                proposal_id=uuid4(),
                risk_evaluation_id=uuid4(),
                authorised_by_user_id=UUID(int=0),
                reason_text="A perfectly valid reason that exceeds the 20-char floor",
                confirmation_chain=_make_chain(user_id),
                state_snapshot_at_override={},
            )


@pytest.mark.integration
async def test_db_check_constraint_rejects_short_reason_via_raw_sql(
    session: AsyncSession,
    seeded_tenant_user: dict[str, str],
) -> None:
    """L2 defence: raw SQL bypassing the service is caught by the DB CHECK.

    Per design D5 "DB-level CHECK is the last-line guarantee".
    Raw SQL via ``text()`` bypasses the slice-3 ORM listener (gotcha
    #23) AND the service-layer validator — the only thing left is
    the CHECK constraint, which MUST refuse the row.
    """
    tenant_id = UUID(seeded_tenant_user["tenant_id"])
    user_id = UUID(seeded_tenant_user["user_id"])

    sql = text(
        "INSERT INTO risk_overrides ("
        "id, tenant_id, proposal_id, risk_evaluation_id, "
        "authorised_by_user_id, reason_text, confirmation_chain, "
        "state_snapshot_at_override, created_at"
        ") VALUES ("
        ":id, :tenant_id, :proposal_id, :risk_evaluation_id, "
        ":authorised_by_user_id, :reason_text, :confirmation_chain, "
        ":state_snapshot_at_override, :created_at"
        ")"
    )

    # First create a parent risk_evaluation row so the FK is satisfied.
    eval_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO risk_evaluations ("
            "id, tenant_id, proposal_id, outcome, state_snapshot, created_at"
            ") VALUES (:id, :tenant_id, :proposal_id, :outcome, :state_snapshot, :created_at)"
        ),
        {
            "id": eval_id.hex,
            "tenant_id": tenant_id.hex,
            "proposal_id": uuid4().hex,
            "outcome": "reject",
            "state_snapshot": "{}",
            "created_at": utc_now(),
        },
    )

    with pytest.raises(IntegrityError):
        await session.execute(
            sql,
            {
                "id": uuid4().hex,
                "tenant_id": tenant_id.hex,
                "proposal_id": uuid4().hex,
                "risk_evaluation_id": eval_id.hex,
                "authorised_by_user_id": user_id.hex,
                "reason_text": "short",  # < 20 chars
                "confirmation_chain": "{}",
                "state_snapshot_at_override": "{}",
                "created_at": utc_now(),
            },
        )
        await session.flush()
