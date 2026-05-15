"""Unit tests for :class:`RiskService` bus bridge (slice K1-followup §2).

The bridge `register_subscriptions` + `_proposal_created_handler` close
the propose→risk hop in the T1 archived event pipeline. These tests
mock both the trading-context repository (so we don't need a real
sqlite + ORM round-trip) and `evaluate_proposal` (so we don't
exercise the engine's full state-loading path).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from iguanatrader.contexts.risk.models import Decision, TradeProposalInput
from iguanatrader.contexts.risk.service import RiskService
from iguanatrader.contexts.trading.events import (
    ProposalCreated,
    ProposalRiskEvaluated,
)
from iguanatrader.shared.errors import IguanaError
from iguanatrader.shared.messagebus import MessageBus


class _StubKillSwitchActiveError(IguanaError):
    """Local stand-in matching the K1 KillSwitchActiveError contract."""


@pytest.fixture
def event() -> ProposalCreated:
    return ProposalCreated(
        tenant_id=uuid4(),
        proposal_id=uuid4(),
        symbol="AAPL",
        strategy_kind="donchian_atr",
        strategy_version=1,
        correlation_id=uuid4(),
    )


@pytest.fixture
def fake_proposal_row(event: ProposalCreated) -> SimpleNamespace:
    return SimpleNamespace(
        id=event.proposal_id,
        tenant_id=event.tenant_id,
        symbol="AAPL",
        side="buy",
        quantity=Decimal("10"),
        entry_price_indicative=Decimal("150.00"),
    )


@pytest.fixture
def bus() -> MessageBus:
    return MessageBus()


@pytest.fixture
def risk_service(bus: MessageBus) -> RiskService:
    repo = AsyncMock()
    return RiskService(repository=repo, bus=bus)


@pytest.mark.asyncio
async def test_bridge_publishes_proposal_risk_evaluated_on_allow(
    risk_service: RiskService,
    bus: MessageBus,
    event: ProposalCreated,
    fake_proposal_row: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allow path: handler emits ProposalRiskEvaluated(outcome='allow')."""
    captured: list[Any] = []

    async def _capture(evt: ProposalRiskEvaluated) -> None:
        captured.append(evt)

    bus.subscribe(ProposalRiskEvaluated, _capture)

    async def _fake_get_by_id(_self: object, _proposal_id: object) -> object:
        return fake_proposal_row

    monkeypatch.setattr(
        "iguanatrader.contexts.trading.repository.TradeProposalRepository.get_by_id",
        _fake_get_by_id,
    )
    monkeypatch.setattr(
        risk_service,
        "evaluate_proposal",
        AsyncMock(return_value=(uuid4(), Decision(outcome="allow"))),
    )

    await risk_service._proposal_created_handler(event)
    # Drain bus queues.
    for _ in range(10):
        import asyncio

        await asyncio.sleep(0)

    assert len(captured) == 1
    assert captured[0].outcome == "allow"
    assert captured[0].cap_type_breached is None
    assert captured[0].proposal_id == event.proposal_id


