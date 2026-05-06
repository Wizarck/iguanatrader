"""Unit tests for the sync token-bucket rate limiter (slice R2)."""

from __future__ import annotations

import threading
import time

import pytest
from iguanatrader.contexts.research.sources._token_bucket import TokenBucket


def test_initial_burst_does_not_block() -> None:
    """A fresh bucket starts full (capacity = max(1, rate)) so the first
    ``acquire`` call returns immediately."""
    bucket = TokenBucket(rate=10.0)
    start = time.monotonic()
    bucket.acquire()
    assert time.monotonic() - start < 0.05


def test_throttles_to_configured_rate() -> None:
    """A bucket with rate=20.0 capacity=2 should take ~0.5s for 12 acquires
    (2 burst + 10 replenishments at 50ms each)."""
    bucket = TokenBucket(rate=20.0, capacity=2.0)
    start = time.monotonic()
    for _ in range(12):
        bucket.acquire()
    elapsed = time.monotonic() - start
    # 12 - 2 = 10 throttled tokens at 20/s = 500ms minimum
    assert elapsed >= 0.45, f"expected >= 450ms, got {elapsed * 1000:.0f}ms"


def test_concurrent_acquires_share_budget() -> None:
    """Two threads pulling from one bucket cumulatively respect the rate."""
    bucket = TokenBucket(rate=10.0, capacity=1.0)

    def worker() -> None:
        for _ in range(3):
            bucket.acquire()

    start = time.monotonic()
    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - start
    # 6 total acquires - 1 burst = 5 throttled at 10/s = 500ms minimum
    assert elapsed >= 0.40


def test_invalid_rate_raises() -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate=0)
    with pytest.raises(ValueError):
        TokenBucket(rate=-1.0)


def test_acquire_more_than_capacity_raises() -> None:
    bucket = TokenBucket(rate=1.0, capacity=2.0)
    with pytest.raises(ValueError):
        bucket.acquire(tokens=5.0)
