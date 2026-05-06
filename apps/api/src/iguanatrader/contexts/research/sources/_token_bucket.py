"""Sync token-bucket rate limiter for Tier-A source adapters (slice R2).

Per slice R2 design D2 + risk-note "rate-limit token bucket coordination":

* One :class:`TokenBucket` instance per concrete adapter class (class-level
  attribute). Multiple :class:`SECEdgarSource` instances within the same
  Python process share the same bucket; cross-process coordination is
  out of MVP (single-process scheduler at v1).
* :meth:`acquire` blocks until a token is available, sleeping in small
  increments. Sync-only — the :class:`SourcePort` contract from R1 is
  synchronous so the adapter call path never enters async-land.
* The bucket is **leaky**: tokens replenish at ``rate`` per second up to
  ``capacity``; a fresh bucket starts full so short bursts pass without
  waiting.
"""

from __future__ import annotations

import threading
import time


class TokenBucket:
    """Thread-safe leaky token bucket.

    Parameters
    ----------
    rate:
        Steady-state rate at which tokens replenish, in tokens per second.
        EDGAR uses 10.0 (10 req/s); FRED 2.0; BLS 0.0058 (~500/day);
        BEA 1.66 (~100/min).
    capacity:
        Maximum tokens that can accumulate. Defaults to ``max(1, rate)`` —
        a 1-second burst budget. Set explicitly for sources that document
        a different burst tolerance (e.g. EDGAR allows ~10 req/s but the
        documentation also caps a 600s burst).
    """

    def __init__(self, rate: float, capacity: float | None = None) -> None:
        if rate <= 0:
            raise ValueError(f"rate must be > 0, got {rate}")
        self._rate = rate
        self._capacity = capacity if capacity is not None else max(1.0, rate)
        self._tokens = self._capacity
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> None:
        """Block until ``tokens`` are available, then consume them."""
        if tokens > self._capacity:
            raise ValueError(f"requested {tokens} tokens but bucket capacity is {self._capacity}")
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                wait = deficit / self._rate
            # Sleep outside the lock so other threads can refill themselves.
            time.sleep(wait)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now


__all__ = ["TokenBucket"]
