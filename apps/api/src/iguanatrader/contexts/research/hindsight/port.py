"""HindsightPort Protocol (slice R6).

Two methods - one read (``recall``, gated by feature flag) and one
write (``retain``, always-on FR80). Concrete adapters implement
structurally; mypy --strict enforces conformance.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class HindsightPort(Protocol):
    """Read + write interface to the Hindsight memory bank.

    ``bank`` is the canonical key per tenant:
    ``iguanatrader-research-<tenant_id>``. The caller computes it; the
    adapter does not depend on tenant resolution.
    """

    async def recall(
        self,
        *,
        bank: str,
        query: str,
        limit: int = 20,
        timeout_ms: int = 2000,
    ) -> list[str]:
        """Return up to ``limit`` narrative chunks ranked by relevance.

        Empty list on no hits. Raises :class:`HindsightUnavailable` or
        :class:`HindsightTimeout` on failure - caller is expected to
        log + degrade gracefully (FR81 + NFR-I8).
        """
        ...

    async def retain(
        self,
        *,
        bank: str,
        kind: str,
        content: str,
        metadata: dict[str, Any],
    ) -> None:
        """Persist a narrative chunk to the bank.

        Raises :class:`HindsightUnavailable`, :class:`HindsightTimeout`,
        or :class:`HindsightWriteFailed` on failure. Caller wraps in
        try/except for graceful degradation (FR80 always-on but
        non-blocking).
        """
        ...


__all__ = ["HindsightPort"]
