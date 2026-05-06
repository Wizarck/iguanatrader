"""LLM client Protocol + fake (slice R5 design D3 + D9).

Production wiring of the Anthropic SDK is **deferred** — adding
``anthropic`` as a Python dep is a deployment-slice concern (security
review of the SDK, version pinning, secret-handling for ``ANTHROPIC_API_KEY``).
R5 ships the synthesizer against the :class:`LLMClient` Protocol so
the wiring is one swap when the dep lands.

Until then:

* :class:`FakeLLMClient` returns canned :class:`LLMCompletion` responses
  keyed by ``replay_key``. The synthesizer integration test seeds the
  fake; tests assert deterministic output.
* :class:`AnthropicLLMClient` (NOT shipped here) would wrap
  ``anthropic.Anthropic().messages.create(...)`` decorated with
  :func:`@cost_meter` from O1.

The :class:`LLMResponse` Protocol from O1 is satisfied: every
:class:`LLMCompletion` exposes ``tokens_input``, ``tokens_output``, and
``cached`` so :func:`@cost_meter` can wrap a real client without
modifying the Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LLMCompletion:
    """Concrete completion shape returned by :class:`LLMClient.complete`.

    Mirrors the :class:`iguanatrader.contexts.observability.ports.LLMResponse`
    Protocol shape — fields are positional + properties so ``@cost_meter``
    consumes us correctly.
    """

    text: str
    tokens_input: int
    tokens_output: int
    cached: bool
    model: str
    replay_key: str | None = None


class LLMClient(Protocol):
    """Sync LLM client Protocol consumed by the synthesizer."""

    async def complete(
        self,
        prompt: str,
        *,
        model: str,
        replay_key: str | None,
        max_tokens: int,
    ) -> LLMCompletion:
        """Issue a completion against ``prompt`` and return the response."""
        ...


class FakeLLMClient:
    """In-memory fake — returns canned completions keyed by ``replay_key``.

    Use in tests + the slice-R5 default service wiring (until the
    production Anthropic client lands). When ``replay_key`` is not in
    the registry, returns a stock template so the synthesizer's
    pipeline can still exercise its parse/persist path.
    """

    DEFAULT_TEMPLATE: str = (
        "## Methodology summary\n\n"
        "{rationale}\n\n"
        "Synthesised against the supplied feature bundle. "
        "Below: per-pillar narrative.\n\n"
        "## Pillars\n\n"
        "Pillar-by-pillar narrative (deterministic placeholder until a "
        "real LLM client is wired). Citation example: {first_citation}\n\n"
        "```json\n"
        '{{"audit_trail_entries": []}}\n'
        "```\n"
    )

    def __init__(self, registry: dict[str, str] | None = None) -> None:
        self._registry: dict[str, str] = dict(registry or {})

    def register(self, replay_key: str, body: str) -> None:
        """Add a canned response. Test-only; production callers MUST NOT use."""
        self._registry[replay_key] = body

    async def complete(
        self,
        prompt: str,
        *,
        model: str,
        replay_key: str | None,
        max_tokens: int,
    ) -> LLMCompletion:
        if replay_key is not None and replay_key in self._registry:
            text = self._registry[replay_key]
            cached = True
        else:
            text = self._render_default(prompt)
            cached = False
        return LLMCompletion(
            text=text,
            tokens_input=max(1, len(prompt) // 4),
            tokens_output=max(1, len(text) // 4),
            cached=cached,
            model=model,
            replay_key=replay_key,
        )

    @classmethod
    def _render_default(cls, prompt: str) -> str:
        # Pull a canonical [fact:<uuid>] marker from the prompt if any —
        # makes the fake citation-aware so end-to-end tests can validate
        # the resolver path without a registry entry.
        first_citation = "[fact:00000000-0000-0000-0000-000000000000]"
        if "[fact:" in prompt:
            start = prompt.index("[fact:")
            end = prompt.index("]", start) + 1
            first_citation = prompt[start:end]
        rationale = "Synthesised brief (fake-LLM)."
        return cls.DEFAULT_TEMPLATE.format(rationale=rationale, first_citation=first_citation)


__all__ = ["FakeLLMClient", "LLMClient", "LLMCompletion"]
