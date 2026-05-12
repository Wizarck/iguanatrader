"""Hypothesis property tests for :meth:`RiskService._proposal_created_handler`.

Slice ``property-tests-bus-bridge-handlers``. Companion to
``test_propose_event_emission`` (PR #112) — covers the next hop in the
propose→risk→approve→execute bus chain.

Three invariants under test (50 examples each):

1. Strategy returns a permissive decision → exactly 1
   :class:`ProposalRiskEvaluated` event on the bus with matching
   ``proposal_id`` + ``tenant_id``.
2. :class:`KillSwitchActiveError` raised by ``evaluate_proposal`` →
   exactly 1 event with ``outcome='reject'`` + ``cap_type_breached='kill_switch'``.
3. ``TradeProposalRepository.get_by_id`` returns ``None`` (proposal was
   deleted between publish + handle) → ZERO events published.

Marker: ``@pytest.mark.property``. NOT ``ci_blocking`` — emission contract
is already covered by unit tests; this is the regression net catching
edge cases on random ``ProposalCreated`` event payloads.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from iguanatrader.contexts.risk.models import CapType, Decision, Outcome
from iguanatrader.contexts.risk.service import RiskService
from iguanatrader.contexts.trading.events import ProposalCreated, ProposalRiskEvaluated
from iguanatrader.shared.errors import KillSwitchActiveError
from iguanatrader.shared.messagebus import MessageBus


@dataclass
class _FakeProposalRow:
    id: UUID
    tenant_id: UUID
    side: str
    quantity: Decimal
    entry_price_indicative: Decimal


class _FakeProposalRepository:
    def __init__(self, *, row: _FakeProposalRow | None) -> None:
        self._row = row
        self.calls: list[UUID] = []

    async def get_by_id(self, proposal_id: UUID) -> _FakeProposalRow | None:
        self.calls.append(proposal_id)
        return self._row


async def _drain(*, ticks: int = 5) -> None:
    for _ in range(ticks):
        await asyncio.sleep(0)


def _wire_repo(monkeypatch: Any, repo: _FakeProposalRepository) -> None:
    # The handler constructs `TradeProposalRepository()` inline — swap the
    # class for one whose constructor returns our fake.
    def _factory(*_: object, **__: object) -> _FakeProposalRepository:
        return repo

    monkeypatch.setattr(
        "iguanatrader.contexts.trading.repository.TradeProposalRepository",
        _factory,
    )


# Decision constraint (see Decision validator): ``cap_type_breached`` is
# None iff ``outcome == "allow"``. The Hypothesis composite below generates
# valid (outcome, cap_type_breached) pairs that satisfy the invariant.
_VALID_CAP_TYPES = ["per_trade", "daily_loss", "weekly_loss", "max_open", "max_drawdown"]


@st.composite
def _decision_pairs(draw: st.DrawFn) -> tuple[str, str | None]:
    outcome = draw(st.sampled_from(["allow", "reject", "clip"]))
    if outcome == "allow":
        return (outcome, None)
    return (outcome, draw(st.sampled_from(_VALID_CAP_TYPES)))


@pytest.mark.property
@given(
    side=st.sampled_from(["buy", "sell"]),
    quantity_raw=st.floats(
        min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False
    ),
    entry_raw=st.floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    decision_pair=_decision_pairs(),
)
@settings(
    deadline=None,
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_handler_emits_one_event_when_proposal_exists(
    side: str,
    quantity_raw: float,
    entry_raw: float,
    decision_pair: tuple[str, str | None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """For any persisted proposal + any decision, exactly 1 ProposalRiskEvaluated."""
    outcome, cap_type_breached = decision_pair

    async def _run() -> None:
        tenant_id = uuid4()
        proposal_id = uuid4()
        row = _FakeProposalRow(
            id=proposal_id,
            tenant_id=tenant_id,
            side=side,
            quantity=Decimal(str(round(quantity_raw, 4))),
            entry_price_indicative=Decimal(str(round(entry_raw, 4))),
        )
        repo = _FakeProposalRepository(row=row)
        _wire_repo(monkeypatch, repo)

        captured: list[ProposalRiskEvaluated] = []

        async def _capture(evt: ProposalRiskEvaluated) -> None:
            captured.append(evt)

        bus = MessageBus()
        bus.subscribe(ProposalRiskEvaluated, _capture)

        # Risk repository isn't used by _proposal_created_handler directly
        # (the handler calls service.evaluate_proposal which uses it); we
        # patch evaluate_proposal to return a deterministic decision.
        service = RiskService(repository=object(), bus=bus)  # type: ignore[arg-type]

        async def _fake_evaluate(_inp: Any) -> tuple[None, Decision]:
            return (
                None,
                Decision(
                    outcome=cast(Outcome, outcome),
                    cap_type_breached=cast("CapType | None", cap_type_breached),
                ),
            )

        monkeypatch.setattr(service, "evaluate_proposal", _fake_evaluate)

        event = ProposalCreated(
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            symbol="SPY",
            strategy_kind="fake",
            strategy_version=1,
            correlation_id=uuid4(),
        )
        await service._proposal_created_handler(event)
        await _drain()
        await bus.aclose()

        assert len(captured) == 1, f"Expected 1 ProposalRiskEvaluated, got {len(captured)}"
        assert captured[0].proposal_id == proposal_id
        assert captured[0].tenant_id == tenant_id
        assert captured[0].outcome == outcome
        assert captured[0].cap_type_breached == cap_type_breached
        assert repo.calls == [proposal_id]

    asyncio.run(_run())


@pytest.mark.property
@given(
    side=st.sampled_from(["buy", "sell"]),
    quantity_raw=st.floats(
        min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False
    ),
    entry_raw=st.floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
)
@settings(
    deadline=None,
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_handler_kill_switch_emits_reject_with_kill_switch_cap(
    side: str,
    quantity_raw: float,
    entry_raw: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KillSwitchActiveError → exactly 1 reject event with cap='kill_switch'."""

    async def _run() -> None:
        tenant_id = uuid4()
        proposal_id = uuid4()
        row = _FakeProposalRow(
            id=proposal_id,
            tenant_id=tenant_id,
            side=side,
            quantity=Decimal(str(round(quantity_raw, 4))),
            entry_price_indicative=Decimal(str(round(entry_raw, 4))),
        )
        repo = _FakeProposalRepository(row=row)
        _wire_repo(monkeypatch, repo)

        captured: list[ProposalRiskEvaluated] = []

        async def _capture(evt: ProposalRiskEvaluated) -> None:
            captured.append(evt)

        bus = MessageBus()
        bus.subscribe(ProposalRiskEvaluated, _capture)

        service = RiskService(repository=object(), bus=bus)  # type: ignore[arg-type]

        async def _raise_kill_switch(_inp: Any) -> tuple[None, Decision]:
            raise KillSwitchActiveError("kill switch active")

        monkeypatch.setattr(service, "evaluate_proposal", _raise_kill_switch)

        event = ProposalCreated(
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            symbol="SPY",
            strategy_kind="fake",
            strategy_version=1,
            correlation_id=uuid4(),
        )
        await service._proposal_created_handler(event)
        await _drain()
        await bus.aclose()

        assert len(captured) == 1
        assert captured[0].outcome == "reject"
        assert captured[0].cap_type_breached == "kill_switch"
        assert captured[0].proposal_id == proposal_id

    asyncio.run(_run())


