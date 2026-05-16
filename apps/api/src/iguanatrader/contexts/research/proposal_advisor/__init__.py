"""LLM-driven proposal advisory services (slice ``llm-observability-and-signals``).

Two services:

* :class:`ProposalExplainerService` — produces a human-readable
  narrative for an existing :class:`TradeProposal`. Read-only,
  idempotent at the side-effect level (no DB mutation), tagged as
  ``application=iguanatrader-explainer`` in the Langfuse / ELIGIA
  dashboard cost-by-tag widgets.

* :class:`ProposalRiskAssessor` — returns a 0-100 risk score + flags
  + rationale for a proposal, informed by the tenant's recent trades
  and open positions. **Informational** — does not block the
  approval flow. Tagged ``application=iguanatrader-risk``.

Both services consume the same :class:`AnthropicLLMClient` adapter but
target different Anthropic models (haiku for explainer, sonnet for
risk) per the cost / quality trade-off documented in
``docs/decisions/0001-llm-observability-langfuse.md``.
"""

from iguanatrader.contexts.research.proposal_advisor.explainer import (
    ProposalExplainerResult,
    ProposalExplainerService,
)
from iguanatrader.contexts.research.proposal_advisor.risk import (
    ProposalRiskAssessment,
    ProposalRiskAssessor,
)

__all__ = [
    "ProposalExplainerResult",
    "ProposalExplainerService",
    "ProposalRiskAssessment",
    "ProposalRiskAssessor",
]
