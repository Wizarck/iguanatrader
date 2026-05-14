"""Stoploss-guard cap — rejects on consecutive-stoploss streak (v1.5).

Sixth protection in the engine chain, composed after ``max_drawdown``.
Implements the Freqtrade ``StoplossGuard`` pattern: when ``N`` of the
trailing ``M`` closed trades exited via stoploss, halt new proposals.
Daily / weekly loss caps trip on aggregate P&L; a tight losing streak
(``N`` losers each just under the daily floor) drains capital without
ever tripping daily — this guard catches the regime change before the
cap fires.

Pure function. The streak count itself is computed upstream by the
service-layer ``RiskState`` builder (which reads
``trades.exit_reason``); the protection just compares the
:class:`int` field on :class:`RiskState` against the configured
threshold on :class:`RiskCaps`.

Default disabled: ``RiskCaps.stoploss_guard_threshold`` is ``None``
out of the box, so existing tenants see no behavioural change until
they opt in.
"""

from __future__ import annotations

from decimal import Decimal

from iguanatrader.contexts.risk.models import (
    Decision,
    RiskCaps,
    RiskState,
    TradeProposalInput,
)


def evaluate(
    proposal: TradeProposalInput,
    state: RiskState,
    caps: RiskCaps,
) -> Decision:
    """Return ``Decision(outcome="allow")`` iff the streak is below cap.

    Semantics match the other ``>=``-style caps (daily, weekly,
    max_open, max_drawdown): the cap is **at-or-above**, so a streak
    that exactly equals the threshold rejects. This keeps the chain
    consistent — every regime-level halt fires the moment the
    threshold is reached, not one trade later.

    ``current_pct`` carries the streak-as-fraction-of-lookback so the
    SSE + observability consumers can chart "3 of 5 trailing trades
    stopped" alongside the percent-based caps. When
    ``state.recent_trades_lookback`` is ``0`` (state builder not yet
    wired) the denominator is unknown and ``current_pct`` is left
    ``None`` rather than dividing by zero.
    """
    threshold = caps.stoploss_guard_threshold
    if threshold is None:
        return Decision(outcome="allow")

    if state.recent_stoploss_count_trailing < threshold:
        return Decision(outcome="allow")

    current_pct: Decimal | None
    if state.recent_trades_lookback > 0:
        current_pct = Decimal(state.recent_stoploss_count_trailing) / Decimal(
            state.recent_trades_lookback,
        )
    else:
        current_pct = None

    return Decision(
        outcome="reject",
        cap_type_breached="stoploss_guard",
        current_pct=current_pct,
    )


__all__ = ["evaluate"]
