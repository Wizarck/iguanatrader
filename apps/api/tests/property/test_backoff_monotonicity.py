"""Property test: backoff sequence is monotonically non-decreasing."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st
from iguanatrader.shared.backoff import backoff_seconds


@given(attempt=st.integers(min_value=0, max_value=1000))
def test_monotonic_non_decreasing(attempt: int) -> None:
    """For any non-negative attempt: ``backoff(n+1) >= backoff(n)``."""
    assert backoff_seconds(attempt + 1) >= backoff_seconds(attempt)


@given(attempt=st.integers(min_value=4, max_value=10000))
def test_capped_at_48_for_large_attempts(attempt: int) -> None:
    """Beyond the canonical sequence length, every value is the cap (48)."""
    assert backoff_seconds(attempt) == 48.0


@given(attempt=st.integers(min_value=0, max_value=1000))
def test_jittered_values_within_twenty_percent(attempt: int) -> None:
    """Jittered output lies in ``[base * 0.8, base * 1.2]`` for any attempt."""
    base = backoff_seconds(attempt)  # un-jittered ground truth
    sample = backoff_seconds(attempt, with_jitter=True)
    assert base * 0.8 <= sample <= base * 1.2
