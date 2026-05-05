"""Per-trade cap protection — rejects when notional exceeds 2% of capital by default.

Per spec ``risk-engine-protections`` Requirement "Per-trade cap rejects
proposals exceeding 2% of capital by default":

* Computes ``proposal.notional_value / state.capital``.
* If strictly greater than ``caps.per_trade_pct``, returns
  :class:`Decision` with ``outcome="reject"`` + ``cap_type_breached="per_trade"``.
* Else returns ``Decision(outcome="allow")`` so the engine can move on
  to the next protection.

Pure function: no I/O, no clock, no DB. The engine's
``test_engine_purity`` does NOT walk this file (it only walks
``engine.py``), but the same convention applies for property-test
ergonomics.

Edge cases handled:

* ``state.capital == 0`` — division would raise; returns reject with
  ``current_pct=None`` (zero capital ⇒ no trade is possible at all).
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
    """Return ``Decision(outcome="allow")`` iff notional is within per-trade cap."""
    if state.capital <= Decimal("0"):
        return Decision(
            outcome="reject",
            cap_type_breached="per_trade",
            current_pct=None,
        )

    current_pct = proposal.notional_value / state.capital
    if current_pct > caps.per_trade_pct:
        return Decision(
            outcome="reject",
            cap_type_breached="per_trade",
            current_pct=current_pct,
        )
    return Decision(outcome="allow")


__all__ = ["evaluate"]
