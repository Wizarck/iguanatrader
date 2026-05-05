"""Bounded context for trading — entities, ports, service, repositories, events.

Adapters live in slice T2 (``brokers/``) + T3 (``strategies/``); routes in
slice T4. Slice T1 plants only the contract surface:

* :mod:`iguanatrader.contexts.trading.models` — ORM models (6 tables).
* :mod:`iguanatrader.contexts.trading.ports` — :class:`BrokerPort`,
  :class:`StrategyPort` (PEP 544 ``Protocol`` subclasses of
  :class:`iguanatrader.shared.ports.Port`).
* :mod:`iguanatrader.contexts.trading.service` — :class:`TradingService`
  orchestrator skeleton (``propose → risk_check → enqueue_approval →
  execute_on_approval → reconcile_fills``).
* :mod:`iguanatrader.contexts.trading.repository` — per-entity
  ``BaseRepository`` subclasses with automatic tenant filtering.
* :mod:`iguanatrader.contexts.trading.events` — inter-context event
  dataclasses (frozen wire format).

structlog event-name convention for this context: ``trading.<entity>.<action>``
(e.g. ``trading.proposal.created``, ``trading.order.placed``).
"""

from __future__ import annotations

from iguanatrader.contexts.trading.events import (
    ApprovalRequested,
    EquityUpdated,
    OrderFilled,
    OrderPlaced,
    ProposalApproved,
    ProposalCreated,
    ProposalRejected,
    ProposalRiskEvaluated,
)

__all__ = [
    "ApprovalRequested",
    "EquityUpdated",
    "OrderFilled",
    "OrderPlaced",
    "ProposalApproved",
    "ProposalCreated",
    "ProposalRejected",
    "ProposalRiskEvaluated",
]
