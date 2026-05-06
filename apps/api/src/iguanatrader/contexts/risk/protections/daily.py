"""Daily-loss cap — rejects all proposals when day-to-date loss ≥ 5% (default).

Per spec scenario "Day-to-date loss at 5.1% halts new proposals":

* When ``state.day_to_date_loss_pct >= caps.daily_loss_pct``, ANY
  proposal is rejected with ``cap_type_breached="daily_loss"``.
* The kill-switch auto-activation (per design D6 + spec) is the
  service layer's responsibility — this protection only signals the
  breach; ``RiskService._maybe_auto_activate_on_breach`` reads the
  decision and writes the ``kill_switch_events`` row.

Pure function — no I/O.
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
    """Return ``Decision(outcome="allow")`` iff daily loss is below cap."""
    if state.day_to_date_loss_pct >= caps.daily_loss_pct:
        return Decision(
            outcome="reject",
            cap_type_breached="daily_loss",
            current_pct=state.day_to_date_loss_pct,
        )
    return Decision(outcome="allow")


__all__ = ["evaluate"]