@pytest.mark.property
@given(proposal_uuid_bytes=st.binary(min_size=16, max_size=16))
@settings(
    deadline=None,
    max_examples=30,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_handler_missing_proposal_emits_nothing(
    proposal_uuid_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If TradeProposalRepository.get_by_id returns None, ZERO events published."""

    async def _run() -> None:
        proposal_id = UUID(bytes=proposal_uuid_bytes)
        tenant_id = uuid4()

        repo = _FakeProposalRepository(row=None)
        _wire_repo(monkeypatch, repo)

        captured: list[ProposalRiskEvaluated] = []

        async def _capture(evt: ProposalRiskEvaluated) -> None:
            captured.append(evt)

        bus = MessageBus()
        bus.subscribe(ProposalRiskEvaluated, _capture)

        service = RiskService(repository=object(), bus=bus)  # type: ignore[arg-type]

        # evaluate_proposal MUST NOT be called when the row is missing —
        # patch it to assert that invariant by raising on entry.
        async def _should_not_run(_inp: Any) -> tuple[None, Decision]:
            raise AssertionError("evaluate_proposal called when row was missing")

        monkeypatch.setattr(service, "evaluate_proposal", _should_not_run)

        event = ProposalCreated(
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            symbol="SPY",
            strategy_kind="fake",
            strategy_version=1,
            correlation_id=uuid4(),
        )
        await service._proposal_created_handler(event)
        await _drain()
        await bus.aclose()

        assert captured == []
        assert repo.calls == [proposal_id]

    asyncio.run(_run())
