"""Weekly-loss cap — rejects when week-to-date loss ≥ 15% (default).

Mirror of :mod:`iguanatrader.contexts.risk.protections.daily` against
the ``week_to_date_loss_pct`` field. Pure function.
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
    """Return ``Decision(outcome="allow")`` iff weekly loss is below cap."""
    if state.week_to_date_loss_pct >= caps.weekly_loss_pct:
        return Decision(
            outcome="reject",
            cap_type_breached="weekly_loss",
            current_pct=state.week_to_date_loss_pct,
        )
    return Decision(outcome="allow")


__all__ = ["evaluate"]
