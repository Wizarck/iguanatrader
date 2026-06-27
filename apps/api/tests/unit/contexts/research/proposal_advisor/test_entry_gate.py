"""WS-2 ``EntryVetoGate`` — turns the advisor verdict into a block/proceed
decision, applies the confidence threshold, and FAILS OPEN on any error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest
from iguanatrader.contexts.research.proposal_advisor.entry_gate import EntryVetoGate


@dataclass
class _Verdict:
    veto: bool
    confidence: Decimal
    rationale: str = "because"
    flags: list[str] = field(default_factory=list)


class _StubAdvisor:
    def __init__(self, verdict: _Verdict | None = None, *, raise_exc: bool = False) -> None:
        self._verdict = verdict or _Verdict(veto=False, confidence=Decimal("0"))
        self._raise = raise_exc
        self.calls: list[dict[str, Any]] = []

    async def assess(self, **kwargs: Any) -> _Verdict:
        self.calls.append(kwargs)
        if self._raise:
            raise RuntimeError("llm-boom")
        return self._verdict


def _gate(advisor: _StubAdvisor, **kw: Any) -> EntryVetoGate:
    return EntryVetoGate(advisor, **kw)  # type: ignore[arg-type]


async def _evaluate(gate: EntryVetoGate, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "symbol": "AMD",
        "side": "buy",
        "quantity": Decimal("10"),
        "entry_price": Decimal("200"),
        "stop_price": Decimal("190"),
        "target_price": Decimal("240"),
        "confidence_score": Decimal("0.8"),
        "reasoning": {"lookback": 20},
    }
    kwargs.update(overrides)
    return await gate.evaluate(**kwargs)


@pytest.mark.asyncio
async def test_high_conviction_veto_blocks() -> None:
    advisor = _StubAdvisor(_Verdict(veto=True, confidence=Decimal("0.9"), rationale="bad setup"))
    decision = await _evaluate(_gate(advisor))
    assert decision.blocked is True
    assert decision.rationale == "bad setup"


@pytest.mark.asyncio
async def test_low_conviction_veto_does_not_block() -> None:
    advisor = _StubAdvisor(_Verdict(veto=True, confidence=Decimal("0.6")))
    decision = await _evaluate(_gate(advisor))
    assert decision.blocked is False


@pytest.mark.asyncio
async def test_no_veto_proceeds() -> None:
    advisor = _StubAdvisor(_Verdict(veto=False, confidence=Decimal("0.99")))
    decision = await _evaluate(_gate(advisor))
    assert decision.blocked is False


@pytest.mark.asyncio
async def test_gate_fails_open_on_advisor_error() -> None:
    advisor = _StubAdvisor(raise_exc=True)
    decision = await _evaluate(_gate(advisor))
    # A gate error NEVER blocks trading — the human HITL is the backstop.
    assert decision.blocked is False
    assert "fail-open" in decision.rationale


@pytest.mark.asyncio
async def test_context_lookups_reach_the_advisor() -> None:
    async def brief_lookup(symbol: str) -> str | None:
        return f"thesis-{symbol}"

    async def hindsight_lookup(symbol: str) -> list[str]:
        return ["prior fade"]

    async def recent_trades_lookup(symbol: str) -> str:
        return "1 win, 2 losses"

    advisor = _StubAdvisor(_Verdict(veto=False, confidence=Decimal("0")))
    gate = _gate(
        advisor,
        brief_lookup=brief_lookup,
        hindsight_lookup=hindsight_lookup,
        recent_trades_lookup=recent_trades_lookup,
    )
    await _evaluate(gate, symbol="NVDA")
    call = advisor.calls[0]
    assert call["brief_thesis"] == "thesis-NVDA"
    assert call["hindsight_chunks"] == ["prior fade"]
    assert call["recent_trades_summary"] == "1 win, 2 losses"


@pytest.mark.asyncio
async def test_custom_threshold_is_honoured() -> None:
    advisor = _StubAdvisor(_Verdict(veto=True, confidence=Decimal("0.6")))
    gate = _gate(advisor, confidence_threshold=Decimal("0.5"))
    decision = await _evaluate(gate)
    assert decision.blocked is True  # 0.6 >= 0.5
