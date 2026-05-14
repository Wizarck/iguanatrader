# Retrospective: strategy-macd-cross + bundled hoist

- **PR**: [#157](https://github.com/Wizarck/iguanatrader/pull/157) (merged 2026-05-14, squash `f885444`).
- **Archive path**: `openspec/changes/archive/2026-05-14-strategy-macd-cross/`
- **Lines shipped**: macd_cross.py + test_macd_cross.py + `_indicators.py` extraction + 4 import-and-replace edits.

## What worked

- **Conditional hoist bundled with MACD** — parallel session correctly identified that bundling the `_compute_atr` hoist into the MACD slice was cleaner than a standalone chore PR (which would have been mechanically merge-conflict-prone with whatever strategy landed next). Net: 1 PR with a wider blast radius vs 2 PRs needing cross-PR sequencing.
- **Appel canonical defaults** — `fast=12 slow=26 signal=9` mirrors the de-facto retail MACD spec. Reasoning dict includes both raw `macd` + `signal` values for operators to audit.
- **Optional MACD-bias filter** — `bias_threshold` param lets operators require MACD > 0 (bull regime) before signaling, reducing false positives in choppy/bear conditions.

## What didn't

- **Parallel-session race vs my chore-hoist PR #158** — I authored a standalone `chore-hoist-strategy-indicators` slice + opened PR #158 ~15 min before MACD #157 merged. Once #157 landed (which already hoisted), my PR became redundant. Recovery: closed PR #158 (`gh pr close --delete-branch`), no harm done. **Pre-flag**: when multiple Claude sessions are operating on the same repo, the main agent should `git fetch origin --prune && git log --oneline -5 origin/main` BEFORE opening a new chore PR to detect parallel work. The 30-second cost prevents the 30-minute redundancy.
- **My PR #158 mislabelled donchian test failure as "Windows-Decimal-precision flake"** — actually a real algorithmic bug in `donchian_atr._compute_signal_impl` (`window_highs` included `bars[-1].high`, making `latest_close < channel_high` always-true). Parallel session correctly diagnosed via PR #157 agent's report → wrote `fix-donchian-channel-bounds` proposal. **Pre-flag for future self**: before labeling a test failure as a "platform flake", run the same test on a known-clean baseline (e.g. `git stash` round-trip OR `git worktree add` from origin/main). If it fails there too, it's NOT a flake — it's either a pre-existing bug OR a baseline regression. Both demand investigation, not deferral.

## Carry-forward

- **`fix-donchian-channel-bounds`** — shipped as next slice. The donchian breakout has been silently non-functional since slice T3 (signals always suppressed). Critical fix.
- **CI runs `--collect-only`, not full pytest** — flagged in `fix-donchian-channel-bounds` proposal §"Why". Until coverage hits 80%, real pytest doesn't gate PRs. The donchian bug went undetected for ~2 weeks because of this. Carry-forward: revisit CI gating once coverage push lands.

## Pattern usage

- **Bundle mechanical-refactor with feature-slice when ordering benefits clarity** — the hoist standalone would have needed a chore PR + a feature PR (MACD). Bundling collapses to 1 PR with `_indicators.py` extraction + MACD addition + 3 caller updates. Reviewer reads it as "extract + extend in one move".
- **Parallel-session detection ritual** — `git fetch origin --prune && git log --oneline -5 origin/main` before opening a chore PR catches in-flight work from other agents.
- **"Windows flake" hypothesis demands baseline test** — don't accept the hypothesis without verifying the test passes on origin/main HEAD via `git stash` / worktree. If it doesn't, it's a real bug.
