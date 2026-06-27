"""``ExitAdvisor`` — LLM-driven URGENT-EXIT opinion for an open position (WS-5).

Given an open position, the protective stop/target ACTUALLY resting at the
broker (and any divergence from what the strategy intended), the latest
fundamental brief, recalled historical context, and recent trade outcomes,
the advisor decides whether the owner should be asked to SELL URGENTLY.

It is an OPINION for a human-in-the-loop, never an auto-close: the caller
(the urgent-exit sweep) turns an ``urgent_sell`` verdict above a confidence
threshold into an ``ExitApprovalRequested`` → Telegram approve/deny. The
advisor is told to recommend an urgent sell ONLY with conviction (a broken
thesis, an unprotected position in an adverse move, an acute risk in the
recalled history) and to default to HOLD when uncertain.

Model: **Claude Opus 4.8** — per the owner, the actual *risk evaluation /
opinion* runs on Opus; Sonnet is reserved for information *synthesis* (the
``BriefService`` thesis the advisor reads here). The Langfuse application tag
is ``iguanatrader-exit``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import structlog

from iguanatrader.contexts.research.synthesis.llm_client import LLMClient

log = structlog.get_logger("iguanatrader.contexts.research.proposal_advisor.exit_advisor")

#: Default model for the urgent-exit OPINION. Opus 4.8 — the owner reserves
#: Opus for actual risk evaluation / judgement, Sonnet for synthesis.
DEFAULT_EXIT_MODEL = "claude-opus-4-8"

#: Output token ceiling. The verdict is structured + concise.
EXIT_MAX_TOKENS = 1200

PROMPT_TEMPLATE = """\
You are a trading-risk advisor. The owner holds the OPEN position below. Your
job is to decide whether to ASK THE OWNER (human-in-the-loop) to SELL IT
URGENTLY right now. You do NOT execute anything — a human approves or denies
your recommendation over Telegram.

Recommend an urgent sell ONLY with conviction. Strong reasons include: the
fundamental thesis is broken or invalidated by the brief; the position is
UNPROTECTED at the broker (the protective stop the strategy intended is missing
or wrong) while the price moves against it; the recalled history shows this
setup repeatedly led to acute drawdowns. If the evidence is weak, ambiguous, or
merely "could go either way", recommend HOLD (urgent_sell = false). A false
urgent alarm costs the owner trust; only fire when you would act yourself.

# Open position

* Symbol: {symbol}
* Side held: {side}            (buy = long, sell = short)
* Quantity: {quantity}
* Average entry price: {average_price}
* Current price: {current_price}
* Unrealised P&L: {unrealized_pnl}
* Intended protective stop: {intended_stop}
* Intended take-profit target: {intended_target}

# Protective orders actually at the broker

{resting_orders_summary}

# Divergences detected (intended vs actually resting at IBKR)

{divergences}

# Latest fundamental brief (thesis)

{brief_thesis}

# Recalled historical context

{hindsight_chunks}

# Recent trade outcomes

{recent_trades_summary}

# Required output

Return a single JSON object (no surrounding prose, no markdown fences):

{{
  "urgent_sell": <true|false>,
  "confidence": <number 0..1, your conviction in the recommendation>,
  "rationale": "<one short paragraph: why sell now, or why hold>",
  "flags": [<short string reasons, max 5 items>]
}}
"""

_JSON_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True, slots=True)
class ExitAdvisorVerdict:
    """Service-level urgent-exit opinion."""

    trade_id: str
    urgent_sell: bool
    confidence: Decimal
    rationale: str
    flags: list[str]
    model: str
    generated_at: datetime
    tokens_input: int
    tokens_output: int


class ExitAdvisorParseError(Exception):
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


class ExitAdvisor:
    """Single-call urgent-exit opinion (Opus) producing urgent_sell + confidence."""

    def __init__(self, llm_client: LLMClient, *, model: str = DEFAULT_EXIT_MODEL) -> None:
        self._llm = llm_client
        self._model = model

    async def assess(
        self,
        *,
        trade_id: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        average_price: Decimal | None,
        current_price: Decimal | None,
        unrealized_pnl: Decimal | None,
        intended_stop: Decimal,
        intended_target: Decimal | None,
        resting_orders_summary: str,
        divergences: list[str],
        brief_thesis: str | None,
        hindsight_chunks: list[str],
        recent_trades_summary: str,
    ) -> ExitAdvisorVerdict:
        """Run the urgent-exit assessment + parse the JSON return shape."""
        prompt = PROMPT_TEMPLATE.format(
            symbol=symbol,
            side=side,
            quantity=str(quantity),
            average_price=(str(average_price) if average_price is not None else "unknown"),
            current_price=(str(current_price) if current_price is not None else "unknown"),
            unrealized_pnl=(str(unrealized_pnl) if unrealized_pnl is not None else "unknown"),
            intended_stop=str(intended_stop),
            intended_target=(str(intended_target) if intended_target is not None else "none"),
            resting_orders_summary=resting_orders_summary or "none observed",
            divergences=("\n".join(f"* {d}" for d in divergences) if divergences else "* none"),
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
            max_tokens=EXIT_MAX_TOKENS,
            langfuse_application="iguanatrader-exit",
        )
        parsed = self._parse_json_body(completion.text)
        urgent_sell = bool(parsed.get("urgent_sell", False))
        confidence = _coerce_confidence(parsed.get("confidence", 0))
        rationale = str(parsed.get("rationale", "")).strip()
        raw_flags = parsed.get("flags")
        flags = (
            [str(f) for f in raw_flags if isinstance(f, str | int | float)][:5]
            if isinstance(raw_flags, list)
            else []
        )
        log.info(
            "research.proposal_advisor.exit.completed",
            trade_id=trade_id,
            urgent_sell=urgent_sell,
            confidence=str(confidence),
            flags_count=len(flags),
            model=self._model,
            tokens_input=completion.tokens_input,
            tokens_output=completion.tokens_output,
        )
        return ExitAdvisorVerdict(
            trade_id=trade_id,
            urgent_sell=urgent_sell,
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
            raise ExitAdvisorParseError(
                f"could not locate JSON object in LLM response: {text[:200]!r}"
            )
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ExitAdvisorParseError(
                f"JSON decode failed: {exc}; payload: {match.group(0)[:200]!r}"
            ) from exc
        if not isinstance(data, dict):
            raise ExitAdvisorParseError(f"expected JSON object, got {type(data).__name__}")
        return data


__all__ = [
    "DEFAULT_EXIT_MODEL",
    "EXIT_MAX_TOKENS",
    "ExitAdvisor",
    "ExitAdvisorParseError",
    "ExitAdvisorVerdict",
]
