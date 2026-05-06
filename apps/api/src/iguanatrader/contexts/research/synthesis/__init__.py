"""Brief synthesis pipeline (slice R5 design D3).

Public exports:

* :class:`Synthesizer` — orchestrates feature → methodology → LLM →
  citation parse → audit trail.
* :class:`CitationResolver` — parses ``[fact:<uuid>]`` markers and
  resolves them against ``research_facts``.
* :class:`AuditTrailService` — persists per-metric audit rows.
* :class:`SynthesizedBrief` — synthesizer return tuple.
* :class:`LLMClient` — Protocol the synthesizer consumes; tests inject
  :class:`FakeLLMClient`. Production wiring (Anthropic SDK) lands in a
  follow-up deployment slice.
"""

from __future__ import annotations

from iguanatrader.contexts.research.synthesis.audit_trail import AuditTrailService
from iguanatrader.contexts.research.synthesis.citation_resolver import (
    CitationResolver,
    ResolvedCitation,
)
from iguanatrader.contexts.research.synthesis.llm_client import (
    FakeLLMClient,
    LLMClient,
    LLMCompletion,
)
from iguanatrader.contexts.research.synthesis.synthesizer import (
    SynthesizedBrief,
    Synthesizer,
)

__all__ = [
    "AuditTrailService",
    "CitationResolver",
    "FakeLLMClient",
    "LLMClient",
    "LLMCompletion",
    "ResolvedCitation",
    "SynthesizedBrief",
    "Synthesizer",
]
