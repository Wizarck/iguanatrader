# Retrospective: strategy-bollinger-breakout

- **PR**: [#156](https://github.com/Wizarck/iguanatrader/pull/156) (merged 2026-05-14, squash `28abbd8`).
- **Archive path**: `openspec/changes/archive/2026-05-14-strategy-bollinger-breakout/`
- **Lines shipped**: 544 insertions across 4 files. CI 15/15 verde primer push.

## What worked

- **Squeeze filter as optional param** — `squeeze_threshold = None` default keeps signal frequency high; operators opt in by setting e.g. `0.05` (bandwidth < 5% of SMA over prior 6 bars) to filter for breakouts-after-compression. Clean separation between "show me every breakout" vs "show me high-conviction breakouts".
- **Strict `>` over upper band** — `closes[-1] > upper_band` (not `>=`). Touching the band exactly should not fire; must clear it. Test 3 validates the boundary explicitly.
- **9 unit tests + 4 property tests** — agent shipped 3 sanity tests beyond the proposal's 6. Coverage strengthened without scope creep.
- **§4.5.6 language hygiene followed first try** — agent's prompt included the "avoid TODO literal in findings line" guidance from PR #155 retro; first push had clean `ai-self-review-required`.

## What didn't

- **Agent took ~27 min wall-time** — longer than RSI (~25 min) and PR #152 (~8 min). Cause: 2 iterations of ruff fixes (`RUF002` ambiguous-σ Unicode + `RUF022` unsorted `__all__`). The first iteration's fixes triggered the second's. Pre-flag: when an agent's first lint round produces fixes, MUST re-run the FULL lint stack (ruff + black + mypy) before declaring done — `__all__` reorder can fail black even if ruff passes.
- **External worktree rename** mid-task (`agent-a24dd1ece7b46193a` → `agent-ac9055d7ad40cb89f`) — appears benign (files survived intact, PR opened correctly). Cause unclear; possibly Windows file-handle quirk or fleet-orchestration rename. Filed as observational; no action required unless recurrence.

## Carry-forward

- **3rd ATR caller landed → ready to hoist** — `_compute_atr` now copied in `donchian_atr.py`, `rsi_mean_reversion.py`, `bollinger_breakout.py`. The TODO-marker condition (3rd caller) is met. Ship `chore-hoist-strategy-indicators` next, BEFORE MACD slice (if MACD doesn't need ATR, defer to 4th caller).
- **Bollinger mean-reversion variant** (long at lower band) — explicit out-of-scope per proposal; would overlap RSI mean-reversion's signal regime. Revisit if operators have specific use cases.

## Pattern usage

- **Optional-filter-as-None-default** — clean way to ship a feature behind a runtime opt-in. `squeeze_threshold=None` means filter disabled; operators set to enable. No code branch needed in the strategy beyond `if threshold is not None:`.
- **§4.5.6 language hygiene** — paraphrase ("forward-pointer comment") instead of quoting `# TODO(...)` literal. STUB_INDICATORS regex catches the latter.
- **Test count > proposal count is fine** — agents shipping extra coverage tests beyond proposal §Tests is welcome as long as no scope creep into other features.
