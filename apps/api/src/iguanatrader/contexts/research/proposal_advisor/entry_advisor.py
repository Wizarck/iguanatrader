"""``EntryAdvisor`` — LLM-driven ENTRY-VETO opinion for a fresh proposal (WS-2).

Symmetric sibling of the WS-5 :class:`ExitAdvisor`: where the exit advisor asks
"should the owner SELL this open position urgently?", the entry advisor asks
"should this brand-new entry proposal be BLOCKED before it ever reaches the
owner?". It is a HARD pre-filter — when it vetoes with conviction the proposal
is dropped at ``propose()`` and no Telegram approval card is ever raised; when
it does not veto, the proposal continues to the existing risk → approval → HITL
Telegram flow unchanged (the human still decides).

Given the proposal, the latest fundamental brief thesis, recalled historical
context, and recent trade outcomes, the advisor returns ``veto`` + a confidence.
It is told to veto ONLY with conviction (the brief thesis contradicts the
setup, the recalled history shows this exact setup repeatedly lost, an acute
known risk) and to default to PROCEED when uncertain — the human HITL approval
is still downstream, so a marginal proposal should reach it, not be silently
killed.

Model: **Claude Opus 4.8** — per the owner, the actual *risk evaluation /
veto judgement* runs on Opus; Sonnet is reserved for information *synthesis*
(the ``BriefService`` thesis the advisor reads here). The Langfuse application
tag is ``iguanatrader-entry``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog

from iguanatrader.contexts.research.synthesis.llm_client import LLMClient

log = structlog.get_logger("iguanatrader.contexts.research.proposal_advisor.entry_advisor")

#: Default model for the entry-veto judgement. Opus 4.8 — the owner reserves
#: Opus for actual risk evaluation / judgement, Sonnet for synthesis.
DEFAULT_ENTRY_MODEL = "claude-opus-4-8"

#: Output token ceiling. The verdict is structured + concise.
ENTRY_MAX_TOKENS = 1200

PROMPT_TEMPLATE = """\
You are a trading-risk gatekeeper. An automated strategy just produced the
ENTRY proposal below. Your job is to decide whether to BLOCK it BEFORE the
owner is asked to approve it. You do NOT place anything — if you do not block
it, a human still approves or denies it over Telegram afterwards.

Block (veto = true) ONLY with conviction. Strong reasons include: the
fundamental brief thesis directly CONTRADICTS taking this side now (e.g. a long
into a broken thesis / imminent negative catalyst); the recalled history shows
this exact setup repeatedly led to losses; an acute, concrete known risk
(earnings/macro print within the holding horizon that the stop cannot survive).
If the evidence is weak, ambiguous, or merely "I'd prefer not to", PROCEED
(veto = false) and let the human decide — a marginal proposal should reach the
owner, not be silently killed. Blocking a good trade costs the owner
opportunity; only veto when you would refuse it yourself.

# Entry proposal

* Symbol: {symbol}
* Side: {side}            (buy = open long, sell = open short)
* Quantity: {quantity}
* Indicative entry price: {entry_price}
* Protective stop price: {stop_price}
* Take-profit target: {target_price}
* Strategy confidence (0..1): {confidence_score}
* Strategy reasoning (machine-generated): {reasoning_json}

# Latest fundamental brief (thesis)

{brief_thesis}

# Recalled historical context

{hindsight_chunks}

# Recent trade outcomes

{recent_trades_summary}

# Required output

Return a single JSON object (no surrounding prose, no markdown fences):

