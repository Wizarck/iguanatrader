"""Slice-local :class:`IguanaError` subclasses for the observability context.

Per cross-slice merge rules, slice O1 does NOT modify
:mod:`iguanatrader.shared.errors`. The three new error types live here
in the bounded context that owns them; the global RFC 7807 handler chain
in :mod:`iguanatrader.api.errors` renders any :class:`IguanaError`
subclass uniformly without further wiring.

============================== ====== =================================
Class                           Status Use case
============================== ====== =================================
``BudgetExceededError``         402    Per-tenant monthly LLM budget cap reached (FR41 BLOCK_100).
``PerplexityRateLimitError``    429    In-process sliding-window throttle refused a Perplexity call (NFR-I4).
``ReplayCacheMissError``        500    Test-mode-only — fixture missing for a recorded scenario; signals stale cache + record-mode hint.
============================== ====== =================================

Type URIs follow the project convention
``urn:iguanatrader:error:<kebab-name>``. Clients pattern-match on
``type`` (or ``status``); never on the Python class name.
"""

from __future__ import annotations

from typing import ClassVar

from iguanatrader.shared.errors import IguanaError, RateLimitError


class BudgetExceededError(IguanaError):
    """Per-tenant monthly LLM budget cap reached (HTTP 402 — Payment Required).

    Raised by :func:`iguanatrader.contexts.observability.llm_routing.route_llm`
    when :func:`iguanatrader.contexts.observability.budget.check_budget`
    returns :class:`BudgetStatus.BLOCK_100`. The handler chain renders
    RFC 7807 with ``status=402`` so operators can disambiguate the
    "wallet empty" case from generic 5xx.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:budget-exceeded"
    default_title: ClassVar[str] = "Budget Exceeded"
    default_status: ClassVar[int] = 402


class PerplexityRateLimitError(RateLimitError):
    """In-process sliding-window throttle refused a Perplexity call (HTTP 429).

    Subclass of :class:`RateLimitError` (slice 2 shared kernel) so the
    project-wide ``Retry-After``-aware handlers + middleware route it
    correctly. The :attr:`retry_after_seconds` instance attribute is the
    integer seconds until the next request slot frees in the rolling
    60-second window (per design D3 + NFR-I4).
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:perplexity-rate-limit"
    default_title: ClassVar[str] = "Perplexity Rate Limit"
    default_status: ClassVar[int] = 429

    def __init__(
        self,
        detail: str | None = None,
        *,
        retry_after_seconds: int = 1,
        title: str | None = None,
        status: int | None = None,
        instance: str | None = None,
    ) -> None:
        super().__init__(
            detail=detail,
            title=title,
            status=status,
            instance=instance,
        )
        self.retry_after_seconds: int = retry_after_seconds


class ReplayCacheMissError(IguanaError):
    """Replay-cache fixture missing for a recorded scenario (HTTP 500).

    Test-mode-only — production never raises this because the replay
    cache is a no-op when ``IGUANATRADER_LLM_REPLAY`` is unset. The
    operator playbook for refresh is at
    ``docs/runbooks/replay-cache-refresh.md``.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:replay-cache-miss"
    default_title: ClassVar[str] = "Replay Cache Miss"
    default_status: ClassVar[int] = 500


__all__ = [
    "BudgetExceededError",
    "PerplexityRateLimitError",
    "ReplayCacheMissError",
]
