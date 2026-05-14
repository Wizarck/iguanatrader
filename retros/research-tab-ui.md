# Retrospective: research-tab-ui

- **PR**: [#150](https://github.com/Wizarck/iguanatrader/pull/150) (merged 2026-05-14, squash `8222a75`).
- **Archive path**: `openspec/changes/archive/2026-05-14-research-tab-ui/`
- **Lines shipped**: 875 insertions / 8 deletions. CI 15/15 green on first push (incl. Lighthouse a11y ≥95).

## What worked

- **"STOP after gh pr create" instruction** kept this agent's wall-time to ~6min — same saving as PR #149. Pattern is now proven across both parallel agents.
- **Pure helpers + impure glue split** — `parseRecent` + `recordRecent` + `isValidSymbol` live in `$lib/research/recent.ts` as DOM-free pure functions; SSR-safe `readRecent`/`writeRecent` glue handles the `localStorage` calls. 20 vitest cases on the pure side, no jsdom needed.
- **Case-insensitive dedupe with uppercase coercion** — input coerced to uppercase before recording. Matches the strategies-config-ui symbol pattern (`^[A-Z0-9]{1,16}$`) so "spy" and "SPY" don't both end up in recent.
- **Minimal touch on the existing `[symbol]/+page.svelte`** — 5-line `$effect` hook + 1 import. Zero changes to the brief-rendering body shipped in R5/R6.
- **Pills as native `<a href>`** — focusable, keyboard-navigable, no JS-only navigation. Lighthouse a11y ≥95 passed first-push.
- **Last dashboard tab is live** — all 7 sidebar tabs now real, zero `PlaceholderCard` instances in `apps/web/src/routes/(app)/*/+page.svelte`.

## What didn't

- **Pre-existing `RiskUtilisationCard.svelte:73` svelte-check error noted** by the agent but proved benign — CI on Linux passed `pnpm check` cleanly for both #149 and #150. The error only surfaces in the Windows agent's local `pnpm check`. Likely a platform-specific svelte-check tooling quirk. Worth investigating in a follow-up `chore-svelte-check-windows-parity` if more agents flag it.
- **`pnpm check` exits non-zero on Windows but green on Linux CI** — agents have been warning about this pattern; not a regression but a tooling-platform-parity gap. Pre-flag: when an agent reports `pnpm check` failure, double-check by querying CI before treating as a blocker.

## Carry-forward

- **Server-backed watchlist** (`GET /research/watchlist`) — v1.5 if operators want cross-device sync.
- **Bulk refresh from landing** — currently each symbol's detail page has its own refresh button.
- **Brief preview on hover** — would need an additional fetch per pill; defer.
- **Symbol auto-complete** — needs a symbols-catalogue endpoint. v1.5.

## Pattern usage

- **Pure helpers + impure glue split** — when a module needs both pure logic and platform-specific side effects (localStorage / fetch / setTimeout), extract the pure half into `$lib/<domain>/<name>.ts` and keep the impure glue in the component. Pure tests run without jsdom; glue tests can be Storybook + Playwright. Pattern reusable for any "stateful UI helper".
- **Case-insensitive dedupe with uppercase coercion** — when the domain has an uppercase convention (IBKR symbols), coerce on read AND on write to keep the storage tidy.
- **`$effect` for one-shot mount hooks** — Svelte 5 idiom for "do this when the component mounts" (e.g., record a visited symbol). Cleanup function optional.
- **Native `<a href>` over JS click handlers** — pills, breadcrumbs, navigation. Free a11y; no `goto` glue needed.
- **STOP after gh pr create** — proven across 2 parallel agents (#149 + #150). Lock into the template.
