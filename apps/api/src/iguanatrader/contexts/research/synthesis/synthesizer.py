"""Brief synthesizer — orchestrates the 7-step pipeline (slice R5 D3).

Per design D3:

1. Fetch features via :class:`CompositeFeatureProvider`.
2. Score methodology (pure function from ``methodology/<name>.py``).
3. Render prompt template with feature bundle + citations + result.
4. Invoke LLM (single call per refresh) — :class:`LLMClient.complete`.
5. Parse output (markdown body + JSON ``audit_trail_entries`` block).
6. Validate ``[fact:<uuid>]`` markers against the input bundle.
7. Return synthesised brief + audit entries (caller persists in
   transaction with retry-on-version-collision).

The synthesizer DOES NOT touch the repository directly — that is
:class:`BriefService.refresh`'s job (``service.py``). This separation
keeps the synthesizer testable as a pure pipeline.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from iguanatrader.contexts.research.errors import (
    BriefSynthesisShortError,
    InvalidCitationError,
)
from iguanatrader.contexts.research.feature_provider.base import FeatureBundle
from iguanatrader.contexts.research.methodology import (
    METHODOLOGY_REGISTRY,
    MethodologyResult,
)
from iguanatrader.contexts.research.synthesis.audit_trail import AuditTrailEntry
from iguanatrader.contexts.research.synthesis.citation_resolver import CitationResolver
from iguanatrader.contexts.research.synthesis.llm_client import (
    LLMClient,
    LLMCompletion,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

#: Minimum word count for a synthesised brief body. Below this floor the
#: synthesizer raises :class:`BriefSynthesisShortError` (design Q3).
MIN_BODY_WORDS = 100

#: Maximum tokens we ask the LLM to produce per call. Bounds cost.
MAX_OUTPUT_TOKENS = 2000

#: Path to the prompt-template directory. Each methodology has a sibling
#: ``<name>.md`` Jinja2-ish template (we use minimal ``str.format_map``
#: to avoid the Jinja2 dep — templates only need ``{symbol}``,
#: ``{methodology}``, ``{rationale}``, ``{features_block}``,
#: ``{citations_block}`` placeholders).
PROMPT_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True, slots=True)
class SynthesizedBrief:
    """Synthesizer return — caller persists in a transaction."""

    body_markdown: str
    audit_entries: list[AuditTrailEntry]
    pillars: dict[str, Decimal]
    overall_score: Decimal
    rationale: str
    missing_features: list[str]
    partial: bool
    llm_completion: LLMCompletion
    citations_used: list[UUID]


class Synthesizer:
    """Sync orchestrator over the 7-step synthesis pipeline."""

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    async def synthesize(
        self,
        *,
        symbol: str,
        methodology: str,
        feature_bundle: FeatureBundle,
        methodology_result: MethodologyResult,
        model: str,
    ) -> SynthesizedBrief:
        """Run the synthesis pipeline against ``feature_bundle``."""
        if methodology not in METHODOLOGY_REGISTRY:
            raise ValueError(
                f"unknown methodology {methodology!r}; "
                f"expected one of {sorted(METHODOLOGY_REGISTRY)}"
            )

        prompt = self._render_prompt(
            symbol=symbol,
            methodology=methodology,
            feature_bundle=feature_bundle,
            methodology_result=methodology_result,
        )
        replay_key = self._compute_replay_key(
            symbol=symbol,
            methodology=methodology,
            feature_bundle=feature_bundle,
        )
        completion = await self._llm.complete(
            prompt=prompt,
            model=model,
            replay_key=replay_key,
            max_tokens=MAX_OUTPUT_TOKENS,
        )

        body_markdown, audit_entries = self._parse_output(completion.text)

        if len(body_markdown.split()) < MIN_BODY_WORDS:
            raise BriefSynthesisShortError(
                detail=(
                    f"synthesised brief for {symbol} is shorter than {MIN_BODY_WORDS} "
                    f"words ({len(body_markdown.split())} found)"
                )
            )

        # Citation validation against the input bundle.
        allowed = set(feature_bundle.fact_citations.values())
        invalid = CitationResolver.validate_against_bundle(body_markdown, allowed)
        if invalid:
            raise InvalidCitationError(
                detail=(
                    f"synthesised brief for {symbol} cites unknown fact ids "
                    f"{[str(u) for u in invalid]}; allowed: {[str(u) for u in allowed]}"
                )
            )

        partial_required_a_missing = any(
            tier == "A" and value is None for value, tier in feature_bundle.values.values()
        )
        # `partial` triggers when an LLM-emitted JSON block flagged it,
        # OR when a required tier-A feature is missing.
        partial = partial_required_a_missing or self._is_partial_in_text(completion.text)

        pillars_decimals = {
            name: pillar.score for name, pillar in methodology_result.pillars.items()
        }

        cited_ids = CitationResolver.parse_markers(body_markdown)

        return SynthesizedBrief(
            body_markdown=body_markdown,
            audit_entries=audit_entries,
            pillars=pillars_decimals,
            overall_score=methodology_result.overall_score,
            rationale=methodology_result.rationale,
            missing_features=methodology_result.missing_features,
            partial=partial,
            llm_completion=completion,
            citations_used=cited_ids,
        )

    # ------------------------------------------------------------------
    # Prompt rendering
    # ------------------------------------------------------------------

    def _render_prompt(
        self,
        *,
        symbol: str,
        methodology: str,
        feature_bundle: FeatureBundle,
        methodology_result: MethodologyResult,
    ) -> str:
        template = self._load_template(methodology)

        features_lines: list[str] = []
        for name, (value, tier) in feature_bundle.values.items():
            citation = feature_bundle.fact_citations.get(name)
            citation_str = f"[fact:{citation}]" if citation else "(no citation)"
            value_str = "None" if value is None else str(value)
            features_lines.append(f"- {name} (tier {tier}): {value_str} {citation_str}")
        features_block = "\n".join(features_lines) or "(no features available)"

        citations_lines: list[str] = []
        for name, fact_id in feature_bundle.fact_citations.items():
            citations_lines.append(f"- {name} → [fact:{fact_id}]")
        citations_block = "\n".join(citations_lines) or "(no citations available)"

        return template.format_map(
            {
                "symbol": symbol,
                "methodology": methodology,
                "rationale": methodology_result.rationale,
                "overall_score": f"{methodology_result.overall_score:.3f}",
                "features_block": features_block,
                "citations_block": citations_block,
            }
        )

    @staticmethod
    def _load_template(methodology: str) -> str:
        path = PROMPT_DIR / f"{methodology}.md"
        if not path.exists():
            raise FileNotFoundError(
                f"prompt template not found for methodology {methodology!r} at {path}"
            )
        return path.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Replay key
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_replay_key(
        *,
        symbol: str,
        methodology: str,
        feature_bundle: FeatureBundle,
    ) -> str:
        """Stable hash over the bundle so replay_cache returns same output."""
        canonical: dict[str, Any] = {
            "symbol": symbol,
            "methodology": methodology,
            "values": {
                name: (str(value) if value is not None else None, tier)
                for name, (value, tier) in feature_bundle.values.items()
            },
            "citations": {name: str(fid) for name, fid in feature_bundle.fact_citations.items()},
        }
        body = json.dumps(canonical, sort_keys=True)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
        return f"brief:{symbol}:{methodology}:{digest}"

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    _AUDIT_TRAIL_RE = re.compile(
        r"```json\s*(\{.*?\"audit_trail_entries\".*?\})\s*```",
        re.DOTALL,
    )

    @classmethod
    def _parse_output(cls, text: str) -> tuple[str, list[AuditTrailEntry]]:
        """Extract markdown body + audit_trail_entries from LLM output."""
        match = cls._AUDIT_TRAIL_RE.search(text)
        if match is None:
            return text.strip(), []
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            logger.warning("research.synthesis.audit_trail_block_unparseable")
            return text.strip(), []

        body = (text[: match.start()] + text[match.end() :]).strip()
        raw_entries = payload.get("audit_trail_entries", [])
        if not isinstance(raw_entries, list):
            return body, []
        entries: list[AuditTrailEntry] = []
        for raw in raw_entries:
            if not isinstance(raw, dict):
                continue
            metric = str(raw.get("metric", "")).strip()
            formula = str(raw.get("formula", "")).strip()
            if not metric or not formula:
                continue
            inputs_raw = raw.get("inputs", [])
            inputs = inputs_raw if isinstance(inputs_raw, list) else []
            steps_raw = raw.get("steps", [])
            steps = steps_raw if isinstance(steps_raw, list) else []
            entries.append(
                AuditTrailEntry(
                    metric=metric,
                    formula=formula,
                    inputs=inputs,
                    steps=steps,
                    final_output=str(raw.get("final_output", "")).strip(),
                )
            )
        return body, entries

    @staticmethod
    def _is_partial_in_text(text: str) -> bool:
        """Detect ``partial=true`` flag in LLM output (case-insensitive)."""
        lowered = text.lower()
        return "partial=true" in lowered or '"partial": true' in lowered


__all__ = [
    "MAX_OUTPUT_TOKENS",
    "MIN_BODY_WORDS",
    "PROMPT_DIR",
    "SynthesizedBrief",
    "Synthesizer",
]
