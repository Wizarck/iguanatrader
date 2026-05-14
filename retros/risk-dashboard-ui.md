# Retrospective: risk-dashboard-ui

- **PR**: [#148](https://github.com/Wizarck/iguanatrader/pull/148) (merged 2026-05-14, squash `076bed6`).
- **Archive path**: `openspec/changes/archive/2026-05-14-risk-dashboard-ui/`
- **Lines shipped**: 875 insertions / 12 deletions. CI 15/15 green on first push (Lighthouse a11y ≥95 both runs).

## What worked

- **Threshold-tier mapper as a pure function** — `utilisationBarColour(ratio)` in `$lib/risk/colour.ts` maps ratio to `success`/`accent`/`destructive` outside any component. Unit-testable without DOM (4 tier cases + edge). Same hoist pattern as portfolio's `sparkline.ts`/`format.ts` and strategies' `STRATEGY_KIND_DEFAULTS`.
- **`role="progressbar"` + `aria-valuenow`/`aria-valuemax`** for utilisation bars passed Lighthouse a11y first-push. Critical for trading dashboards where screen-reader operators need real-time risk state.
- **Kill-switch indicator as `Badge` reuse** — no new component, just `Badge variant="destructive"` when active, `"success"` otherwise. The α component library pays off.
- **Empty-state composability** — triggers only on the all-zero condition (utilisation + capital + open positions all zero). Partial-zero states render real cards with `formatPercent(0)` — distinguishes "system idle" from "system running but no risk consumed yet".
- **Reuse of `formatMoney`/`formatPercent`** from portfolio retro discipline kept Decimal math in Python; the UI formats display-only strings.

## What didn't

- **Agent timed out at the "wait for CI" step** — same pattern as PR #143. The agent wrote all the code (3 components, 2 helpers, 2 test files, 9 storybook variants) and reached the CI-watch step, then ran out of task budget. Parent took over: commit + push + open PR + monitor merge. Pre-flag: future agent prompts should explicitly say "after `git push` returns, report PR URL and END — DO NOT watch CI in the agent's own session; the parent will monitor." Saves the agent ~10min of idle waiting against its budget.

## Carry-forward

- **`POST /risk/override` UI** — separate slice (`risk-override-ui`); requires the proposal-id + risk-evaluation-id flow which only makes sense after `/approvals` UI lands (now done in PR #146 — unblocked).
- **SSE realtime** (`/stream/risk/events`) — page is `load`-fn driven. `risk-sse-realtime` is a separate slice once SSE infra extends.
- **Per-proposal `per_trade` utilisation** — backend says this is per-evaluation event; surfaces in `/approvals` UI, not here.
- **Historical drawdown chart** — overlaid sparkline of `peak_to_trough_drawdown_pct` over time. v1.5.

## Pattern usage

- **Pure tier mapper extracted to `$lib/<domain>/colour.ts`** — anywhere a threshold-to-colour mapping appears, extract it as a pure function. Three slices now follow this pattern (`portfolio/format.ts`, `costs/format.ts`, `risk/colour.ts`).
- **`role="progressbar"`** for any utilisation/progress visualisation — Lighthouse-friendly, screen-reader-friendly, costs nothing.
- **`Badge` for binary indicators** (kill-switch, enabled/disabled) — never re-extract; always reuse from α's component library.
- **Empty-state triggers ALL-empty, not partial** — pattern continues from portfolio. Distinguishes "no data" from "real-zero values".
- **Agent-prompt update**: tell future agents to push + report + EXIT, not watch CI in-session. Saves wall-time.
