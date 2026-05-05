"""In-process Perplexity rate-limit throttle (NFR-I4 + design D3).

Sliding-window counter: a :class:`collections.deque` of monotonic
timestamps for the last 60 seconds, protected by :class:`asyncio.Lock`.
``acquire()`` evicts entries older than 60s, checks
``len(deque) < max_rpm``, appends the current timestamp + returns;
otherwise raises :class:`PerplexityRateLimitError` with a
``retry_after_seconds`` hint (seconds until the oldest entry ages out
of the window).

Process-local. Multi-worker uvicorn deployments multiply effective rate
by worker count — documented in design D3 risks + ``docs/gotchas.md``
candidate #33. v2 SaaS migration to Redis-backed window deferred to
``docs/architecture-decisions.md`` cross-reference (no new ADR for this
slice).

The :func:`get_throttle` factory returns a process-local singleton
keyed off the configured ``max_rpm``. Tests reset the singleton via
:func:`reset_throttle_for_tests`.
"""

from __future__ import annotations

import asyncio
import math
import os
import time
from collections import deque

import structlog

from iguanatrader.contexts.observability.errors import PerplexityRateLimitError
from iguanatrader.contexts.observability.ports import ClockPort

log = structlog.get_logger("iguanatrader.contexts.observability.perplexity_throttle")

#: Default max requests per minute when ``IGUANATRADER_PERPLEXITY_MAX_RPM``
#: is unset (per Perplexity's documented hard cap; design D3).
DEFAULT_MAX_RPM: int = 60

#: Sliding-window length in seconds.
WINDOW_SECONDS: int = 60


class _MonotonicClock:
    """Default :class:`ClockPort` adapter — wraps :func:`time.monotonic`."""

    def monotonic(self) -> float:
        return time.monotonic()


class PerplexityThrottle:
    """Sliding-window rate-limit (per design D3 + NFR-I4).

    Constructed with ``max_rpm`` (default 60) and an optional
    :class:`ClockPort` for testability.
    """

    def __init__(
        self,
        max_rpm: int = DEFAULT_MAX_RPM,
        *,
        clock: ClockPort | None = None,
    ) -> None:
        if max_rpm <= 0:
            raise ValueError(f"max_rpm must be > 0, got {max_rpm!r}")
        self._max_rpm: int = max_rpm
        self._clock: ClockPort = clock or _MonotonicClock()
        self._timestamps: deque[float] = deque()
        self._lock: asyncio.Lock = asyncio.Lock()

    @property
    def max_rpm(self) -> int:
        """Current configured RPM limit."""
        return self._max_rpm

    @property
    def queue_length(self) -> int:
        """Number of timestamps currently in the window — for tests / debug."""
        return len(self._timestamps)

    async def acquire(self) -> None:
        """Block-or-raise: register a request slot in the rolling window.

        On success: appends the current monotonic timestamp + returns
        (caller proceeds to make the Perplexity HTTP call).

        On overflow: raises :class:`PerplexityRateLimitError` with
        ``retry_after_seconds`` set to ``ceil(WINDOW_SECONDS - age_of_oldest)``
        — the integer seconds until the oldest in-window timestamp ages
        out and the next slot frees.
        """
        async with self._lock:
            now_t = self._clock.monotonic()
            cutoff = now_t - WINDOW_SECONDS

            # Evict expired entries.
            while self._timestamps and self._timestamps[0] <= cutoff:
                self._timestamps.popleft()

            if len(self._timestamps) < self._max_rpm:
                self._timestamps.append(now_t)
                log.debug(
                    "observability.throttle.applied",
                    decision="allow",
                    max_rpm=self._max_rpm,
                    in_window=len(self._timestamps),
                )
                return

            # Over the cap — compute retry_after from the oldest timestamp.
            age_of_oldest = now_t - self._timestamps[0]
            remaining = WINDOW_SECONDS - age_of_oldest
            retry_after = max(1, math.ceil(remaining))
            log.warning(
                "observability.throttle.applied",
                decision="block",
                max_rpm=self._max_rpm,
                in_window=len(self._timestamps),
                retry_after_seconds=retry_after,
            )
            raise PerplexityRateLimitError(
                detail=(
                    f"Perplexity rate limit hit ({self._max_rpm} rpm); "
                    f"retry in ~{retry_after}s."
                ),
                retry_after_seconds=retry_after,
            )

    def reset(self) -> None:
        """Drop the window contents. Test-only helper."""
        self._timestamps.clear()


_singleton: PerplexityThrottle | None = None


def get_throttle() -> PerplexityThrottle:
    """Return the process-local singleton :class:`PerplexityThrottle`.

    Reads ``IGUANATRADER_PERPLEXITY_MAX_RPM`` (env, default
    :data:`DEFAULT_MAX_RPM`). The singleton is created on first call
    and reused for the life of the process.
    """
    global _singleton
    if _singleton is None:
        raw = os.getenv("IGUANATRADER_PERPLEXITY_MAX_RPM")
        max_rpm = DEFAULT_MAX_RPM
        if raw is not None:
            try:
                parsed = int(raw)
                if parsed > 0:
                    max_rpm = parsed
            except ValueError:
                pass
        _singleton = PerplexityThrottle(max_rpm=max_rpm)
    return _singleton


def reset_throttle_for_tests() -> None:
    """Drop the process-local singleton. Test-only helper."""
    global _singleton
    _singleton = None


__all__ = [
    "DEFAULT_MAX_RPM",
    "WINDOW_SECONDS",
    "PerplexityThrottle",
    "get_throttle",
    "reset_throttle_for_tests",
]
