# Proposal: chore-hoist-strategy-indicators

> **Hoist `_compute_atr` from 3 strategy modules to a shared `_indicators.py` module.** Mechanical extraction; 3 callers now justifies the lift (decision A in each strategy's proposal was "copy until 3rd caller — then hoist"). No behavioural change.

## Why

As of 2026-05-14, `_compute_atr` exists verbatim in 3 strategy modules:
- `apps/api/src/iguanatrader/contexts/trading/strategies/donchian_atr.py` (original)
- `apps/api/src/iguanatrader/contexts/trading/strategies/rsi_mean_reversion.py` (PR #155 copy)
- `apps/api/src/iguanatrader/contexts/trading/strategies/bollinger_breakout.py` (PR #156 copy)

Each strategy's proposal explicitly deferred the hoist with a `# strategies-indicators-shared` forward-pointer comment, gated on "3rd caller". That condition is now met. Continuing to copy at the 4th caller (MACD or VolDonchian, both queued) would accumulate the bug-risk of divergent copies for no abstraction gain.

## What

### New module

`apps/api/src/iguanatrader/contexts/trading/strategies/_indicators.py`:

```python
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
```

Note: drops the underscore prefix (`_compute_atr` → `compute_atr`) since this is now a module-level public helper, not module-private. The leading underscore was correct when copied; now that the function is the documented entry point of a shared module, drop it.

### Replace in 3 strategies

Each of the 3 strategy modules:
1. Add `from iguanatrader.contexts.trading.strategies._indicators import compute_atr`
2. Replace `atr = _compute_atr(bars[...])` → `atr = compute_atr(bars[...])`
3. Delete the local `_compute_atr` function definition + the forward-pointer comment above it.

### No public API change

`Strategy` ABC unchanged. `STRATEGY_REGISTRY` unchanged. `__all__` exports in `__init__.py` unchanged (we don't expose `_indicators` at the package level — strategies import directly).

### Tests

No new tests. The 3 strategy unit tests cover ATR behaviour through their respective `_compute_signal_impl` paths. The hoist is mechanical: behaviour preserved by definition.

Property-based no-lookahead test still passes (it iterates `STRATEGY_REGISTRY` and runs `evaluate` — internal ATR helper location is invisible to it).

## Out of scope

- **Hoisting other duplicated helpers** (`_to_decimal`, `_sma`) — only ATR meets the 3-caller threshold today. `_to_decimal` is also duplicated 3× but is so trivial (5 lines) that hoisting it would create more cognitive overhead than it saves. Revisit if a 4th strategy needs the same helper.
- **Public-API exposure of indicators** — `_indicators.py` is intentionally package-internal. If external consumers ever need `compute_atr` (e.g. for a custom strategy plugin), that's a separate decision about strategy-extension surface; not this slice.
- **Renaming `compute_atr` to `wilder_atr`** — name change is bikeshedding; "ATR" is industry-standard for Wilder's mean of true ranges. Keep.

## Acceptance

- `_indicators.py` exists with `compute_atr`.
- All 3 strategy modules import + use `compute_atr` (no local copies remain).
- `pytest apps/api/tests/unit/contexts/trading/strategies/ apps/api/tests/property/test_strategy_no_lookahead.py` — all tests pass with no behavioural change.
- mypy --strict + ruff + black clean on touched files.
- Grep `git grep "_compute_atr"` returns 0 hits in `apps/api/src/`.
