"""AsyncTokenBucket — async-safe token-bucket rate limiter."""

from __future__ import annotations

import asyncio
import time


class AsyncTokenBucket:
    """Replenishing token bucket with monotonic-clock accounting.

    ``acquire()`` blocks until at least one token is available; on wakeup it
    consumes exactly one token. Concurrent callers serialize on an internal
    lock so the replenish-and-decrement sequence is atomic.
    """

    def __init__(self, *, rate_per_second: float, burst: int | None = None) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        self._rate = float(rate_per_second)
        self._capacity = float(burst if burst is not None else max(1, int(rate_per_second)))
        self._tokens = self._capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def capacity(self) -> float:
        return self._capacity

    @property
    def rate_per_second(self) -> float:
        return self._rate

    async def acquire(self) -> None:
        """Block until a token is available; consume one."""
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                if elapsed > 0:
                    self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                    self._last_refill = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                deficit = 1.0 - self._tokens
                wait = deficit / self._rate
            # Released the lock before sleeping so concurrent acquirers can
            # race fairly on the next refill window.
            await asyncio.sleep(wait)


__all__ = ["AsyncTokenBucket"]
