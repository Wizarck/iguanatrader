"""In-memory :class:`HindsightPort` (test/dev) — slice R6.

Constructor seeds a ``{bank: list[str]}`` dict. ``recall`` filters by
case-insensitive substring match on ``query``; ``retain`` appends a
formatted entry. Used by:

* Integration tests (``test_hindsight_recall_gated.py``,
  ``test_hindsight_retain_always_on.py``).
* Dev workflows where running an HTTP MCP backend locally is friction.
* Default daemon adapter when ``IGUANATRADER_HINDSIGHT_URL`` env-var
  is unset (dev-friendly degradation).
"""

from __future__ import annotations

from typing import Any


class InMemoryHindsightAdapter:
    """Dict-backed fake. Deterministic behaviour for tests."""

    def __init__(self, *, seed: dict[str, list[str]] | None = None) -> None:
        self._banks: dict[str, list[str]] = {k: list(v) for k, v in seed.items()} if seed else {}

    async def recall(
        self,
        *,
        bank: str,
        query: str,
        limit: int = 20,
        timeout_ms: int = 2000,
    ) -> list[str]:
        del timeout_ms  # unused in the fake; tests don't exercise timing
        entries = self._banks.get(bank, [])
        if not query:
            return entries[:limit]
        # Real Hindsight uses vector search; the fake approximates this by
        # treating the query as a bag of words and matching any entry that
        # contains at least one token (case-insensitive). Substring-of-
        # whole-query would miss everything when the caller passes a multi-
        # word semantic query.
        tokens = [t for t in query.lower().split() if t]
        if not tokens:
            return entries[:limit]
        matches = [e for e in entries if any(t in e.lower() for t in tokens)]
        return matches[:limit]

    async def retain(
        self,
        *,
        bank: str,
        kind: str,
        content: str,
        metadata: dict[str, Any],
    ) -> None:
        del metadata  # captured implicitly by the formatted string in v1
        self._banks.setdefault(bank, []).append(f"[{kind}] {content}")

    # Test helpers (NOT part of the Protocol).
    def _entries(self, bank: str) -> list[str]:
        return list(self._banks.get(bank, []))


__all__ = ["InMemoryHindsightAdapter"]
