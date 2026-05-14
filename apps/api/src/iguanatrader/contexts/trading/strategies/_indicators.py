"""Shared technical indicators used across multiple strategies.

Single-source-of-truth for indicator helpers that 2+ strategies need.
Adding a helper here is a one-time lift; strategies import + call.
"""

from __future__ import annotations

from decimal import Decimal
from itertools import pairwise
from typing import Any


def compute_atr(bars: Any) -> Decimal | None:
    """Wilder ATR over ``bars`` — needs at least 2 bars.

    Returns the average true range as a Decimal, or None if the input
    has fewer than 2 bars.
    """
    if len(bars) < 2:
        return None
    true_ranges: list[Decimal] = []
    for prev, cur in pairwise(bars):
        tr1 = cur.high - cur.low
        tr2 = abs(cur.high - prev.close)
        tr3 = abs(cur.low - prev.close)
        true_ranges.append(max(tr1, tr2, tr3))
    if not true_ranges:
        return None
    total = sum(true_ranges, Decimal("0"))
    return total / Decimal(len(true_ranges))


__all__ = ["compute_atr"]