@pytest.mark.asyncio
async def test_bridge_publishes_proposal_risk_evaluated_on_reject(
    risk_service: RiskService,
    bus: MessageBus,
    event: ProposalCreated,
    fake_proposal_row: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject path: handler emits ProposalRiskEvaluated(outcome='reject', cap_type_breached='daily')."""
    import asyncio

    captured: list[Any] = []

    async def _capture(evt: ProposalRiskEvaluated) -> None:
        captured.append(evt)

    bus.subscribe(ProposalRiskEvaluated, _capture)

    async def _fake_get_by_id(_self: object, _proposal_id: object) -> object:
        return fake_proposal_row

    monkeypatch.setattr(
        "iguanatrader.contexts.trading.repository.TradeProposalRepository.get_by_id",
        _fake_get_by_id,
    )
    monkeypatch.setattr(
        risk_service,
        "evaluate_proposal",
        AsyncMock(
            return_value=(
                uuid4(),
                Decision(outcome="reject", cap_type_breached="daily_loss"),
            )
        ),
    )

    await risk_service._proposal_created_handler(event)
    for _ in range(10):
        await asyncio.sleep(0)

    assert len(captured) == 1
    assert captured[0].outcome == "reject"
    assert captured[0].cap_type_breached == "daily_loss"


@pytest.mark.asyncio
async def test_bridge_swallows_kill_switch_error_and_publishes_reject(
    risk_service: RiskService,
    bus: MessageBus,
    event: ProposalCreated,
    fake_proposal_row: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kill-switch path: KillSwitchActiveError → ProposalRiskEvaluated(outcome='reject', cap_type_breached='kill_switch')."""
    import asyncio

    from iguanatrader.shared.errors import KillSwitchActiveError

    captured: list[Any] = []

    async def _capture(evt: ProposalRiskEvaluated) -> None:
        captured.append(evt)

    bus.subscribe(ProposalRiskEvaluated, _capture)

    async def _fake_get_by_id(_self: object, _proposal_id: object) -> object:
        return fake_proposal_row

    monkeypatch.setattr(
        "iguanatrader.contexts.trading.repository.TradeProposalRepository.get_by_id",
        _fake_get_by_id,
    )

    async def _raise_kill_switch(_proposal: object) -> tuple[Any, Any]:
        raise KillSwitchActiveError(detail="Kill switch active.")

    monkeypatch.setattr(risk_service, "evaluate_proposal", _raise_kill_switch)

    await risk_service._proposal_created_handler(event)
    for _ in range(10):
        await asyncio.sleep(0)

    assert len(captured) == 1
    assert captured[0].outcome == "reject"
    assert captured[0].cap_type_breached == "kill_switch"


@pytest.mark.asyncio
async def test_bridge_logs_warning_and_publishes_nothing_when_proposal_missing(
    risk_service: RiskService,
    bus: MessageBus,
    event: ProposalCreated,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing-proposal path: get_by_id returns None → no event published."""
    import asyncio

    captured: list[Any] = []

    async def _capture(evt: ProposalRiskEvaluated) -> None:
        captured.append(evt)

    bus.subscribe(ProposalRiskEvaluated, _capture)

    async def _fake_get_by_id(_self: object, _proposal_id: object) -> object | None:
        return None

    monkeypatch.setattr(
        "iguanatrader.contexts.trading.repository.TradeProposalRepository.get_by_id",
        _fake_get_by_id,
    )

    await risk_service._proposal_created_handler(event)
    for _ in range(10):
        await asyncio.sleep(0)

    assert captured == []


@pytest.mark.asyncio
async def test_register_subscriptions_wires_handler_for_proposal_created(
    risk_service: RiskService,
    bus: MessageBus,
    event: ProposalCreated,
    fake_proposal_row: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Integration: register_subscriptions + bus.publish(ProposalCreated) → handler invoked."""
    import asyncio

    captured: list[Any] = []

    async def _capture(evt: ProposalRiskEvaluated) -> None:
        captured.append(evt)

    bus.subscribe(ProposalRiskEvaluated, _capture)

    async def _fake_get_by_id(_self: object, _proposal_id: object) -> object:
        return fake_proposal_row

    monkeypatch.setattr(
        "iguanatrader.contexts.trading.repository.TradeProposalRepository.get_by_id",
        _fake_get_by_id,
    )
    monkeypatch.setattr(
        risk_service,
        "evaluate_proposal",
        AsyncMock(return_value=(uuid4(), Decision(outcome="allow"))),
    )

    risk_service.register_subscriptions(bus)
    await bus.publish(event)
    for _ in range(20):
        await asyncio.sleep(0)

    assert len(captured) == 1
    assert captured[0].outcome == "allow"
    assert captured[0].proposal_id == event.proposal_id

    await bus.aclose()


def test_project_proposal_input_computes_notional_value(
    fake_proposal_row: SimpleNamespace,
) -> None:
    """Static helper: notional_value = quantity * entry_price_indicative."""
    result = RiskService._project_proposal_input(fake_proposal_row)
    assert isinstance(result, TradeProposalInput)
    assert result.id == fake_proposal_row.id
    assert result.tenant_id == fake_proposal_row.tenant_id
    assert result.side == "buy"
    assert result.notional_value == Decimal("1500.00")  # 10 * 150.00


def _suppress_unused() -> None:
    _ = (datetime, UTC, _StubKillSwitchActiveError)
