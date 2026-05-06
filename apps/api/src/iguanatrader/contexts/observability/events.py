"""MessageBus event payloads owned by the observability bounded context.

Per the slice-2 :class:`MessageBus` contract: events are dataclasses
inheriting from :class:`Event`. Subscribers receive the typed payload;
the bus does not introspect.

Three events for slice O1:

- :class:`CostSnapshotEvent` (``observability.cost.snapshot``) — emitted
  by the dashboard publisher every 5 minutes per tenant (NFR-O4).
- :class:`BudgetWarningThresholdEvent`
  (``observability.budget.warning_threshold``) — emitted exactly once
  per tenant per month when WARN_80 first fires (FR41).
- :class:`LLMRouteChosenEvent` (``observability.llm.route_chosen``) —
  emitted on every routing decision (FR39 + observability for budget
  auto-downgrades).

Each event carries the canonical ``event_name`` (matches the dot-namespaced
structlog convention from AGENTS.md §4) so log + bus consumers can
filter on a single string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from iguanatrader.shared.messagebus import Event


@dataclass
class CostSnapshotEvent(Event):
    """5-minute aggregated cost snapshot for a single tenant (NFR-O4).

    The publisher computes the snapshot from
    :class:`ApiCostEventRepository.query_by_tenant_and_period` and emits
    once per 5-minute bucket per tenant. Subscribers can publish to SSE,
    persist to a separate aggregations table, or forward to OTEL metrics.
    """

    EVENT_NAME: ClassVar[str] = "observability.cost.snapshot"

    tenant_id: UUID = field(default_factory=lambda: UUID(int=0))
    bucket_start: datetime = field(default_factory=lambda: datetime.fromtimestamp(0))
    bucket_end: datetime = field(default_factory=lambda: datetime.fromtimestamp(0))
    total_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    total_calls: int = 0
    cached_calls: int = 0
    by_provider: dict[str, Decimal] = field(default_factory=dict)
    by_model: dict[str, Decimal] = field(default_factory=dict)


@dataclass
class BudgetWarningThresholdEvent(Event):
    """Emitted once per tenant per month when the WARN_80 threshold first crosses.

    The :func:`iguanatrader.contexts.observability.budget.check_budget`
    function deduplicates via an in-process cache keyed by
    ``(tenant_id, year, month)`` (per design D4 + risk mitigation in D9).
    """

    EVENT_NAME: ClassVar[str] = "observability.budget.warning_threshold"

    tenant_id: UUID = field(default_factory=lambda: UUID(int=0))
    percent_used: int = 0
    spent_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    cap_usd: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass
class LLMRouteChosenEvent(Event):
    """Emitted on every :func:`route_llm` call (FR39).

    Carries the routing decision rationale + budget status so downstream
    consumers (audit log writer, OTEL exporter) can correlate a routing
    choice with the budget gate state.
    """

    EVENT_NAME: ClassVar[str] = "observability.llm.route_chosen"

    tenant_id: UUID | None = None
    task_class: str = ""
    model_chosen: str = ""
    reason: str = ""


__all__ = [
    "BudgetWarningThresholdEvent",
    "CostSnapshotEvent",
    "LLMRouteChosenEvent",
]
