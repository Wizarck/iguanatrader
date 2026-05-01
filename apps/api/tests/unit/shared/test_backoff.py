"""Unit tests for :mod:`iguanatrader.shared.backoff`."""

from __future__ import annotations

import pytest
from iguanatrader.shared.backoff import backoff_seconds


class TestCanonicalSequence:
    @pytest.mark.parametrize(
        ("attempt", "expected"),
        [
            (0, 3.0),
            (1, 6.0),
            (2, 12.0),
            (3, 24.0),
            (4, 48.0),
        ],
    )
    def test_indexed_values(self, attempt: int, expected: float) -> None:
        assert backoff_seconds(attempt) == expected

    @pytest.mark.parametrize("attempt", [5, 6, 10, 100, 1000])
    def test_caps_at_48(self, attempt: int) -> None:
        assert backoff_seconds(attempt) == 48.0

    def test_negative_attempt_raises(self) -> None:
        with pytest.raises(ValueError, match="must be >= 0"):
            backoff_seconds(-1)


class TestJitter:
    def test_no_jitter_returns_exact_base(self) -> None:
        # No jitter: deterministic, always equals the base sequence value.
        for attempt, expected in enumerate([3.0, 6.0, 12.0, 24.0, 48.0]):
            assert backoff_seconds(attempt) == expected

    def test_jitter_within_twenty_percent(self) -> None:
        # 1000 samples at attempt=0 (base 3.0); each must lie in
        # [3.0 * 0.8, 3.0 * 1.2] = [2.4, 3.6].
        for _ in range(1000):
            v = backoff_seconds(0, with_jitter=True)
            assert 2.4 <= v <= 3.6

    def test_jitter_distribution_spans_range(self) -> None:
        # Sanity: across many samples the jittered output is not a single
        # constant. (Defensively guards against a future regression where
        # jitter calls a misseeded RNG and always returns the base.)
        samples = {backoff_seconds(0, with_jitter=True) for _ in range(100)}
        assert len(samples) > 10  # arbitrary low-bar; observed >>50 in practice