{{
  "veto": <true|false>,
  "confidence": <number 0..1, your conviction in the recommendation>,
  "rationale": "<one short paragraph: why block, or why let it through>",
  "flags": [<short string reasons, max 5 items>]
}}
"""

_JSON_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True, slots=True)
class EntryAdvisorVerdict:
    """Service-level entry-veto opinion."""

    symbol: str
    veto: bool
    confidence: Decimal
    rationale: str
    flags: list[str]
    model: str
    generated_at: datetime
    tokens_input: int
    tokens_output: int


class EntryAdvisorParseError(Exception):
    """LLM returned a body we could not parse into the expected JSON shape."""


def _coerce_confidence(value: object) -> Decimal:
    try:
        conf = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")
    if conf < 0:
        return Decimal("0")
    if conf > 1:
        return Decimal("1")
    return conf


class EntryAdvisor:
    """Single-call entry-veto opinion (Opus) producing veto + confidence."""

    def __init__(self, llm_client: LLMClient, *, model: str = DEFAULT_ENTRY_MODEL) -> None:
        self._llm = llm_client
        self._model = model

    async def assess(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Decimal,
        entry_price: Decimal | None,
        stop_price: Decimal | None,
        target_price: Decimal | None,
        confidence_score: Decimal | None,
        reasoning: dict[str, Any],
        brief_thesis: str | None,
        hindsight_chunks: list[str],
        recent_trades_summary: str,
    ) -> EntryAdvisorVerdict:
        """Run the entry-veto assessment + parse the JSON return shape."""
        prompt = PROMPT_TEMPLATE.format(
            symbol=symbol,
            side=side,
            quantity=str(quantity),
            entry_price=(str(entry_price) if entry_price is not None else "unknown"),
            stop_price=(str(stop_price) if stop_price is not None else "none"),
            target_price=(str(target_price) if target_price is not None else "none"),
            confidence_score=(
                str(confidence_score) if confidence_score is not None else "unspecified"
            ),
            reasoning_json=json.dumps(reasoning, sort_keys=True, default=str),
            brief_thesis=brief_thesis or "no brief available",
            hindsight_chunks=(
                "\n".join(f"* {c}" for c in hindsight_chunks)
                if hindsight_chunks
                else "* none available"
            ),
            recent_trades_summary=recent_trades_summary or "no recent trades",
        )
        completion = await self._llm.complete(
            prompt=prompt,
            model=self._model,
            replay_key=None,
            max_tokens=ENTRY_MAX_TOKENS,
            langfuse_application="iguanatrader-entry",
        )
        parsed = self._parse_json_body(completion.text)
        veto = bool(parsed.get("veto", False))
        confidence = _coerce_confidence(parsed.get("confidence", 0))
        rationale = str(parsed.get("rationale", "")).strip()
        raw_flags = parsed.get("flags")
        flags = (
            [str(f) for f in raw_flags if isinstance(f, str | int | float)][:5]
            if isinstance(raw_flags, list)
            else []
        )
        log.info(
            "research.proposal_advisor.entry.completed",
            symbol=symbol,
            veto=veto,
            confidence=str(confidence),
            flags_count=len(flags),
            model=self._model,
            tokens_input=completion.tokens_input,
            tokens_output=completion.tokens_output,
        )
        return EntryAdvisorVerdict(
            symbol=symbol,
            veto=veto,
            confidence=confidence,
            rationale=rationale,
            flags=flags,
            model=completion.model,
            generated_at=datetime.now(UTC),
            tokens_input=completion.tokens_input,
            tokens_output=completion.tokens_output,
        )

    @staticmethod
    def _parse_json_body(text: str) -> dict[str, object]:
        """Extract the first ``{...}`` JSON object from the LLM response."""
        match = _JSON_PATTERN.search(text)
        if not match:
            raise EntryAdvisorParseError(
                f"could not locate JSON object in LLM response: {text[:200]!r}"
            )
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise EntryAdvisorParseError(
                f"JSON decode failed: {exc}; payload: {match.group(0)[:200]!r}"
            ) from exc
        if not isinstance(data, dict):
            raise EntryAdvisorParseError(f"expected JSON object, got {type(data).__name__}")
        return data


__all__ = [
    "DEFAULT_ENTRY_MODEL",
    "ENTRY_MAX_TOKENS",
    "EntryAdvisor",
    "EntryAdvisorParseError",
    "EntryAdvisorVerdict",
]
