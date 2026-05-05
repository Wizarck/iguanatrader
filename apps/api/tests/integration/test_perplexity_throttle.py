"""Integration tests for Perplexity sliding-window throttle (NFR-I4 + design D3).

Test matrix (per task 7.1):

- 11th call within 60s when ``max_rpm=10`` raises
  :class:`PerplexityRateLimitError` with correct ``retry_after_seconds``.
- Calls outside the 60s window do not count toward the cap.
- Concurrent ``acquire()`` calls under :class:`asyncio.Lock` are
  serialised correctly (no double-spend of the rate budget).
- :func:`get_throttle` is process-local singleton; reset hook restores
  a clean state between tests.
"""

from __future__ import annotations

import asyncio

import pytest
from iguanatrader.contexts.observability.errors import PerplexityRateLimitError
from iguanatrader.contexts.observability.perplexity_throttle import (
    PerplexityThrottle,
    get_throttle,
    reset_throttle_for_tests,
)


class _FakeClock:
    """Test-only :class:`ClockPort` — wall-clock advanced by tests."""

    def __init__(self, t0: float = 1000.0) -> None:
        self._t = t0

    def monotonic(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


async def test_eleventh_call_within_window_raises_with_retry_after() -> None:
    clock = _FakeClock()
    throttle = PerplexityThrottle(max_rpm=10, clock=clock)

    for _ in range(10):
        await throttle.acquire()

    with pytest.raises(PerplexityRateLimitError) as excinfo:
        await throttle.acquire()

    assert excinfo.value.retry_after_seconds >= 1
    assert excinfo.value.status == 429
    assert excinfo.value.type == "urn:iguanatrader:error:perplexity-rate-limit"


async def test_calls_outside_window_do_not_count() -> None:
    clock = _FakeClock()
    throttle = PerplexityThrottle(max_rpm=2, clock=clock)

    await throttle.acquire()
    await throttle.acquire()

    # Advance past the 60s window — entries should evict on next acquire.
    clock.advance(61)

    # Now the deque is empty for the active window; we can hit the cap again.
    await throttle.acquire()
    await throttle.acquire()

    assert throttle.queue_length == 2


async def test_concurrent_acquires_serialised_under_lock() -> None:
    clock = _FakeClock()
    throttle = PerplexityThrottle(max_rpm=5, clock=clock)

    async def _try() -> bool:
        try:
            await throttle.acquire()
            return True
        except PerplexityRateLimitError:
            return False

    results = await asyncio.gather(*[_try() for _ in range(8)])
    allowed = sum(1 for ok in results if ok)
    refused = sum(1 for ok in results if not ok)
    assert allowed == 5
    assert refused == 3
    assert throttle.queue_length == 5


def test_get_throttle_singleton_with_reset() -> None:
    reset_throttle_for_tests()
    a = get_throttle()
    b = get_throttle()
    assert a is b
    reset_throttle_for_tests()
    c = get_throttle()
    assert c is not a
