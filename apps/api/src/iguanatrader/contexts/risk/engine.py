"""Pure-functional risk engine — ``(Proposal, State, Caps) → Decision``.

Per slice K1 design D1 + spec ``risk-engine-protections`` Requirement 1:
:func:`evaluate` is a top-level pure function with NO I/O, NO clock
read, NO DB access, NO network, NO file-system access. ``mypy --strict``
checks the contract; the
:mod:`tests.unit.contexts.risk.test_engine_purity` AST inspector is the
runtime CI gate.

Composition order (per design D2 + tasks 3.7) is fixed:

1. ``per_trade``  — cheapest, single-trade cap.
2. ``daily_loss`` — blanket halt on day-to-date loss.
3. ``weekly_loss`` — blanket halt on week-to-date loss.
4. ``max_open``  — open-positions count cap.
5. ``max_drawdown`` — peak-to-trough drawdown cap.

Short-circuit semantics: the first non-allow Decision is returned
(later protections are not evaluated). When all five pass, the engine
returns ``Decision(outcome="allow", state_snapshot=<rendered RiskState>)``.

The ``state_snapshot`` is rendered via ``state.model_dump(mode="json")``
which converts ``Decimal`` to ``str`` — appropriate for the JSON
column in ``risk_evaluations.state_snapshot``. Pydantic's serialiser
is a pure transform (no I/O), so engine purity is preserved.

PURITY PROHIBITED IMPORTS (asserted by ``test_engine_purity.py``):

* ``datetime``, ``time``, ``sqlalchemy``, ``requests``, ``httpx``

PURITY PROHIBITED CALL PATTERNS:

* ``.now()``, ``.utcnow()``, ``.commit()``, ``.execute()``, ``.add()``,
  ``.delete()``

Adding a sixth protection in a future slice is a 1-line edit to
``_PROTECTIONS`` below + a new file under ``protections/``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from iguanatrader.contexts.risk.models import (
    Decision,
    RiskCaps,
    RiskState,
    TradeProposalInput,
)
from iguanatrader.contexts.risk.protections import (
    daily,
    max_drawdown,
    max_open,
    per_trade,
    weekly,
)

#: Protection callable signature shared by all five protection modules.
ProtectionFn = Callable[[TradeProposalInput, RiskState, RiskCaps], Decision]

#: Fixed composition order — per design D2. Order is part of the FR45
#: contract; reordering is a breaking change to engine semantics.
_PROTECTIONS: tuple[ProtectionFn, ...] = (
    per_trade.evaluate,
    daily.evaluate,
    weekly.evaluate,
    max_open.evaluate,
    max_drawdown.evaluate,
)


def _snapshot(state: RiskState) -> dict[str, str]:
    """Render :class:`RiskState` as a stringified dict for JSON storage.

    Pure transform — Pydantic's serialiser is invoked; no I/O. The
    resulting dict has every value coerced to ``str`` so the JSON
    column in ``risk_evaluations.state_snapshot`` is round-trip safe
    on both SQLite (TEXT-backed JSON) and PostgreSQL (native JSONB).
    """
    raw: dict[str, Any] = state.model_dump(mode="json")
    return {key: str(value) for key, value in raw.items()}


def evaluate(
    proposal: TradeProposalInput,
    state: RiskState,
    caps: RiskCaps,
) -> Decision:
    """Compose the five protections; return the first non-allow Decision.

    When every protection returns ``Decision(outcome="allow")``, the
    engine returns its own ``allow`` Decision with the state snapshot
    attached. The non-allow path returns the protection's Decision
    augmented with the snapshot (so audit consumers always see the
    state the engine saw, regardless of which protection fired).
    """
    for protection in _PROTECTIONS:
        decision = protection(proposal, state, caps)
        if decision.outcome != "allow":
            return decision.model_copy(update={"state_snapshot": _snapshot(state)})

    return Decision(outcome="allow", state_snapshot=_snapshot(state))


__all__ = ["evaluate"]
