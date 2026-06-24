"""Unit tests for :func:`render_proposal_card` — clear buy/sell wording."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from iguanatrader.contexts.approval.channels.proposal_card import render_proposal_card

_EXPIRES = datetime(2026, 6, 23, 20, 30, tzinfo=UTC)


def test_long_card_states_buy_and_sell_levels() -> None:
    request_id = uuid4()
    card = render_proposal_card(
        request_id=request_id,
        proposal_id=uuid4(),
        symbol="AMD",
        side="buy",
        quantity=Decimal("12"),
        entry_price=Decimal("560.00"),
        stop_price=Decimal("540.00"),
        target_price=Decimal("590.00"),
        expires_at=_EXPIRES,
        reasoning={"lookback": 20, "breakout_level": "558.37"},
    )
    assert "COMPRAR (LARGO) AMD" in card
    assert "MÁXIMO de 20 días (558.37)" in card
    # Both sides of the trade are spelled out for a long.
    assert "Vender en objetivo: 590.00" in card
    assert "Vender si toca stop: 540.00" in card
    assert "+5.4%" in card  # (590-560)/560
    assert "-3.6%" in card  # (540-560)/560
    assert f"/approve {request_id}" in card


def test_short_card_states_sell_short_and_buy_back() -> None:
    card = render_proposal_card(
        request_id=uuid4(),
        proposal_id=uuid4(),
        symbol="USO",
        side="sell",
        quantity=Decimal("30"),
        entry_price=Decimal("110.00"),
        stop_price=Decimal("116.00"),
        target_price=Decimal("101.00"),
        expires_at=_EXPIRES,
        reasoning={"lookback": 20, "breakout_level": "110.48"},
    )
    assert "VENDER EN CORTO USO" in card
    assert "MÍNIMO de 20 días (110.48)" in card
    assert "Recomprar en objetivo: 101.00" in card
    assert "Recomprar si toca stop: 116.00" in card


def test_card_omits_target_line_when_no_target() -> None:
    card = render_proposal_card(
        request_id=uuid4(),
        proposal_id=uuid4(),
        symbol="SPY",
        side="buy",
        quantity=Decimal("5"),
        entry_price=Decimal("740.00"),
        stop_price=Decimal("720.00"),
        target_price=None,
        expires_at=_EXPIRES,
        reasoning={},
    )
    assert "🎯" not in card
    assert "Vender si toca stop: 720.00" in card
