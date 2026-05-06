"""Rule-based LLM routing per task class (FR39 + design D2).

Five task classes map to five canonical model tiers; routing is a
hardcoded :class:`dict` lookup in this module — no DB, no ML
classifier (per design D2 alternatives). Future task classes are
added by editing :data:`_ROUTING_TABLE` plus a unit test.

Budget integration (per design D4): :func:`route_llm` calls
:func:`iguanatrader.contexts.observability.budget.check_budget` and:

- ``OK`` → returns the canonical tier.
- ``WARN_80`` → downgrades sonnet → haiku, opus → sonnet (cheaper tier).
- ``BLOCK_100`` → raises :class:`BudgetExceededError`.

The routing decision is logged via structlog
``observability.llm.route_chosen`` with ``task_class``, ``tier``,
``reason``, ``tenant_id``.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

import structlog

from iguanatrader.contexts.observability.budget import BudgetStatus, check_budget
from iguanatrader.contexts.observability.errors import BudgetExceededError

log = structlog.get_logger("iguanatrader.contexts.observability.llm_routing")


class TaskClass(StrEnum):
    """Coarse classification of the LLM workload (per design D2)."""

    RESEARCH_BRIEF = "research_brief"
    ROUTINE_SUMMARY = "routine_summary"
    ALERTING = "alerting"
    COMPLEX_SYNTHESIS = "complex_synthesis"
    GPT_FALLBACK = "gpt_fallback"


class LLMTier(StrEnum):
    """Canonical model tier identifiers (per design D2 routing table)."""

    CLAUDE_3_5_SONNET = "claude-3-5-sonnet"
    CLAUDE_3_5_HAIKU = "claude-3-5-haiku"
    CLAUDE_3_OPUS = "claude-3-opus"
    GPT_4O_MINI = "gpt-4o-mini"


#: Hardcoded task-class → model-tier table (per design D2). Lookup-only;
#: edits land here + a unit test, no DB-driven dynamism.
_ROUTING_TABLE: dict[TaskClass, LLMTier] = {
    TaskClass.RESEARCH_BRIEF: LLMTier.CLAUDE_3_5_SONNET,
    TaskClass.ROUTINE_SUMMARY: LLMTier.CLAUDE_3_5_HAIKU,
    TaskClass.ALERTING: LLMTier.CLAUDE_3_5_HAIKU,
    TaskClass.COMPLEX_SYNTHESIS: LLMTier.CLAUDE_3_OPUS,
    TaskClass.GPT_FALLBACK: LLMTier.GPT_4O_MINI,
}


#: Cheaper tier for the WARN_80 auto-downgrade (per design D4).
#: Pairs "tier" → "downgrade target". Tiers absent from the map remain
#: unchanged on WARN_80.
_DOWNGRADE_TABLE: dict[LLMTier, LLMTier] = {
    LLMTier.CLAUDE_3_OPUS: LLMTier.CLAUDE_3_5_SONNET,
    LLMTier.CLAUDE_3_5_SONNET: LLMTier.CLAUDE_3_5_HAIKU,
}


async def route_llm(
    task_class: TaskClass,
    *,
    tenant_id: UUID | None = None,
) -> LLMTier:
    """Return the canonical :class:`LLMTier` for ``task_class``.

    When ``tenant_id`` is provided, runs the budget gate:
    :class:`BudgetStatus.WARN_80` triggers the auto-downgrade per
    :data:`_DOWNGRADE_TABLE`; :class:`BudgetStatus.BLOCK_100` raises
    :class:`BudgetExceededError` (RFC 7807 status 402).

    Emits structlog ``observability.llm.route_chosen`` with the chosen
    tier, the reason (``ok`` / ``warn_80_downgrade`` / ``no_tenant``),
    and the budget gate state (when consulted).
    """
    base_tier = _ROUTING_TABLE[task_class]

    if tenant_id is None:
        log.info(
            "observability.llm.route_chosen",
            task_class=task_class.value,
            tier=base_tier.value,
            reason="no_tenant",
        )
        return base_tier

    state = await check_budget(tenant_id)

    if state.status is BudgetStatus.BLOCK_100:
        log.warning(
            "observability.llm.route_chosen",
            task_class=task_class.value,
            tier=base_tier.value,
            reason="block_100",
            tenant_id=str(tenant_id),
            percent_used=state.percent_used,
        )
        raise BudgetExceededError(
            detail=(
                f"Tenant {tenant_id} exceeded the monthly LLM budget cap "
                f"of {state.cap_usd} USD ({state.percent_used}% used). "
                "Raise the cap via `iguanatrader admin set-budget` "
                "(slice O2) or wait for next-month rollover."
            ),
        )

    if state.status is BudgetStatus.WARN_80:
        downgraded = _DOWNGRADE_TABLE.get(base_tier, base_tier)
        log.info(
            "observability.llm.route_chosen",
            task_class=task_class.value,
            tier=downgraded.value,
            reason="warn_80_downgrade",
            tenant_id=str(tenant_id),
            base_tier=base_tier.value,
            percent_used=state.percent_used,
        )
        return downgraded

    log.info(
        "observability.llm.route_chosen",
        task_class=task_class.value,
        tier=base_tier.value,
        reason="ok",
        tenant_id=str(tenant_id),
        percent_used=state.percent_used,
    )
    return base_tier


__all__ = [
    "LLMTier",
    "TaskClass",
    "route_llm",
]
