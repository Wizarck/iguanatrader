"""Canonical exponential backoff sequence.

Per design decision D7 (slice 2 ``shared-primitives``): IBKR adapter,
Telegram channel, Hermes/WhatsApp channel, and any future live adapter
share a single backoff schedule:

    ``[3, 6, 12, 24, 48]`` seconds

…capped at ``48`` seconds for any attempt index ``>= 4``. Optional
±20% uniform jitter avoids thundering-herd reconnection bursts.

The sequence is intentionally NOT a tunable surface — uniformity makes
it easy to reason about reconnection budgets across the system, and
deviation requires an explicit ADR. See NFR-R7 in the PRD.
"""

from __future__ import annotations

import random

_SEQUENCE: tuple[int, ...] = (3, 6, 12, 24, 48)
_JITTER_FRACTION = 0.2  # ±20%


def backoff_seconds(attempt: int, *, with_jitter: bool = False) -> float:
    """Return the canonical backoff delay for ``attempt`` (0-indexed).

    ``attempt = 0`` returns 3, ``attempt = 1`` returns 6, ``attempt = 2``
    returns 12, ``attempt = 3`` returns 24, ``attempt >= 4`` returns 48
    (capped). Negative ``attempt`` raises :class:`ValueError`.

    When ``with_jitter`` is true, the returned value is uniformly
    sampled from ``[base * 0.8, base * 1.2]`` to avoid synchronised
    reconnect storms across multiple adapters that lost their connection
    at the same instant.
    """
    if attempt < 0:
        raise ValueError(f"attempt must be >= 0, got {attempt}")

    base: int = _SEQUENCE[attempt] if attempt < len(_SEQUENCE) else _SEQUENCE[-1]

    if not with_jitter:
        return float(base)

    low = base * (1 - _JITTER_FRACTION)
    high = base * (1 + _JITTER_FRACTION)
    return random.uniform(low, high)


__all__ = ["backoff_seconds"]
