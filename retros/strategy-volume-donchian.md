# Retrospective: strategy-volume-donchian

- **PR**: [#159](https://github.com/Wizarck/iguanatrader/pull/159) (merged 2026-05-14, squash `7c022e8`).
- **Archive path**: `openspec/changes/archive/2026-05-14-strategy-volume-donchian/`
- **Lines shipped**: 421 insertions across 4 files.

## What worked

- **Channel-high slice corrected from day 1** — uses `bars[-period - 1 : -1]` (the post-fix-donchian-channel-bounds pattern), not the buggy `bars[-lookback:]` inherited from pre-fix donchian. Confirmation that landing fix-donchian (PR #160) is now CRITICAL — otherwise donchian + volume-donchian diverge in semantics.
- **Trailing-volume window also excludes current bar** — `bars[-vol_window - 1 : -1]`. Consistent with channel-high exclusion. Avoids the same "current value bleeds into trailing aggregate" class of bug.
- **6 registered strategies** — STRATEGY_REGISTRY now: donchian_atr, sma_cross, rsi_mean_reversion, bollinger_breakout, macd_cross, volume_donchian. v1.5 strategy catalogue 4-of-4 trend/momentum slots filled (counter-trend = RSI; the rest are breakout/momentum variants).

## What didn't

- **My spawned VolDonchian agent detected pre-existing PR + exited gracefully** — parallel session opened PR #159 before my agent finished pwd-pinning. Agent's report correctly identified the duplicate and stopped (commit `890db74` already on `feat/strategy-volume-donchian`). Pre-flag for future agent prompts: include a Step 0.5 — `git ls-remote --heads origin <expected-branch-name>` returns non-empty → STOP and report "pre-existing PR detected" rather than re-doing the work.

## Carry-forward

- **Branch-exists pre-flight check in agent prompts** — added to mental checklist; consider promoting to `release-management.md` §4.5.7 if 2nd recurrence of parallel-session-races lands.
- **Volume-spike-only variant** — current strategy ANDs Donchian breakout + volume gate. A pure "volume spike → trigger" signal (no Donchian) is a separate strategy, not a parameter. v2 if operators want it.
- **`MIN_BARS` computed from defaults** — could be made dynamic (max(period, vol_window) + atr_period + 2 from config-snapshot params) but the conservative default 36 is fine for now.

## Pattern usage

- **Inherit the fix before the fix lands** — volume-donchian's channel-high slice uses the post-fix pattern (`bars[-period - 1 : -1]`) even though fix-donchian (PR #160) hasn't merged yet. When two slices are in flight and one fixes a bug the other would inherit, the dependent slice should adopt the fix pattern directly + reference the parent slice in its proposal. Saves a rebase-and-fix cycle.
- **`ls-remote pre-flight` for parallel-session detection** — `git ls-remote --heads origin <branch>` is the cheapest probe. If non-empty, another agent (or session) already opened the slice. Don't duplicate.
- **`compute_atr` import (no copy)** — volume-donchian is the 5th caller. `_indicators.py` already exists; just `from ... import compute_atr`. The hoist's value compounds with each new caller.
