"""``ProposalRiskAssessor`` — LLM-driven risk review for a proposal.

Returns a structured risk assessment: ``risk_score`` (0-100, higher =
more risk), a list of ``flags`` (free-form strings), and a one-paragraph
``rationale``. **Informational only** — does NOT block the proposal
approval flow; the route layer surfaces the result as a sibling view.

Context fed to the LLM: the proposal under review + a short snapshot
of the tenant's recent trades (closed P&L, win/loss streak) + open
positions count. The aim is to flag the obvious ("you're already
maxed in tech sector", "five consecutive losses", "stop is unusually
tight") without claiming domain-expert authority.

Default model is ``claude-3-5-sonnet`` because the task involves
multi-attribute reasoning (sector, sequence, sizing) where haiku
under-delivers in informal benchmarks. The Langfuse application tag
is ``iguanatrader-risk``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog

from iguanatrader.contexts.research.synthesis.llm_client import LLMClient

log = structlog.get_logger("iguanatrader.contexts.research.proposal_advisor.risk")

#: Default model for the risk-review flow — multi-attribute reasoning.
DEFAULT_RISK_MODEL = "claude-3-5-sonnet-20241022"

#: Output token ceiling. Risk review is structured + concise.
RISK_MAX_TOKENS = 1200

PROMPT_TEMPLATE = """\
You are a trading-risk reviewer. The user is about to approve an
automated trade proposal and wants a brief risk assessment. You do NOT
approve or reject — you flag concerns.

# Proposal under review

* Symbol: {symbol}
* Side: {side}
* Quantity: {quantity}
* Indicative entry price: {entry_price_indicative}
* Stop price: {stop_price}
* Confidence score (0-1): {confidence_score}
* Mode: {mode}
* Strategy reasoning (machine-generated): {reasoning_json}

# Tenant trading context (last 30 days)

* Recent closed trades (P&L summary): {recent_trades_summary}
* Open positions count: {open_positions_count}

# Required output

Return a single JSON object (no surrounding prose) with these keys:

```
{{
  "risk_score": <integer 0-100, higher means more risk>,
  "flags": [<short string concerns, max 5 items>],
  "rationale": "<one paragraph explaining the score>"
}}
```

Do NOT wrap in markdown fences. Do NOT add commentary outside the JSON.
"""

_JSON_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True, slots=True)
class ProposalRiskAssessment:
    """Service-level return; route layer maps to a DTO."""

    proposal_id: str
    risk_score: int
    flags: list[str]
    rationale: str
    model: str
    generated_at: datetime
    tokens_input: int
    tokens_output: int


class RiskAssessmentParseError(Exception):
    """LLM returned a body we could not parse into the expected JSON shape."""


class ProposalRiskAssessor:
    """Single-call risk review producing a structured score + flags."""

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        model: str = DEFAULT_RISK_MODEL,
    ) -> None:
        self._llm = llm_client
        self._model = model

    async def assess(
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
        recent_trades_summary: str,
        open_positions_count: int,
    ) -> ProposalRiskAssessment:
        """Run the assessment + parse the JSON return shape."""
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
            recent_trades_summary=recent_trades_summary or "no recent trades",
            open_positions_count=open_positions_count,
        )
        completion = await self._llm.complete(
            prompt=prompt,
            model=self._model,
            replay_key=None,
            max_tokens=RISK_MAX_TOKENS,
            langfuse_application="iguanatrader-risk",
        )
        parsed = self._parse_json_body(completion.text)
        score = int(parsed.get("risk_score", 0))
        score = max(0, min(100, score))
        flags_raw = parsed.get("flags") or []
        flags = [str(f) for f in flags_raw if isinstance(f, str | int | float)][:5]
        rationale = str(parsed.get("rationale", "")).strip()
        log.info(
            "research.proposal_advisor.risk.completed",
            proposal_id=proposal_id,
            risk_score=score,
            flags_count=len(flags),
            model=self._model,
            tokens_input=completion.tokens_input,
            tokens_output=completion.tokens_output,
        )
        return ProposalRiskAssessment(
            proposal_id=proposal_id,
            risk_score=score,
            flags=flags,
            rationale=rationale,
            model=completion.model,
            generated_at=datetime.now(UTC),
            tokens_input=completion.tokens_input,
            tokens_output=completion.tokens_output,
        )

    @staticmethod
    def _parse_json_body(text: str) -> dict[str, Any]:
        """Extract the first ``{...}`` JSON object from the LLM response.

        Robust against the model wrapping the JSON in extra prose (the
        prompt explicitly forbids fences but LLMs ignore that ~5% of
        the time). Raises :class:`RiskAssessmentParseError` if no JSON
        object can be located, so the route layer returns a 502
        upstream-error rather than a malformed 200.
        """
        match = _JSON_PATTERN.search(text)
        if not match:
            raise RiskAssessmentParseError(
                f"could not locate JSON object in LLM response: {text[:200]!r}"
            )
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise RiskAssessmentParseError(
                f"JSON decode failed: {exc}; payload: {match.group(0)[:200]!r}"
            ) from exc
        if not isinstance(data, dict):
            raise RiskAssessmentParseError(f"expected JSON object, got {type(data).__name__}")
        return data


__all__ = [
    "DEFAULT_RISK_MODEL",
    "RISK_MAX_TOKENS",
    "ProposalRiskAssessment",
    "ProposalRiskAssessor",
    "RiskAssessmentParseError",
]
