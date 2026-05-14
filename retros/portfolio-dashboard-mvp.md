# Retrospective: portfolio-dashboard-mvp

- **PR**: [#144](https://github.com/Wizarck/iguanatrader/pull/144) (merged 2026-05-14, squash `234dc02`).
- **Archive path**: `openspec/changes/archive/2026-05-14-portfolio-dashboard-mvp/`
- **Lines shipped**: 1197 insertions / 11 deletions across N files. CI 14/14 green on first push.

## What worked

- **Slice-pattern re-use end-to-end** — `EmptyState`, `Badge`, `DataTable` all came from α ([[trades-list-and-detail]], PR #141) with zero re-extraction. `+page.server.ts` parallel-fetch pattern copied verbatim from `(app)/trades/+page.server.ts`. The dashboard "summary card + chart + table" template is now genuinely reusable for the next 4 dashboard slices.
- **Backend-first slicing chain paid off** — the previous 2 slices ([[trading-routes-portfolio-strategies-bodies]] PR #142 + [[portfolio-pnl-and-equity-series]] PR #143) had pre-shipped exactly the DTO shape this UI consumed. Zero scope creep, zero "backend gap discovered mid-slice" surprises. Validates the audit-before-slice pattern from PR #142 retro.
- **Re-scoped proposal vs original** — the 2026-05-13 first draft of this proposal assumed top-level `total_value` / `day_pnl` fields that didn't exist. Re-scoping against the actual `PortfolioSummaryOut { equity, open_trades, open_orders, day_pnl_abs, day_pnl_pct }` shape took ~10 min and produced a clean spec. Cheap fix; the alternative (shipping UI against imagined contract) would have been a wasted slice.
- **Step 0 worktree-isolation prevention** WORKED again. Second consecutive agent spawn with the `pwd`-pinning preamble; zero rogue writes to main checkout. Pattern is reliable now — pin to the prompt template for every future code-writing agent.
- **Honest "—" rendering for null fields** — `last_price` / `unrealized_pnl` / `avg_entry_price` / `day_pnl_abs/pct` all render as em-dash when null instead of fake-zero or skeleton-forever. Frontend ships ready for when `market-data-snapshot-port` lands the live values; no UI change needed at that point.
- **Lighthouse a11y ≥95 first-push** — semantic `<dl>`/`<dt>`/`<dd>` markup for the summary cells + `<svg role="img" aria-label="...">` on the sparkline + Spanish copy throughout passed without any tweaks.
- **Pure-helper extraction** — `buildSparklinePath`, `formatMoney`, `formatPercent` all extracted to `$lib/portfolio/{sparkline,format}.ts` as DOM-free pure functions. Unit-testable + reusable from any future SVG/format consumer.

## What didn't

- **Nothing notable**. CI green on first push, no fix rounds, no env quirks bit on the frontend side. The Windows-venv linter hang from PR #143 didn't apply (this slice is all SvelteKit; `pnpm` toolchain is fast on Windows).

## Carry-forward

- **Position drill-down** to `/portfolio/{trade_id}` — separate slice (`portfolio-position-detail`). Row click currently does nothing; the `DataTable` already supports `onRowClick`.
- **SSE realtime updates** — page is `load`-fn driven; refresh requires nav. `portfolio-sse-realtime` is a separate slice once SSE infra extends past `/approvals`.
- **Per-tenant currency formatting** — `formatMoney` hard-codes USD via `Intl.NumberFormat('en-US', {currency: 'USD'})`. SaaS multi-currency = v1.5 (`portfolio-currency-formatting`).
- **Chart-lib upgrade** — bare SVG sparkline is sufficient for MVP. Choose a lib (Plotly/Chart.js/uPlot) only when a future slice needs candlestick / multi-series / zoom (likely the live trading view in v2).
- **`market-data-snapshot-port`** — when that slice lands, `last_price` / `unrealized_pnl` populate automatically; the positions table already handles them as live values without code change.
- **Sparkline X-axis tick labels** — currently only the hover tooltip shows dates. Explicit axis labels defer to follow-up if operators ask.

## Pattern usage

- **`+page.server.ts` parallel-fetch with `loadError` collapse** — same pattern as α; same pattern future dashboard slices will use. Three failure modes (404 from any of N endpoints, 5xx, network throw) all collapse to a single `loadError: string`. Renderer switches on `loadError` first, then on data shape.
- **Empty-state triggering on the "all-three-empty" condition** — `snapshot_kind === "empty"` AND `positions.length === 0` AND `equity_series.length === 0`. Partial-empty cases (e.g., snapshot exists but no series yet) render the summary with placeholders, not the EmptyState card. This honest-by-design partial-render is reusable for any "X-or-empty" dashboard tab.
- **Pure-function extraction for chart paths + format helpers** — `buildSparklinePath` / `formatMoney` / `formatPercent` live in `$lib/portfolio/{sparkline,format}.ts` as DOM-free pure functions. Pattern: any function that maps data to a visual artifact (SVG path / formatted string / colour token) belongs in a pure module, not inside the `.svelte` script tag. Unit tests run without `jsdom`.
- **Honest null rendering** — em-dash "—" for any null Decimal-valued field. Decision: NEVER render `null` as "0" or as "—%". Either a real number (formatted via `Intl`) or a single em-dash. Distinguishes "data not present" from "data present and zero" — load-bearing for trading UIs where zero is a real state.
- **`Number(decimalString)` for chart plotting** — bounded to plot precision (~240 pixels), JS Number is fine. One-line WHY comment in the sparkline component documents that this is plot-only, never for display or arithmetic. Pattern reusable for any visual mapping of bounded `Decimal | None` values.
- **Step 0 worktree-pinning + scoped linters** — proven twice now (PRs #143 + #144). The Step 0 preamble + "scope linters to touched files" preflag is reliable. Lock into the agent-spawn prompt template.
