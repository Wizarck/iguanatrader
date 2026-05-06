"""Orchestration-specific errors (slice O2)."""

from __future__ import annotations

from typing import ClassVar

from iguanatrader.shared.errors import IguanaError


class DuplicateRoutineTriggerError(IguanaError):
    """A duplicate ``(routine_name, scheduled_at, tenant_id)`` was triggered.

    The unique-index enforces idempotency on scheduler restart races.
    Handler treats this as a benign skip (status=`skipped_duplicate`).
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:routine-duplicate-trigger"
    default_title: ClassVar[str] = "Duplicate Routine Trigger"
    default_status: ClassVar[int] = 409


class BudgetGateBlockedError(IguanaError):
    """LLM budget gate (O1) blocked the routine before execution."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:routine-budget-blocked"
    default_title: ClassVar[str] = "Routine Budget Blocked"
    default_status: ClassVar[int] = 402


class RoutineExecutionError(IguanaError):
    """Routine execution raised mid-flight; persisted with ``status='error'``."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:routine-execution"
    default_title: ClassVar[str] = "Routine Execution Error"
    default_status: ClassVar[int] = 500


__all__ = [
    "BudgetGateBlockedError",
    "DuplicateRoutineTriggerError",
    "RoutineExecutionError",
]
