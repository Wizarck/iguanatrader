"""Max open positions cap — rejects when ≥ 10 open positions (default).

Per spec design D2 + tasks 3.5: assumes every proposal opens a NEW
position (clip semantics deferred). When the open-positions count is
already at-or-above the cap, the proposal is rejected with
``cap_type_breached="max_open"``.

Pure function.
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
    """Return ``Decision(outcome="allow")`` iff open count is below cap."""
    if state.open_positions_count >= caps.max_open_positions:
        return Decision(
            outcome="reject",
            cap_type_breached="max_open",
            # Express open-positions ratio as a Decimal so the SSE +
            # observability consumers can chart "70% utilisation"
            # uniformly with the percent-based caps.
            current_pct=(
                Decimal(state.open_positions_count) / Decimal(caps.max_open_positions)
                if caps.max_open_positions > 0
                else None
            ),
        )
    return Decision(outcome="allow")


__all__ = ["evaluate"]
