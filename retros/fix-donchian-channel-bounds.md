# Retrospective: fix-donchian-channel-bounds

- **PR**: [#160](https://github.com/Wizarck/iguanatrader/pull/160) (merged 2026-05-14, squash `011cdb1`).
- **Archive path**: `openspec/changes/archive/2026-05-14-fix-donchian-channel-bounds/`
- **Lines shipped**: 57 insertions / 20 deletions across 2 files. CI 15/15 verde primer push. Agent wall-time: 126 seconds (new record).

## What worked

- **Smallest agent task duration to date** — 126s end-to-end (proposal already on main, fix is 2-line slice change + test refactor). Confirms the §4.5.5 STOP-after-`gh pr create` pattern compounds with small slices: no idle time, agent exits immediately, parent monitors CI.
- **Root-cause was algorithmic, not platform** — the donchian-breakout test failure I flagged in PR #158 as "Windows-Decimal-precision flake" was a real bug. `window_highs` included `bars[-1].high`, making `latest_close < channel_high` impossible to satisfy. The strategy had been silently non-functional since slice T3 (~2 weeks). Parallel session caught it; my mistake.
- **`_ramp_history` refactor** — spike at `n-2` instead of `n-1` means the wrapper's `bars[:-1]` truncation leaves the breakout as the visible top-bar. Plus a new `test_donchian_no_signal_when_close_below_channel` regression test guards against re-introducing the old (always-true) semantics.

## What didn't

- **My initial misdiagnosis** — labeling the test failure as a platform flake delayed the fix by hours. The parallel session caught it independently. Pre-flag (also captured in PR #157 retro): never deferred-as-flake without `git stash` round-trip on origin/main HEAD. If the failure reproduces on a clean baseline, it's a real bug.
- **CI gating gap** — `.github/workflows/ci.yml` runs `pytest --collect-only` for the trading domain, NOT real execution. The donchian bug went undetected because the failing test was never actually run server-side. Carry-forward: revisit CI gating once coverage push lands (see proposal §"Why" + project memory `ci-pytest-collect-only`).

## Carry-forward

- **CI: real pytest gate** — once test coverage hits 80%, flip the workflow to run full pytest. Until then, trust scoped-touched-files only. **Risk**: same class of silent-suppression bug could land again in any strategy. Mitigation: include strategy-emits-proposal-on-positive-case as a smoke-test gate in every strategy slice's CI matrix.
- **Symmetric short-side fix** — strategy is long-only in v1.5; sell-side comes with shorting support.
- **Other v1.0 strategies audit** — sma_cross is the other v1.0 strategy. Does it have similar off-by-one issues? Worth a one-time audit slice (`audit-strategy-window-semantics`).

## Pattern usage

- **Spike-at-n-2 over spike-at-n-1** — when synthetic test data must survive a `bars[:-1]` wrapper truncation, place the signal-triggering event at the second-to-last bar. The wrapper drops the last; the truncated view's `bars[-1]` IS the signal.
- **Regression test for buggy-old-semantics** — when fixing a "X was always true" bug, add a test that asserts X is NOT always true (e.g., `test_donchian_no_signal_when_close_below_channel`). Locks the fix.
- **Two-line fix can warrant a full slice** — if a bug is silent + critical (entire strategy non-functional), a dedicated PR + retro is correct even for a 2-line code change. Avoids "buried in unrelated PR" archaeology later.
