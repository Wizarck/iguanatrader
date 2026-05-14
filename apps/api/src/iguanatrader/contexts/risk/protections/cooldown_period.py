"""Cooldown-period cap — rejects within a per-symbol cooldown window (v1.5).

Seventh protection in the engine chain, composed after ``stoploss_guard``.
Implements the Freqtrade ``CooldownPeriod`` pattern: when the most-recent
closed trade on a given symbol occurred fewer than
:attr:`RiskCaps.cooldown_seconds` ago, reject new proposals on the SAME
symbol. Other symbols are unaffected — a 30-minute cooldown on TSLA does
not block AAPL signals.

Why this exists alongside the other caps: daily / weekly / drawdown caps
trip on aggregate P&L; a tight stop-and-reopen loop on a single symbol
("revenge trading") drains capital trade-by-trade without ever tripping
those aggregate caps. The cooldown forces a re-evaluation window between
two trades on the same symbol — a quantitative version of "step away
from the keyboard".

Pure function. The seconds-since-last-close map itself is computed
upstream by the service-layer :class:`RiskState` builder, which performs
the single ``datetime.now()`` read at state-build time (per design D5
this clock read at service-layer scope is acceptable; engine + protections
stay clock-free). The protection just compares the :class:`int` field
against the configured threshold.

Default disabled: ``RiskCaps.cooldown_seconds`` is ``None`` out of the
box, so existing tenants see no behavioural change until they opt in.
Absent symbols (no prior close recorded) also fall through to ``allow``
— a brand-new symbol cannot be in cooldown.
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
    """Return ``Decision(outcome="allow")`` iff the symbol is outside cooldown.

    Semantics: cooldown is **strictly less than** — a proposal that
    arrives exactly ``cooldown_seconds`` after the previous close is
    allowed (the wait is satisfied). This matches the per-trade cap's
    strict-greater-than rejection style and lets operators reason about
    the boundary without an off-by-one.

    ``current_pct`` carries ``seconds_since_close / cooldown_seconds`` so
    SSE + observability consumers can chart "40% through the cooldown
    window" alongside the percent-based caps, even though the underlying
    units are seconds rather than a P&L fraction.
    """
    threshold = caps.cooldown_seconds
    if threshold is None:
        return Decision(outcome="allow")

    seconds_since_close = state.seconds_since_last_close_by_symbol.get(
        proposal.symbol,
    )
    if seconds_since_close is None:
        # No prior close on this symbol — no cooldown applies.
        return Decision(outcome="allow")

    if seconds_since_close >= threshold:
        return Decision(outcome="allow")

    return Decision(
        outcome="reject",
        cap_type_breached="cooldown_period",
        current_pct=Decimal(seconds_since_close) / Decimal(threshold),
    )


__all__ = ["evaluate"]
