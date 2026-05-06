"""Max-drawdown cap — rejects when peak-to-trough drawdown ≥ 15% (default).

Ultimate circuit-breaker beyond daily/weekly losses. Per spec
"15.5% drawdown locks out all new trades": reject with
``cap_type_breached="max_drawdown"`` when at-or-above the cap.

Pure function.
"""

from __future__ import annotations

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
    """Return ``Decision(outcome="allow")`` iff drawdown is below cap."""
    if state.peak_to_trough_drawdown_pct >= caps.max_drawdown_pct:
        return Decision(
            outcome="reject",
            cap_type_breached="max_drawdown",
            current_pct=state.peak_to_trough_drawdown_pct,
        )
    return Decision(outcome="allow")


__all__ = ["evaluate"]
