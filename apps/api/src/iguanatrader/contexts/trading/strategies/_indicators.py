"""Shared technical-indicator helpers for :class:`Strategy` subclasses.

Module-private; not part of the public API. Hoisted out of
``donchian_atr`` after the 4th caller landed (per the
``strategy-macd-cross`` proposal §"``_compute_atr`` reuse" decision —
copy-paste tolerated through the 3rd caller, hoist at the 4th). The
function body is byte-identical to the prior copies in
``donchian_atr.py`` / ``rsi_mean_reversion.py`` / ``bollinger_breakout.py``;
this slice's diff in each of those files is therefore -15 lines (removed
``def _compute_atr``) + 1 line (import).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def _compute_atr(bars: Any) -> Decimal | None:
    """Wilder ATR over ``bars`` — needs at least 2 bars."""
    from itertools import pairwise

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
