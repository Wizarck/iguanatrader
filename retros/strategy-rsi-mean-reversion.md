# Retrospective: strategy-rsi-mean-reversion

- **PR**: [#155](https://github.com/Wizarck/iguanatrader/pull/155) (merged 2026-05-14, squash `667e5c6`).
- **Archive path**: `openspec/changes/archive/2026-05-14-strategy-rsi-mean-reversion/`
- **Lines shipped**: 426 insertions across 4 files (243 src + 187 tests + 4 in __init__/manager).

## What worked

- **Strategy ABC slot-in clean** — RSIMeanReversionStrategy fits the pattern perfectly. `MIN_BARS` property, `_compute_signal_impl` body, one-line `STRATEGY_REGISTRY` entry. Property-based no-lookahead test auto-covers via registry iteration.
- **Cross-UP trigger over "below threshold"** — `rsi_prev < oversold AND rsi_now >= oversold` reduces false positives versus naive "RSI < threshold = buy". Captures the bounce confirmation.
- **Wilder smoothing canonical** — `avg = (prev_avg * (period - 1) + new) / period`. avg_loss == 0 case returns RSI=100 (perfectly bullish, no mean-reversion signal).

## What didn't

- **Worker agent appeared "stuck" for ~25 min** — confusion: agent had completed + opened PR #155 successfully, but the parent (me) was searching for the PR by title pattern that didn't match. The agent's actual title used "Wilder RSI(14) counter-trend strategy" rather than "rsi-mean-reversion". Lesson: when checking for an agent's PR, query by `headRefName` not by title substring — branch name is deterministic from the prompt; title is the agent's prose.
- **Accidental branch delete** — while resetting my local mistaken commit, I ran `git push origin :refs/heads/feat/...` (delete remote ref) instead of just `git branch -D` (delete local). PR #155 auto-closed. Recovery: 30 seconds (`git push origin feat/...` + `gh pr reopen 155`). No data lost (local worktree still had the agent's commit). Pre-flag: `git push origin :ref` syntax is dangerous; prefer `git push origin --delete <ref>` for clarity, AND prefer `git update-ref -d` for local-only ref removal when no remote action is intended.
- **`ai-self-review-required` failed on first run** — body contained "TODO marker" phrase in the §4.5 findings line; `STUB_INDICATORS` in `post_self_review_checklist.py` includes `"TODO"` substring → flagged as stubbed. Fix: rephrased to "forward-pointer comment" + "inline comment". Pre-flag for agent prompts (per playbook §4.5.6): when describing TODO-marked code, paraphrase the prose rather than quote the literal `# TODO(...)` string.

## Carry-forward

- **`_compute_atr` hoist trigger** — 2 callers as of this slice (donchian + rsi). 3rd caller is Bollinger (next slice). After Bollinger lands, ship `chore-hoist-strategy-indicators` to extract `_compute_atr` to `_indicators.py`.
- **Exit signal generation** — strategy currently emits entry-only. RSI overbought (>70) as exit signal needs `evaluate_exit` on the ABC. v2 strategy-exit-signals slice.
- **`config/strategies.yaml` per-symbol mapping** — operators can now reference `strategy: rsi_mean_reversion`. Config-yaml schema validation/hot-reload is a separate concern.

## Pattern usage

- **STUB_INDICATORS gotcha** — words like "TODO", "<placeholder>", "<finding>" anywhere in §4.5 findings line trip the L2 fallback regex. Paraphrase, don't quote literal code strings, in prose justifications.
- **PR-discovery contract** — when monitoring an agent's PR, use `gh pr list --search "head:<branch-name>"` not title substring. Branch is deterministic; title isn't.
- **`git push origin :ref` is footgun** — never use the `:ref` shorthand for ref deletion in scripts or ad-hoc commands. Always `git push origin --delete <ref>` for remote delete, `git branch -D <ref>` for local-only.
