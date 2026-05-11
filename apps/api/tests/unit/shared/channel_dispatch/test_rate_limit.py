"""Unit tests for :class:`AsyncTokenBucket`.

Timing assertions use generous tolerances (>=) so CI variance doesn't flake.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from iguanatrader.shared.channel_dispatch import AsyncTokenBucket


def test_rejects_non_positive_rate() -> None:
    with pytest.raises(ValueError):
        AsyncTokenBucket(rate_per_second=0)
    with pytest.raises(ValueError):
        AsyncTokenBucket(rate_per_second=-1.0)


@pytest.mark.asyncio
async def test_burst_acquires_are_immediate() -> None:
    # Burst=5, rate=10/s. The first 5 acquires should complete near-instantly
    # (well under 100ms wall time).
    bucket = AsyncTokenBucket(rate_per_second=10.0, burst=5)
    start = time.monotonic()
    for _ in range(5):
        await bucket.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.2


@pytest.mark.asyncio
async def test_acquire_throttles_beyond_burst() -> None:
    # rate=50/s, burst=2 → first 2 instant, then 8 more at 50/s ≈ 160ms total.
    bucket = AsyncTokenBucket(rate_per_second=50.0, burst=2)
    start = time.monotonic()
    for _ in range(10):
        await bucket.acquire()
    elapsed = time.monotonic() - start
    # Strict lower bound: 8 throttled tokens at 50/s = 0.16s. Allow ample
    # upper bound for CI jitter.
    assert elapsed >= 0.12


@pytest.mark.asyncio
async def test_concurrent_acquires_serialize() -> None:
    bucket = AsyncTokenBucket(rate_per_second=10.0, burst=1)
    start = time.monotonic()
    await asyncio.gather(*(bucket.acquire() for _ in range(5)))
    elapsed = time.monotonic() - start
    # 1 burst token + 4 throttled at 10/s = 0.4s minimum.
    assert elapsed >= 0.3
