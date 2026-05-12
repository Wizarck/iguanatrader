# Retrospective: research-frontend-storybook

> **Forward-authored** — fill at archive.

- **PR**: [#120](https://github.com/Wizarck/iguanatrader/pull/120) (merged 2026-05-12, squash `9c1bf7b`).
- **Archive path**: `openspec/changes/archive/2026-05-12-research-frontend-storybook/`
- **Lines shipped**: 1094 insertions / 4 deletions across 14 files. CI 12/12 verde **al primer push** (zero fix rounds; 1 local svelte-check round caught Storybook ↔ Svelte 5 typing mismatch).

## What worked

- **Local `pnpm build-storybook` as the verification gate** — finished in ~5s and validated the entire pipeline (Vite, story discovery, addon-a11y, framework adapter). svelte-check failed on the same code but the runtime build passed; this is the right tradeoff (build = truth; typecheck = ecosystem gap).
- **`Meta` instead of `satisfies Meta<Component>`** avoids the Svelte 4 vs 5 generic mismatch upfront. Documented inline in each story file so future contributors don't waste time "fixing" it.
- **`tsconfig.json` exclude for `*.stories.ts`** — pragmatic. svelte-check stays clean; Storybook runtime validates args via Controls. The exclude is a known compromise documented in the proposal.
- **3 addon footprint** (`@storybook/sveltekit` + core + `@storybook/addon-a11y`) — Storybook 9+ bundles the canonical essentials, so the older `@storybook/addon-essentials` (which auto-installed with peer-dep conflicts on the v8 release line) was unnecessary.

## What didn't

- **Initial install pulled `@storybook/addon-essentials@8.6`** with `storybook@10` → peer-dep conflict warning. Resolved by removing the addon (essentials are bundled in core for v9+). Pre-flag candidate: when installing the Storybook bundle, prefer `pnpm dlx storybook init` (auto-resolves matching versions) or specifically pin to the major.
- **First-attempt `satisfies Meta<Component>`** triggered 10+ svelte-check errors against Storybook's Svelte 4 generic shape. Two rounds of refactor (drop `satisfies`, then exclude `*.stories.ts` from svelte-check) to land cleanly. Pre-flag: Storybook v10 typings + Svelte 5 runes are not yet fully aligned; budget for a workaround pattern when adding stories.

## Carry-forward

- **CI `build-storybook` job** — 1-line GitHub Actions step that runs `pnpm build-storybook` on PR. Catches story breakage before merge.
- **`@storybook/addon-svelte-csf`** for `.stories.svelte` files — co-locates story scaffolding with the component's native template syntax. Adds a small dependency but improves DX.
- **`@storybook/test` + interaction tests** — once stories accumulate, interactive flow tests (click, fill, assert) could replace some Playwright assertions. Trade-off: Storybook test runner adds CI weight.

## Pattern usage

- **First Storybook slice in iguanatrader** — sets the precedent for component-level documentation. Future slices that touch UI can add stories alongside the component edit for free.
- **Untyped `Meta` over `satisfies Meta<Component>`** — known Svelte 5 / Storybook 10 typing gap; documented in story files inline so contributors don't waste time trying to "fix" it.
- **`tsconfig.json` exclude for `*.stories.ts`** rather than fighting the type mismatch — pragmatic; Storybook runtime validates the args via Controls.

## Carry-forward

- **CI `build-storybook` job** — 1-line GitHub Actions step that runs `pnpm build-storybook` on PR. Catches story breakage before merge.
- **`@storybook/addon-svelte-csf`** for `.stories.svelte` files — co-locates story scaffolding with the component's native template syntax. Adds a small dependency but improves DX.
- **`@storybook/test` + interaction tests** — once stories accumulate, interactive flow tests (click, fill, assert) could replace some Playwright assertions. Trade-off: Storybook test runner adds CI weight.

## Pattern usage

- **First Storybook slice in iguanatrader** — sets the precedent for component-level documentation. Future slices that touch UI can add stories alongside the component edit for free.
- **Untyped `Meta` over `satisfies Meta<Component>`** — known Svelte 5 / Storybook 10 typing gap; documented in story files inline so contributors don't waste time trying to "fix" it.
- **`tsconfig.json` exclude for `*.stories.ts`** rather than fighting the type mismatch — pragmatic; Storybook runtime validates the args via Controls.
