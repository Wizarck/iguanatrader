"""``ProposalExplainerService`` — LLM narrative for an existing proposal.

Read-only service. Consumes a :class:`TradeProposal` already persisted
by the strategy emitter and asks the LLM to produce a 2-3 paragraph
human-readable explanation: which signal fired, what the rationale
boils down to in plain English, and how a non-trading-savvy operator
should interpret the entry / stop levels.

Tagged ``application=iguanatrader-explainer`` so the ELIGIA
``Top by Application`` widget shows the explainer's spend separately
from synthesis / risk / journal. Default model is ``claude-3-5-haiku``
(latency-first, low cost per call) — sonnet would be overkill for a
restatement task.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog

from iguanatrader.contexts.research.synthesis.llm_client import LLMClient

log = structlog.get_logger("iguanatrader.contexts.research.proposal_advisor.explainer")

#: Default model for the explainer flow — fast + cheap; the task is
#: restatement, not novel reasoning.
DEFAULT_EXPLAINER_MODEL = "claude-3-5-haiku-20241022"

#: Hard ceiling on output tokens. Explanations are 2-3 paragraphs.
EXPLAINER_MAX_TOKENS = 800

PROMPT_TEMPLATE = """\
You are a trading-assistant LLM. The user is reviewing an automatically
generated trade proposal and wants a 2-3 paragraph plain-English
explanation. Do NOT recommend approving or rejecting the trade — your
role is descriptive.

# Proposal

* Symbol: {symbol}
* Side: {side}
* Quantity: {quantity}
* Indicative entry price: {entry_price_indicative}
* Stop price: {stop_price}
* Confidence score (0-1): {confidence_score}
* Mode: {mode}
* Reasoning payload (machine-generated, structured): {reasoning_json}

# Required output

Write 2-3 short paragraphs in English explaining:

1. Which signal or strategy generated this proposal (infer from the
   ``reasoning`` payload).
2. The risk envelope — entry vs. stop, in percent terms.
3. What a careful reviewer should sanity-check before approving.

Be concise. Do NOT include preamble like "Sure, here's…". Plain
markdown only. No code fences.
"""


@dataclass(frozen=True, slots=True)
class ProposalExplainerResult:
    """Service-level return; route layer maps to a DTO."""

    proposal_id: str
    narrative: str
    model: str
    generated_at: datetime
    tokens_input: int
    tokens_output: int


class ProposalExplainerService:
    """Asks the LLM to narrate an existing proposal in 2-3 paragraphs."""

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        model: str = DEFAULT_EXPLAINER_MODEL,
    ) -> None:
        self._llm = llm_client
        self._model = model

    async def explain(
        self,
        *,
        proposal_id: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        entry_price_indicative: Decimal,
        stop_price: Decimal,
        confidence_score: Decimal | None,
        mode: str,
        reasoning: dict[str, Any],
    ) -> ProposalExplainerResult:
        """Render the prompt + call the LLM + wrap the response."""
        import json

        prompt = PROMPT_TEMPLATE.format(
            symbol=symbol,
            side=side,
            quantity=str(quantity),
            entry_price_indicative=str(entry_price_indicative),
            stop_price=str(stop_price),
            confidence_score=(
                str(confidence_score) if confidence_score is not None else "unspecified"
            ),
            mode=mode,
            reasoning_json=json.dumps(reasoning, sort_keys=True, default=str),
        )
        completion = await self._llm.complete(
            prompt=prompt,
            model=self._model,
            replay_key=None,
            max_tokens=EXPLAINER_MAX_TOKENS,
            langfuse_application="iguanatrader-explainer",
        )
        log.info(
            "research.proposal_advisor.explainer.completed",
            proposal_id=proposal_id,
            model=self._model,
            tokens_input=completion.tokens_input,
            tokens_output=completion.tokens_output,
        )
        return ProposalExplainerResult(
            proposal_id=proposal_id,
            narrative=completion.text.strip(),
            model=completion.model,
            generated_at=datetime.now(UTC),
            tokens_input=completion.tokens_input,
            tokens_output=completion.tokens_output,
        )


__all__ = [
    "DEFAULT_EXPLAINER_MODEL",
    "EXPLAINER_MAX_TOKENS",
    "ProposalExplainerResult",
    "ProposalExplainerService",
]
