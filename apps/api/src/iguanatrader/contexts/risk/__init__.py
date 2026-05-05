"""Risk bounded context — caps, kill-switch, override audit (slice K1).

Public API (semver-locked from K1):

* :class:`RiskCaps`, :class:`RiskState`, :class:`Decision`,
  :class:`TradeProposalInput`, :class:`Confirmation`,
  :class:`ConfirmationChain` — Pydantic value objects
  (``contexts/risk/models.py``).
* :func:`evaluate` — pure-functional engine entry point
  (``contexts/risk/engine.py``).
* :class:`RiskService` — orchestrator that performs I/O around the
  engine (``contexts/risk/service.py``).
* :class:`RiskRepositoryPort` — Protocol the service depends on
  (``contexts/risk/ports.py``).
* :class:`RiskRepository` — concrete SQLAlchemy adapter
  (``contexts/risk/repository.py``).
* Event types + channel constants (``contexts/risk/events.py``).

Cross-context coupling: this package emits events on
:class:`iguanatrader.shared.messagebus.MessageBus`; subscribers in
``approval`` (P1) and ``observability`` (O1) consume them WITHOUT
importing from ``iguanatrader.contexts.risk`` (per design D6 + the
universal bounded-context rule).

Per design D1: the engine is a *pure function* — the service.py
orchestrator is responsible for state-loading + persistence; readers
have to follow two files to understand "what happens when a proposal
is evaluated", which is the documented trade-off vs property-testability.
"""

from __future__ import annotations

from iguanatrader.contexts.risk.engine import evaluate
from iguanatrader.contexts.risk.events import (
    RISK_KILL_SWITCH_ACTIVATED,
    RISK_KILL_SWITCH_DEACTIVATED,
    RISK_PROPOSAL_ACCEPTED,
    RISK_PROPOSAL_OVERRIDE_REQUIRED,
    RISK_PROPOSAL_REJECTED,
    RiskKillSwitchActivated,
    RiskKillSwitchDeactivated,
    RiskProposalAccepted,
    RiskProposalOverrideRequired,
    RiskProposalRejected,
)
from iguanatrader.contexts.risk.models import (
    CapType,
    Confirmation,
    ConfirmationChain,
    Decision,
    KillSwitchSource,
    KillSwitchTransition,
    Outcome,
    RiskCaps,
    RiskState,
    TradeProposalInput,
)
from iguanatrader.contexts.risk.ports import RiskRepositoryPort
from iguanatrader.contexts.risk.repository import RiskRepository
from iguanatrader.contexts.risk.service import RiskService

__all__ = [
    "RISK_KILL_SWITCH_ACTIVATED",
    "RISK_KILL_SWITCH_DEACTIVATED",
    "RISK_PROPOSAL_ACCEPTED",
    "RISK_PROPOSAL_OVERRIDE_REQUIRED",
    "RISK_PROPOSAL_REJECTED",
    "CapType",
    "Confirmation",
    "ConfirmationChain",
    "Decision",
    "KillSwitchSource",
    "KillSwitchTransition",
    "Outcome",
    "RiskCaps",
    "RiskKillSwitchActivated",
    "RiskKillSwitchDeactivated",
    "RiskProposalAccepted",
    "RiskProposalOverrideRequired",
    "RiskProposalRejected",
    "RiskRepository",
    "RiskRepositoryPort",
    "RiskService",
    "RiskState",
    "TradeProposalInput",
    "evaluate",
]
