"""Urgent-exit review sweep (WS-5 PR-C) — the cron that turns a position
review + an Opus opinion into a Telegram approve/deny card.

Locks the behaviour that matters for real money:

* the cost pre-filter (no LLM call for a green, fully-protected position);
* pending-exit dedup (a still-open card is not re-raised);
* the confidence gate (urgent_sell must clear the threshold);
* the side mapping (long → SELL-to-close ``buy`` held side, short → ``sell``);
* it NEVER closes — it only publishes :class:`ExitApprovalRequested`;
* per-position failure isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.risk.position_review import (
    PositionReview,
    PositionReviewResult,
    ProtectiveLeg,
)
from iguanatrader.contexts.risk.urgent_exit_sweep import UrgentExitReviewSweepService
from iguanatrader.contexts.trading.events import ExitApprovalRequested

_TENANT = uuid4()


# ----------------------------------------------------------------------
# Fakes
# ----------------------------------------------------------------------


@dataclass
class _Verdict:
    urgent_sell: bool
    confidence: Decimal
    rationale: str = "because"
    flags: list[str] = field(default_factory=list)


class _StubAdvisor:
    def __init__(self, verdict: _Verdict | None = None, raise_for: set[str] | None = None) -> None:
        self._verdict = verdict or _Verdict(urgent_sell=False, confidence=Decimal("0"))
        self._raise_for = raise_for or set()
        self.calls: list[dict[str, Any]] = []

    async def assess(self, **kwargs: Any) -> _Verdict:
        self.calls.append(kwargs)
        if kwargs["symbol"] in self._raise_for:
            raise RuntimeError(f"advisor-boom:{kwargs['symbol']}")
        return self._verdict


class _RecordingBus:
    def __init__(self) -> None:
        self.published: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.published.append(event)


class _FakeReview:
    def __init__(self, reviews: list[PositionReview], *, working_read: int = 0) -> None:
        self._reviews = reviews
        self._working_read = working_read

    async def review(self) -> PositionReviewResult:
        return PositionReviewResult(
            reviews=self._reviews,
            broker_positions_read=len(self._reviews),
            broker_working_orders_read=self._working_read,
        )


async def _never_pending(trade_id: UUID) -> bool:
    return False


async def _always_pending(trade_id: UUID) -> bool:
    return True


def _review(
    *,
    symbol: str = "AMD",
    side: str = "long",
    qty: Decimal = Decimal("10"),
    stop: Decimal = Decimal("190"),
    target: Decimal | None = Decimal("240"),
    upnl: Decimal | None = Decimal("-50"),
    divergences: list[str] | None = None,
    resting_stop: ProtectiveLeg | None = None,
    resting_target: ProtectiveLeg | None = None,
    avg: Decimal | None = Decimal("200"),
    trade_id: UUID | None = None,
) -> PositionReview:
    return PositionReview(
        trade_id=trade_id or uuid4(),
        tenant_id=_TENANT,
        symbol=symbol,
        side=side,
        quantity=qty,
        intended_stop=stop,
        intended_target=target,
        resting_stop=resting_stop,
        resting_target=resting_target,
        broker_quantity=qty if side == "long" else -qty,
        average_price=avg,
        unrealized_pnl=upnl,
        divergences=divergences or [],
    )


def _service(
    *,
    reviews: list[PositionReview],
    advisor: _StubAdvisor,
    bus: _RecordingBus,
    pending: Any = _never_pending,
    brief_lookup: Any = None,
    hindsight_lookup: Any = None,
    recent_trades_lookup: Any = None,
    threshold: Decimal = Decimal("0.75"),
) -> UrgentExitReviewSweepService:
    return UrgentExitReviewSweepService(
        position_review=_FakeReview(reviews),  # type: ignore[arg-type]
        exit_advisor=advisor,  # _StubAdvisor structurally conforms to ExitAdvisorLike
        bus=bus,  # type: ignore[arg-type]
        pending_exit_checker=pending,
        brief_lookup=brief_lookup,
        hindsight_lookup=hindsight_lookup,
        recent_trades_lookup=recent_trades_lookup,
        confidence_threshold=threshold,
    )


# ----------------------------------------------------------------------
# Cost pre-filter
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_green_protected_position_skips_advisor() -> None:
    # Profitable + no divergence → no Opus call, no card.
    advisor = _StubAdvisor()
    bus = _RecordingBus()
    svc = _service(
        reviews=[_review(upnl=Decimal("125"), divergences=[])],
        advisor=advisor,
        bus=bus,
    )
    result = await svc.sweep()
    assert advisor.calls == []
    assert bus.published == []
    assert result.skipped_no_signal == 1
    assert result.candidates_assessed == 0
    assert result.urgent_exits_raised == 0


@pytest.mark.asyncio
async def test_divergence_triggers_assessment_even_when_profitable() -> None:
    # No loss, but the broker reconciliation found a missing stop → assess.
    advisor = _StubAdvisor(_Verdict(urgent_sell=True, confidence=Decimal("0.9")))
    bus = _RecordingBus()
    svc = _service(
        reviews=[_review(upnl=Decimal("80"), divergences=["stop_missing_at_broker"])],
        advisor=advisor,
        bus=bus,
    )
    result = await svc.sweep()
    assert len(advisor.calls) == 1
    assert result.urgent_exits_raised == 1
    assert len(bus.published) == 1


@pytest.mark.asyncio
async def test_adverse_pnl_triggers_assessment_without_divergence() -> None:
    advisor = _StubAdvisor(_Verdict(urgent_sell=False, confidence=Decimal("0.2")))
    bus = _RecordingBus()
    svc = _service(
        reviews=[_review(upnl=Decimal("-200"), divergences=[])],
        advisor=advisor,
        bus=bus,
    )
    result = await svc.sweep()
    assert len(advisor.calls) == 1
    assert result.candidates_assessed == 1
    assert result.urgent_exits_raised == 0  # advisor said hold


# ----------------------------------------------------------------------
# Raise / hold gate
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_urgent_sell_above_threshold_raises_exit_card() -> None:
    trade_id = uuid4()
    advisor = _StubAdvisor(
        _Verdict(
            urgent_sell=True,
            confidence=Decimal("0.86"),
            rationale="unprotected + thesis break",
            flags=["unprotected"],
        )
    )
    bus = _RecordingBus()
    svc = _service(
        reviews=[
            _review(
                trade_id=trade_id,
                side="long",
                qty=Decimal("12"),
                upnl=Decimal("-340"),
                divergences=["stop_missing_at_broker"],
            )
        ],
        advisor=advisor,
        bus=bus,
    )
    result = await svc.sweep()

    assert result.urgent_exits_raised == 1
    assert len(bus.published) == 1
    event = bus.published[0]
    assert isinstance(event, ExitApprovalRequested)
    assert event.tenant_id == _TENANT
    assert event.trade_id == trade_id
    assert event.side == "buy"  # long position → close by selling
    assert event.quantity == Decimal("12")
    assert event.reason == "urgent"
    assert event.llm_rationale == "unprotected + thesis break"
    assert event.confidence == Decimal("0.86")
    assert event.metadata["divergences"] == ["stop_missing_at_broker"]


@pytest.mark.asyncio
async def test_urgent_sell_below_threshold_does_not_raise() -> None:
    advisor = _StubAdvisor(_Verdict(urgent_sell=True, confidence=Decimal("0.6")))
    bus = _RecordingBus()
    svc = _service(
        reviews=[_review(upnl=Decimal("-50"))],
        advisor=advisor,
        bus=bus,
    )
    result = await svc.sweep()
    assert bus.published == []
    assert result.candidates_assessed == 1
    assert result.urgent_exits_raised == 0


@pytest.mark.asyncio
async def test_short_position_maps_to_sell_held_side() -> None:
    advisor = _StubAdvisor(_Verdict(urgent_sell=True, confidence=Decimal("0.9")))
    bus = _RecordingBus()
    svc = _service(
        reviews=[_review(side="short", upnl=Decimal("-10"), divergences=["no_broker_position"])],
        advisor=advisor,
        bus=bus,
    )
    await svc.sweep()
    assert bus.published[0].side == "sell"  # short → close by buying back, held side 'sell'


# ----------------------------------------------------------------------
# Dedup + isolation
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_exit_card_is_deduped() -> None:
    advisor = _StubAdvisor(_Verdict(urgent_sell=True, confidence=Decimal("0.99")))
    bus = _RecordingBus()
    svc = _service(
        reviews=[_review(upnl=Decimal("-500"), divergences=["stop_missing_at_broker"])],
        advisor=advisor,
        bus=bus,
        pending=_always_pending,
    )
    result = await svc.sweep()
    assert advisor.calls == []  # never even reached the LLM
    assert bus.published == []
    assert result.skipped_pending == 1


@pytest.mark.asyncio
async def test_per_position_error_is_isolated() -> None:
    advisor = _StubAdvisor(
        _Verdict(urgent_sell=True, confidence=Decimal("0.9")),
        raise_for={"BOOM"},
    )
    bus = _RecordingBus()
    svc = _service(
        reviews=[
            _review(symbol="BOOM", upnl=Decimal("-10"), divergences=["x"]),
            _review(symbol="AMD", upnl=Decimal("-10"), divergences=["stop_missing_at_broker"]),
        ],
        advisor=advisor,
        bus=bus,
    )
    result = await svc.sweep()
    # The raiser is isolated; the healthy position still raises its card.
    assert result.skipped_errors == 1
    assert result.urgent_exits_raised == 1
    assert len(bus.published) == 1
    assert bus.published[0].symbol == "AMD"


# ----------------------------------------------------------------------
# Context plumbing
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_sources_reach_the_advisor() -> None:
    async def brief_lookup(symbol: str) -> str | None:
        return f"thesis-for-{symbol}"

    async def hindsight_lookup(symbol: str) -> list[str]:
        return ["prior drawdown after stop removal"]

    async def recent_trades_lookup(symbol: str) -> str:
        return "2 wins, 1 loss"

    advisor = _StubAdvisor(_Verdict(urgent_sell=False, confidence=Decimal("0")))
    bus = _RecordingBus()
    resting_stop = ProtectiveLeg(
        kind="stop",
        order_type="STP",
        level=Decimal("188"),
        quantity=Decimal("10"),
        status="Submitted",
        order_ref="r1",
    )
    svc = _service(
        reviews=[
            _review(
                symbol="AMD",
                upnl=Decimal("-50"),
                divergences=["stop_level_mismatch"],
                resting_stop=resting_stop,
            )
        ],
        advisor=advisor,
        bus=bus,
        brief_lookup=brief_lookup,
        hindsight_lookup=hindsight_lookup,
        recent_trades_lookup=recent_trades_lookup,
    )
    await svc.sweep()

    call = advisor.calls[0]
    assert call["brief_thesis"] == "thesis-for-AMD"
    assert call["hindsight_chunks"] == ["prior drawdown after stop removal"]
    assert call["recent_trades_summary"] == "2 wins, 1 loss"
    assert call["divergences"] == ["stop_level_mismatch"]
    assert "stop STP @ 188" in call["resting_orders_summary"]
    # No market-data dependency: current price is left unknown for the LLM.
    assert call["current_price"] is None
