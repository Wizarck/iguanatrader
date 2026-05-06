"""Orchestration bounded context — slice O2.

Public exports:

* :class:`AlertTier` — IntEnum (1/2/3) for alert classification.
* :func:`classify_event` — pure rule engine mapping event name +
  payload to an :class:`AlertTier`.
* :class:`RoutineName` — Literal of the 4 supported routines.
* :class:`OrchestrationService` — facade orchestrating routine
  execution + alert filtering + persistence.
* :class:`SchedulerProtocol` — Protocol for the production-vs-fake
  scheduler swap (APScheduler wired in deployment-foundation slice).
"""

from __future__ import annotations

from iguanatrader.contexts.orchestration.alert_filter import (
    AlertTier,
    RoutingDecision,
    classify_event,
)
from iguanatrader.contexts.orchestration.errors import (
    BudgetGateBlockedError,
    DuplicateRoutineTriggerError,
    RoutineExecutionError,
)
from iguanatrader.contexts.orchestration.scheduler import (
    InMemoryScheduler,
    JobSpec,
    SchedulerProtocol,
)
from iguanatrader.contexts.orchestration.service import (
    OrchestrationService,
    RoutineName,
    RoutineOutcome,
)

__all__ = [
    "AlertTier",
    "BudgetGateBlockedError",
    "DuplicateRoutineTriggerError",
    "InMemoryScheduler",
    "JobSpec",
    "OrchestrationService",
    "RoutineExecutionError",
    "RoutineName",
    "RoutineOutcome",
    "RoutingDecision",
    "SchedulerProtocol",
    "classify_event",
]
